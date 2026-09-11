import logging
from pathlib import Path
import threading
import concurrent.futures

import time
from typing import Callable, Optional
from collections import defaultdict
from abc import ABC, abstractmethod

from bigfoot.measurements import MeasurementStatus
from bigfoot.timer import timeit

logger = logging.getLogger(__name__)


class AbstractDriver(ABC):

    metadata: dict = {}

    def __init__(self, measurement_timeout: int, polling_interval: int, max_workers: int):
        self.MEASUREMENT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.BACKGROUND_TASKS: defaultdict[str, dict] = defaultdict(dict)

        self.measurement_timeout = measurement_timeout
        self.polling_interval = polling_interval

        self.results_lock = threading.Lock()
        self.results: dict[str, dict[str, float]] = defaultdict(dict)

        self.load_lock = threading.Lock()
        self.latest_load_of_vps: defaultdict = defaultdict()

        self.vps: dict[str, dict] = {}
        self.vps_lock = threading.Lock()


        logger.info("__init__: initialized AbstractDriver")

    def get_vps(self) -> list[str]:
        """
        A method to get the list of vantage points from the remote platform.
  
        :return: list[str] - the list of vantage points.
        """
        with self.vps_lock:
            return list(self.vps.keys())

    def get_vps_details(self) -> dict:
        """
        A method to get the details of the vantage points from the remote platform.
    
        :return: dict - the details of the vantage points.
        """
        with self.vps_lock:
            return self.vps.copy()

    def record_measurement_result(self, measurement_id: str, vp_name: str, rtt: float ) -> bool:
        """
        A method to record a measurement result in the internal cache of the driver.

        :param: measurement_id: str - the ID of the measurement.
        :param: vp_name: str - the vantage point that the measurement was performed from.
        :param: rtt: float - the round trip time of the measurement.
        :return: bool - True if the measurement result was recorded successfully, False otherwise.
        """

        try:
            with self.results_lock:
                self.results[measurement_id][vp_name] = rtt
                logger.debug(
                    "%s - record_measurement_result: recorded measurement result: vp=%s; rtt=%.3f",
                    measurement_id, vp_name, rtt,
                )
                return True
        except Exception:
            logger.exception("%s - record_measurement_result: failed to record measurement result", measurement_id)

        return False

    def record_vp_load(self, vp_name: str, load: int) -> bool:
        """
        A method to record the load of a vantage point.
      
        :param: vp_name: str - the name of the vantage point.
        :param: load: int - the load of the vantage point.
        :return: bool - True if the load was recorded successfully, False otherwise.
        """
        try:
            with self.load_lock:
                self.latest_load_of_vps[vp_name] = load
                logger.debug("%s - record_vp_load: recorded load=%d", vp_name, load)
                return True
        except Exception:
            logger.exception("%s - record_vp_load: failed to record load", vp_name)
        return False

    def get_results(self, measurement_id: str) -> dict[str, float]:
        """
        A method used by the core to get the results of a measurement.

        :param: measurement_id: str - the ID of the measurement.
        :return: dict[str, float] - the results of the measurement.
        """
        try:
            with self.results_lock:
                if measurement_id in self.results:
                    return self.results[measurement_id].copy()
                else:
                    return {}
        except Exception:
            logger.exception("%s - get_results: failed to get results", measurement_id)
            return {}

    def get_load_of_vp(self, vp_name: str) -> int:
        """
        A method used by the core to get the load of the vantage point.
 
        :param: vp_name: str - a name of the vantage point to get its load.
        :return: int - last fetched load of the vantage point.
        """
        with self.load_lock:
            if vp_name in self.latest_load_of_vps:
                return self.latest_load_of_vps[vp_name]
        try:
            load = self.fetch_load_of_vp(vp_name)   
        except Exception:
            logger.exception("%s - get_load_of_vp: failed to fetch load", vp_name)
            load = -1
        with self.load_lock:
            self.latest_load_of_vps[vp_name] = load
            return load

    @abstractmethod
    def fetch_load_of_vp(self, vp_name: str) -> int:
        """
        A method to fetch the load of the vantage point from the remote platform.
 
        :param: vp_name: str - a name of the vantage point to fetch its load.
        :return: int - the load of the vantage point.
        """

    @abstractmethod
    def retrieve_load_of_vps(self, stop_event: threading.Event):
        """
        A method to fetch the load of the vantage points from the remote platform.
        This method should store the result in the latest_load_of_vps dictionary.
  
        :param: stop_event: threading.Event - the event to stop the background task.
        :return: None
        """

    def conduct_measurement(self, completed_callback: Callable[[dict[str, float], MeasurementStatus, dict], None], measurement_type: str = "", target: str = "", vps: list[str] = []) -> None:
        """
        A method to conduct a measurement and call the completed callback when the measurement is completed. Measurement type is used to determine the type of measurement to conduct.

        :param: measurement_type: str - the type of measurement to schedule.
        :param: completed_callback: Callable[[dict[str, float], MeasurementStatus], None] - the callback to be called when the measurement is completed.
        :param: target: str - the target of the measurement.
        :param: vps: list[str] - the vps that the measurement was performed from.
        :return: None
        """

        def _on_done(future: concurrent.futures.Future):
            try:
                results, status, metadata = future.result()
            except Exception:
                logger.exception("%s - conduct_measurement: failed to get results of measurement (type=%s)", target, measurement_type)
                results = {}
                status = MeasurementStatus.FAILED
                metadata = {}

            completed_callback(results, status, metadata)

        start_time = time.monotonic()
        try:
            logger.info(
                "%s - conduct_measurement: dispatching %s measurement on %s with vps=%s",
                target, measurement_type, type(self).__name__, vps,
            )
            match measurement_type:
                case "ping":
                    self.MEASUREMENT_EXECUTOR.submit( # type: ignore # pylint: disable=unsubscriptable-object
                        self.conduct_ping_measurement, target=target, vps=vps, start_time=start_time
                    ).add_done_callback(_on_done)
                case _:
                    raise ValueError(f"{target} - invalid measurement type: {measurement_type}")
        except Exception:
            logger.error("%s - conduct_measurement: failed to conduct measurement (type=%s)", target, measurement_type)
            completed_callback({}, MeasurementStatus.FAILED, {})

    def conduct_ping_measurement(self, **kwargs) -> tuple[dict[str, float], MeasurementStatus, dict]:
        """
        A method to conduct a ping measurement on the platform using the driver.

        :param: kwargs: dict - the keyword arguments to schedule the measurement.
        :return: tuple[dict[str, float], MeasurementStatus, dict] - the results and status of the measurement and the metadata of the measurement.
        """

        runtimes : dict = {}
      
        with timeit(storage=runtimes, name="schedule_ping_measurement"):
            target, vps, measurement_id = self.schedule_ping_measurement(**kwargs)
            logger.debug("%s - %s - conduct_ping_measurement: scheduled ping measurement", target, measurement_id)

        load_of_vps: dict[str, dict[str, float|int]] = {vp: {'load': self.get_load_of_vp(vp), 'checked_at': time.monotonic()} for vp in vps}
        if measurement_id is None:
            logger.error("%s - %s - conduct_ping_measurement: failed to schedule ping measurement", target, measurement_id)
            metadata: dict = {
                'measurement_id': None,
                'runtimes': runtimes,
                'load_of_vps': load_of_vps,
            }
            return {}, MeasurementStatus.FAILED, metadata

        with timeit(storage=runtimes, name="query_ping_results"):
            results = self.query_results(measurement_id=measurement_id, target=target, vps=vps)
            logger.debug("%s - %s - conduct_ping_measurement: queried ping results", target, measurement_id)

        with timeit(storage=runtimes, name="analyse_ping_results"):
            status = self.analyse_ping_results(results=results, vps=vps)
            logger.debug("%s - %s - conduct_ping_measurement: analyzed ping results", target, measurement_id)

        metadata: dict = {
            'measurement_id': measurement_id,
            'runtimes': runtimes,
            'load_of_vps': load_of_vps,
        }
        
        logger.info("%s - %s - conduct_ping_measurement: conducted ping measurement", target, measurement_id)
        return results, status, metadata

    @abstractmethod
    def schedule_ping_measurement(self, **kwargs) -> tuple[str, list[str], Optional[str]]:
        """
        A method to schedule a ping measurement on the platform using the driver.

        :param: kwargs: dict - the keyword arguments to schedule the measurement.
        :return: tuple[str, list[str], Optional[str]] - the target, vps and measurement id.
        """

    @abstractmethod
    def analyse_ping_results(self, results: dict[str, float], vps: list[str]) -> MeasurementStatus:
        """
        A method to analyse the results of a ping measurement.

        :param: results: dict[str, float] - the results of the measurement.
        :param: vps: list[str] - the vps that the measurement was performed from.
        :return: MeasurementStatus - the status of the measurement.
        """

    @abstractmethod
    def query_results(self, measurement_id: str, target: str, vps: list[str]) -> dict[str, float]:
        """
        A method to query the results of a measurement from the platform using the driver.
        When implemented this method should query the results of the given measurement id from the platform and return the results.

        :param: measurement_id: str - the ID of the measurement.
        :param: target: str - the target of the measurement.
        :param: vps: list[str] - the vps that the measurement was performed from.
        :return: dict[str, float] - the results of the measurement.
        """

    @abstractmethod
    def start(self, *args, **kwargs):
        """
        A method to start the driver.
    
        :param: args: tuple - the arguments to start the driver.
        :param: kwargs: dict - the keyword arguments to start the driver.
        :return: None
        """

    @abstractmethod
    def stop(self):
        """
        A method to stop the driver.
        """