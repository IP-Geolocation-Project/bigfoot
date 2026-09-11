import bz2
import json
import logging
from pathlib import Path
import threading
import time
import ipaddress
import concurrent.futures

from ftplib import FTP
from io import BytesIO
from typing import Optional
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
import urllib3
import requests

from ripe.atlas.cousteau import (
    Ping,
    AtlasSource,
    AtlasCreateRequest,
    AtlasResultsRequest,
)
from ripe.atlas.cousteau.source import MalFormattedSource
from pyrate_limiter import Limiter, Duration, Rate

from bigfoot.measurements import MeasurementStatus
from bigfoot.drivers.abstract_driver import AbstractDriver

logger = logging.getLogger(__name__)


class RipePollingDriver(AbstractDriver):
    """
    A driver that connects the system to the RIPE Atlas API to conduct measurements.
    """
    RIPE_API_KEY: str = ""
    SCHEDULING_ATTEMPTS: int = 3
    RIPE_MAX_CONCURRENT_MEASUREMENTS: int = 100

    HIBERNATION_TIME = 360
    FUTURE_OFFSET = 5
    SLEEP_TIME_AFTER_ERROR = 5

    LOAD_CHECKING_THREADS = 50
    INTER_LOAD_CHECKING_BATCH_DELAY = 2.0 # seconds between batch calls
    LOAD_CHECKING_PAUSE = 10.0            # seconds between full load check

    def __init__(self, ripe_api_key: str, scheduling_attempts: int, concurrency_limit: int, measurement_timeout: int, polling_interval: int, max_workers: int):
        """
        A method to initialize the Ripe Polling Driver.
      
        :param: ripe_api_key: str - the API key for the Ripe Atlas.
        :param: scheduling_attempts: int - the maximum number of scheduling attempts.
        :param: concurrency_limit: int - the concurrency limit.
        :param: measurement_timeout: int - the measurement timeout.
        :param: polling_interval: int - the polling interval.
        :param: max_workers: int - the maximum number of workers.
        """
        super().__init__(measurement_timeout, polling_interval, max_workers)
        RipePollingDriver.RIPE_API_KEY = ripe_api_key
        RipePollingDriver.SCHEDULING_ATTEMPTS = scheduling_attempts
        RipePollingDriver.RIPE_MAX_CONCURRENT_MEASUREMENTS = concurrency_limit

        GENERAL_API_RATE = Rate(250, Duration.SECOND)
        MEASUREMENT_API_RATE = Rate(125, Duration.SECOND)

        self.GENERAL_API_LIMITER = Limiter(GENERAL_API_RATE)
        self.MEASUREMENT_API_LIMITER = Limiter(MEASUREMENT_API_RATE)

        self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS = 2
        self.START_TIME = time.monotonic()
        self.lock = threading.Lock()
        self.API_REQUEST_COUNT: defaultdict[str, list[float]] = defaultdict(list)

        self.vps = RipePollingDriver.get_connected_ripe_vps()
        self.metadata['rps'] = {}
        logger.info("start: RipePollingDriver loaded %d connected RIPE VPs from FTP archive", len(self.vps))

    def start(self, *args, **kwargs):
        """
        A method to start the Ripe Polling Driver.
  
        :param: args: tuple - the arguments to start the driver.
        :param: kwargs: dict - the keyword arguments to start the driver.
        :return: None
        """

        retrieve_load_of_vps_stop_event = threading.Event()

        retrieve_load_of_vps_thread = threading.Thread(
            target=self.retrieve_load_of_vps, args=(retrieve_load_of_vps_stop_event,),
            daemon=True
        )
        retrieve_load_of_vps_thread.start()
        logger.info("start: started background thread retrieve_load_of_vps for RipePollingDriver")

        self.BACKGROUND_TASKS['retrieve_load_of_vps'] = {
            'event': retrieve_load_of_vps_stop_event,
            'thread': retrieve_load_of_vps_thread
        }


    def stop(self):
        """
        A method to stop the Ripe Polling Driver.
    
        :return: None
        """
        logger.info("stop: stopping RipePollingDriver: signalling %d background tasks", len(self.BACKGROUND_TASKS))
        for thread_name, thread_info in self.BACKGROUND_TASKS.items():
            thread_info['event'].set()
            thread_info['thread'].join(timeout=30)
            logger.info("Stopped background thread %s", thread_name)

        logger.info("stop: all RipePollingDriver background tasks stopped; shutting down measurement executor")
        self.MEASUREMENT_EXECUTOR.shutdown(wait=True, cancel_futures=True)
     

        logger.info("stop: RipePollingDriver stopped")

    def schedule_ping_measurement(self, **kwargs) -> tuple[str, list[str], Optional[str]]:
        """
        A method to schedule a ping measurement on the Ripe Atlas platform.
       
        :param: kwargs: dict - the keyword arguments to schedule the measurement.
        :return: tuple[str, list[str], Optional[str]] - the target, vps and measurement id.
        """

        target: str = kwargs.get("target")  # type: ignore
        vps: list[str] = kwargs.get("vps")  # type: ignore

        if not target or not vps:
            raise ValueError("Target and vps are required")

        ping = Ping(
            af=ipaddress.ip_address(target).version,
            target=target,
            description="target"
        )

        source: AtlasSource = AtlasSource(
            requested=len(vps),
            type="probes",
            value=", ".join(str(vp) for vp in vps)
        )

        for remaining_attempts in range(RipePollingDriver.SCHEDULING_ATTEMPTS, 0, -1):

            if self.check_concurrent_measurements():
                logger.warning(
                    "%s - schedule_ping_measurement: concurrent measurement overflow when scheduling measurement; sleeping %d minutes before retry",
                    target, RipePollingDriver.HIBERNATION_TIME // 60,
                )

                time.sleep(RipePollingDriver.HIBERNATION_TIME)  # 360 seconds = 6 minutes

            start_time: datetime = datetime.now(pytz.utc) + timedelta(seconds=RipePollingDriver.FUTURE_OFFSET)

            request: AtlasCreateRequest = AtlasCreateRequest(
                start_time=start_time,
                key=RipePollingDriver.RIPE_API_KEY,
                measurements=[
                    ping,
                ],
                sources=[
                    source,
                ],
                is_oneoff=True,
            )

            try:
                self.try_acquire('measurement_scheduling_api', blocking=True, weight=1)
                logger.debug("%s - schedule_ping_measurement: acquired measurement scheduling API rate limits", target)
                is_success, response = request.create()
                logger.debug("%s - schedule_ping_measurement: sent the request to schedule the measurement", target)
            except MalFormattedSource:
                logger.error("%s - schedule_ping_measurement:  malformatted source for the measurement", target)
                is_success = False
                response = {}

            if is_success:
                msm_id = str(response["measurements"][0])
                logger.info("%s - schedule_ping_measurement: scheduled RIPE measurement id %s using %d vps", target, msm_id, len(vps))
                return target, vps, msm_id

            else:
                logger.warning(
                    "%s - schedule_ping_measurement: failed to schedule measurement; attempts left=%d response=%s",
                    target, remaining_attempts, response,
                )

                if isinstance(response, dict):
                    error_code = response.get("error", {}).get("code", 0)  # type: ignore

                    # TODO: previously error code 102 was responsible for the concurrent measurement overflow. Check what it is now.
                    if int(error_code) == 104:
                        logger.error("%s - schedule_ping_measurement: authentication error while scheduling measurement; check API key", target)
                        return target, vps, None
                    else:
                        detail_errors = response.get("error", {}).get("errors", [])
                        if len(detail_errors) == 0:
                            raise Exception( # pylint: disable=broad-exception-raised
                                f"{target} - schedule_ping_measurement: unknown exception was raised when scheduling Ripe Ping Measurement using {vps}"
                            )
                        detail = detail_errors[0].get("detail", None)
                        logger.error("%s - schedule_ping_measurement: Got RIPE error with detail: %s", target, detail)

                elif isinstance(response, tuple):
                    error = response[0]
                    if isinstance(error, urllib3.exceptions.MaxRetryError):
                        logger.error("%s - schedule_ping_measurement: connection timeout, retrying", target)

                    else:
                        logger.error(
                            "%s - schedule_ping_measurement: failed to schedule measurement due to unknown error: %s",
                            target, error,
                        )

                else:
                    logger.error("%s - schedule_ping_measurement: got unknown error type from RIPE Atlas", target)

                time.sleep(RipePollingDriver.SLEEP_TIME_AFTER_ERROR)
        return target, vps, None

    def analyse_ping_results(self, results: dict[str, float], vps: list[str]) -> MeasurementStatus:
        """
        A method to analyse the results of a ping measurement.
     
        :param: results: dict[str, float] - results of the measurement obtained from the RIPE Atlas
        :param: vps: list[str] - the vps that the measurement was performed from.
        :return: MeasurementStatus - the status of the measurement.
        """

        status = MeasurementStatus.FINISHED

        if len(results.keys()) != len(vps):
            status = MeasurementStatus.TIMEOUT
        else:
            for rtt in results.values():
                if rtt == -1.0:
                    status = MeasurementStatus.FAILED

        return status

    def query_results(self, measurement_id: str, target: str, vps: list[str]) -> dict[str, float]:
        """
        A method to query the results of a measurement from the Ripe Atlas platform.
  
        :param: measurement_id: str - the ID of the measurement.
        :param: target: str - the target of the measurement.
        :param: vps: list[str] - the vps that the measurement was performed from.
        :return: dict[str, float] - the results of the measurement.
        """

        result_request: AtlasResultsRequest = AtlasResultsRequest(msm_id=measurement_id)

        results_querying_start_time = time.monotonic()

        obtained_results: list[dict] = []
        raw_results: list[dict] = []
        while len(obtained_results) != len(vps) and time.monotonic() - results_querying_start_time + self.polling_interval < self.measurement_timeout:
            time.sleep(self.polling_interval)

            self.try_acquire('result_polling_api', blocking=True)
            is_success, raw_results = result_request.get()

            if not is_success:
                if '429 Too Many Requests' in raw_results:
                    logger.error(
                        "%s - query_results: rate limit exceeded while fetching results for measurement with msm_id %s",
                        target, measurement_id,
                    )
                else:
                    logger.error("%s - query_results: failed to obtain results from measurement with msm_id=%s because of unknown error: %s", target, measurement_id, raw_results)
            else:
                obtained_results = raw_results.copy()


        results = {}
        for result in obtained_results:
            prb_id: str = str(result['prb_id'])
            min_rtt: float = float(result['min'])

            results[prb_id] = min_rtt

        logger.info("%s - query_results: measurement results for msm_id=%s: %s", target, measurement_id, results)

        return results

    def retrieve_load_of_vps(self, stop_event: threading.Event):
        """
        A daemon thread that will periodically fetch the load of all Ripe Atlas vantage points that are being used right now.
        The fetched values are stored in the latest_load_of_vps parameter of the AbstractDriver class.
   
        :param: stop_event: threading.Event - the event to stop the background task.
        :return: None
        """

        load_checking_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=RipePollingDriver.LOAD_CHECKING_THREADS)
        while not stop_event.is_set():

            active_vp_names: list[str] = list(self.latest_load_of_vps.keys())
            load_per_vp: defaultdict = defaultdict()

            futures = {load_checking_thread_pool.submit(self.fetch_load_of_vp, vp_name): vp_name for vp_name in active_vp_names}

            for future in concurrent.futures.as_completed(futures):
                vp_name = futures[future]

                try:
                    load_of_vp = future.result()
                    load_per_vp[vp_name] = load_of_vp
                except Exception:
                    logger.error("%s - retrieve_load_of_vps: error fetching load of vantage point", vp_name)

            with self.load_lock:
                self.latest_load_of_vps.update(load_per_vp)

            time.sleep(RipePollingDriver.LOAD_CHECKING_PAUSE)

        load_checking_thread_pool.shutdown(wait=True, cancel_futures=True)

    def fetch_load_of_vp(self, vp_name: str) -> int:
        """
        A method to fetch the load of the vantage points from the remote platform.
        This method should store the result in the latest_load_of_vps dictionary.

        :param: vp_name: str - a name of the vantage point which load should be fetched.
        :return: int - the load of the vantage point.
        """

        MAX_RETRIES = 2
        RATE_LIMIT_BASE_WAIT = 15  # seconds


        url = f"https://atlas.ripe.net/api/v2/probes/{vp_name}/measurements"

        for attempt in range(1, MAX_RETRIES + 1):
            wait_time = RATE_LIMIT_BASE_WAIT * attempt  # backoff: 5, 10, 15...

            try:
                self.try_acquire('probe_load_checker_api', blocking=True)
                response = requests.get(url, timeout=10)
            except requests.exceptions.RequestException:
                logger.exception(
                    "%s - fetch_load_of_vp: network error (attempt %d/%d)",
                    vp_name, attempt, MAX_RETRIES,
                )
                time.sleep(wait_time)
                continue

            if response.status_code == 200:
                try:
                    count = int(response.json()['count'])
                    # logger.info("%s - fetch_load_of_vp: probe has %d active measurements", vp_name, count)
                    return count
                except (requests.exceptions.JSONDecodeError, KeyError, TypeError, ValueError):
                    logger.error(
                        "%s - fetch_load_of_vp: failed to parse load: %s",
                        vp_name, response.text,
                    )
                    time.sleep(wait_time)
                    continue

            elif response.status_code == 429:
                logger.error(
                    "%s - fetch_load_of_vp: rate limit hit; retrying in %d seconds (attempt %d/%d)",
                    vp_name, wait_time, attempt, MAX_RETRIES,
                )
                time.sleep(wait_time)
                continue
            else:
                logger.warning(
                    "%s - fetch_load_of_vp: unknown status %s: %s",
                    vp_name, response.status_code, response.text,
                )
                time.sleep(wait_time)
                continue

        logger.error("%s - fetch_load_of_vp: failed to fetch measurements after %d attempts", vp_name, MAX_RETRIES)
        return -1

    # DRIVER SPECIFIC METHODS
    def check_concurrent_measurements(self) -> bool:
        """
        A method to check number of concurrent measurements on the Ripe Atlas.

        :return: bool - True if there are less than 100 concurrent measurements. False otherwise.
        """

        url_path: str = "https://atlas.ripe.net/api/v2/measurements?"

        config: dict = {
            "key": self.RIPE_API_KEY,
            "is_oneoff": "true",
            "is_public": "true",
            "status": 2,
            "mine": 0,
            "description": "target",
        }

        for key, value in config.items():
            url_path += f"{key}={value}&"

        attempts = 3

        response = None
        while attempts > 0:
            response = None

            attempts -= 1

            try:
                self.try_acquire('concurrent_measurement_checker_api', blocking=True)

                response = requests.request("GET", url_path, timeout=5)
                if response.status_code == 200:
                    break
                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", 5)
                    logger.error("check_concurrent_measurements: RIPE rate limit exceeded; retrying after %s seconds", retry_after)
                    time.sleep(int(retry_after))
                else:
                    logger.error(
                        "check_concurrent_measurements: failed to check concurrent measurements; status=%s response=%s",
                        response.status_code, response.text,
                    )

            except requests.exceptions.RequestException as e:
                backoff = 2 ** (3 - attempts)
                logger.error(
                    "check_concurrent_measurements: request failed with %s: %s; retrying in %d seconds (attempts left=%d)",
                    type(e).__name__, e, backoff, attempts,
                )
                time.sleep(backoff)
            except Exception:
                logger.exception("check_concurrent_measurements: unexpected error while checking concurrent measurements")
                break

        if response is None or response.status_code != 200:
            logger.error("check_concurrent_measurements: failed to check concurrent measurements after multiple attempts")
            raise Exception(
                "check_concurrent_measurements: failed to check concurrent measurements after multiple attempts."
            )

        data: dict = json.loads(response.text)
        count: int = data["count"]

        logger.info("check_concurrent_measurements: RIPE concurrent measurements count: %d", count)
        return count >= self.RIPE_MAX_CONCURRENT_MEASUREMENTS

    @staticmethod
    def get_last_updated_entry(ftp: FTP, path: str) -> str:
        """
        List just the filenames.
      
        :param: path: str - the path to the directory to list the files from.
        :return: str - the last updated entry in the directory.
        """
        entries = list(ftp.mlsd(path, facts=["modify"]))

        IGNORED_FILES = {"README", "meta-latest", ".", ".."}
        entries = [e for e in entries if e[0] not in IGNORED_FILES]
        last_name, _ = max(entries, key=lambda x: x[1].get("modify", ""))

        return last_name

    @classmethod
    def get_connected_ripe_vps(cls) -> dict[str, dict]:
        """
        A method to get the connected RIPE Atlas VPS.
  
        :return: dict[str, dict] - the dictionary of connected RIPE Atlas VPS.
        """
        ripe_host = "ftp.ripe.net"
        ripe_archive_path = "/ripe/atlas/probes/archive/"
        ftp = FTP(ripe_host)
        ftp.login(user="anonymous", passwd="")

        try:
            path = ripe_archive_path

            year = RipePollingDriver.get_last_updated_entry(ftp, path)
            path += year + "/"

            month = RipePollingDriver.get_last_updated_entry(ftp, path)
            path += month + "/"

            anchor_archive_file = RipePollingDriver.get_last_updated_entry(ftp, path)
            path += anchor_archive_file

            buffer = BytesIO()
            ftp.retrbinary(f"RETR {path}", buffer.write)
            buffer.seek(0)
            data = json.loads(bz2.decompress(buffer.read()))

            downloaded_vps = data['objects']

            vps: dict[str, dict] = {}

            for vp in downloaded_vps:
                vp_name = str(vp['id'])
                address_v4 = vp['address_v4']
                address_v6 = vp['address_v6']

                is_anchor = vp['is_anchor']
                is_public = vp['is_public']
                status = vp['status_name']
                tags = vp['tags']

                country_code = vp['country_code']

                latitude = vp['latitude']
                longitude = vp['longitude']


                is_stable = True if 'system-ipv4-stable-30d' in tags or 'system-ipv6-stable-30d' in tags else False

                if status == "Connected":
                    vps[vp_name] = {
                        'address_v4': address_v4,
                        'address_v6': address_v6,
                        'is_anchor': is_anchor,
                        'is_public': is_public,
                        'status': status,
                        'is_stable': is_stable,
                        'tags': tags,
                        'country_code': country_code,
                        'latitude': latitude,
                        'longitude': longitude,
                    }

            return vps.copy()

        except Exception:
            logger.exception("get_connected_ripe_vps: exception occurred while getting connected RIPE Atlas VPs")
            return {}
        finally:
            ftp.close()


    def try_acquire(self, limiter_name: str, blocking: bool = True, weight: int = 1):
        """
        A method to acquire the Leaky Bucket rate limiter for the Ripe Atlas API.
 
        :param: limiter_name: str - the name of the limiter to acquire.
        :param: blocking: bool - whether to block the thread if the rate limiter is not available.
        :param: weight: int - the weight of the request.
        :return: None
        """

        success=False
        if limiter_name in ['probe_load_checker_api', 'probe_status_checker_api',]:
            for attempt in range(1,self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS + 1):
                try:
                    self.GENERAL_API_LIMITER.try_acquire(limiter_name, blocking=blocking, weight=weight)
                    success = True
                    break
                except IndexError:
                    logger.error(
                        "%s - try_acquire: rate limit exceeded at %d/%d; retrying in 1s",
                        limiter_name, attempt, self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS,
                    )
                    time.sleep(1)

        elif limiter_name in ['measurement_scheduling_api', 'result_polling_api', 'concurrent_measurement_checker_api']:
            for attempt in range(1,self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS + 1):
                try:
                    self.MEASUREMENT_API_LIMITER.try_acquire(limiter_name, blocking=blocking, weight=weight)
                    success = True
                    break
                except IndexError:
                    logger.error(
                        "%s - try_acquire: rate limit exceeded at %d/%d; retrying in 1s",
                        limiter_name, attempt, self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS,
                    )
                    time.sleep(1)

        else:
            raise ValueError(f"Invalid limiter name: {limiter_name}")

        if not success:
            logger.error(
                "%s - try_acquire: Failed to acquire rate limiter for %s after %d attempts",
                limiter_name, limiter_name, self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS,
            )
            raise Exception(f"{limiter_name} - try_acquire: failed to acquire rate limiter after {self.RIPE_API_RATE_LIMITER_ACQUISITION_ATTEMPTS} attempts.")

        with self.lock:
            self.metadata['rps'][limiter_name] = self.get_rps(limiter_name)

            self.API_REQUEST_COUNT[limiter_name].append(time.monotonic() - self.START_TIME)

    def get_rps(self, limiter_name: str) -> float:
        """
        A method to get the RPS of the Leaky Bucket rate limiter for the Ripe Atlas API.
 
        :param: limiter_name: str - the name of the limiter to get the RPS of.
        :return: float - the RPS of the Leaky Bucket rate limiter.
        """
        elapsed_time = time.monotonic() - self.START_TIME
        if elapsed_time == 0:
            return 0.0
    
        request_count = len(self.API_REQUEST_COUNT[limiter_name])
        return request_count / elapsed_time if elapsed_time > 0 else 0.0

    def  get_request_count(self, limiter_name: str) -> int:
        """
        A method to get the request count of the Leaky Bucket rate limiter for the Ripe Atlas API.
    
        :param: limiter_name: str - the name of the limiter to get the request count of.
        :return: int - the request count of the Leaky Bucket rate limiter.
        """
        with self.lock:
            return len(self.API_REQUEST_COUNT[limiter_name])
