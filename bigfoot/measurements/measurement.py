from collections import defaultdict
from dataclasses import dataclass, field
import logging
import time
from typing import Optional
import uuid

from bigfoot.config import Config
from bigfoot.vps import VantagePoint
from bigfoot.timer import timeit
from .measurement_scheduler import MeasurementScheduler
from .measurement_status import MeasurementStatus

logger = logging.getLogger(__name__)


class Measurement:

    config: Optional[Config] = None
    VantagePointMapping: Optional[dict[str, VantagePoint]] = None

    @classmethod
    def set_vantage_point_mapping(cls, vantage_point_mapping: dict[str, VantagePoint]):
        """
        A method to set the vantage point mapping.

        :param: vantage_point_mapping: dict[str, VantagePoint] - the vantage point mapping.
        :return: None
        """
        cls.VantagePointMapping = vantage_point_mapping.copy()
        logger.info("VantagePointMapping is set with %d VPs", len(vantage_point_mapping))

    @classmethod
    def set_config(cls, config: Config):
        """
        A method to set the configuration.
        
        :param: config: Config - the configuration.
        :return: None
        """
        cls.config = config
        logger.info("config is set")

    def __init__(self, target: str, vps: list[str], measurement_type: str, unbounded_scheduler: bool = False):
        if Measurement.config is None:
            raise ValueError("config is not set")

        if Measurement.VantagePointMapping is None:
            raise ValueError("VantagePointMapping is not set")

        self.target = target
        self.vp_names = list(vps)
        self.vps = self.lookup_vantage_points(vps)
        self.measurement_type = measurement_type
        self.unbounded_scheduler = unbounded_scheduler

        self.results: dict[str, float] = {}
        self.status: MeasurementStatus = MeasurementStatus.CREATED
        self.runtime: float = 0.0

        self.max_measurement_attempt_count: int =  Measurement.config.MAX_MEASUREMENT_ATTEMPT_COUNT
        self.max_attempt_count: int = Measurement.config.RATE_LIMITER_MAX_ATTEMPT_COUNT

        self.failed_vps: list[str] = []
        self.metadata: dict = defaultdict(dict)

        logger.info("%s - __init__: Measurement created with %d VPs", self.target, len(self.vps))

    def lookup_vantage_points(self, vp_names: list[str]) -> list[VantagePoint]:
        """
        A method to lookup the instances of VantagePoint class by the names of the vantage points.

        :param: vp_names: list[str] - the names of the vantage points.
        :return: list[VantagePoint] - the instances of the VantagePoint class.
        """
        return [Measurement.VantagePointMapping[name] for name in vp_names]  # type: ignore # pylint: disable=unsubscriptable-object

    def analyse_results(self) -> tuple[list[VantagePoint], MeasurementStatus]:
        """
        A method to analyse the results of the measurement and identify names of the vantage points that failed to conduct the measurement.
        
        :return: tuple[set[VantagePoint], MeasurementStatus] - the instances of the VantagePoint class that didnt conduct the measurement and the status of the measurement.
        """

        status = MeasurementStatus.FINISHED
        failed_vps: set[str] = set()

        for vp, rtt in self.results.items():
            if rtt == -1.0:
                failed_vps.add(vp)

        if len(failed_vps) > 0:
            status = MeasurementStatus.FAILED

        timeout_vps =  set(self.vp_names).difference(set(self.results.keys()))

        if len(timeout_vps) > 0:
            status = MeasurementStatus.TIMEOUT

        names_of_vps_to_attempt = failed_vps.union(timeout_vps)
        vps_to_attempt: list[VantagePoint] = self.lookup_vantage_points(list(names_of_vps_to_attempt))

        logger.debug("%s - analyse_results: Analysed the results from vps_to_attempt=%s and got status=%s", self.target, self.vp_names, status)
        return  vps_to_attempt, status

    def update_results(self, new_results: dict[str, float]) -> None:
        """
        A method to update the results of the measurements.
        
        :param: new_results: dict[str, float] - the new results.
        :return: None
        """
        recorded_results = self.results.copy()
        for vp_name, rtt in new_results.items():
            recorded_rtt = recorded_results.get(vp_name)

            if recorded_rtt is None and rtt > 0.0:
                # new result is valid and that vantage point did not return RTT before
                recorded_results[vp_name] = rtt

            elif rtt > 0.0 and (recorded_rtt <= 0.0 or rtt < recorded_rtt):
                # new result is valid and either replaces an invalid existing one, or is smaller than the recorded RTT
                recorded_results[vp_name] = rtt

        self.results = recorded_results.copy()

        logger.debug("%s - update_results: Updated the results recorded_results=%s", self.target, recorded_results)

    def conduct_measurement(self) -> None:
        """
        A method to conduct the measurement.
        """

        logger.info(
            "%s - conduct_measurement: Starting the measurement: vps=%s type=%s",
            self.target, self.vp_names, self.measurement_type,
        )
        measurement_start_time: float = time.monotonic()

        vps_to_attempt = self.vps.copy()

        # create an instance of the rate limiter that will be used to acquire vps and schedule the measurements
        scheduler = MeasurementScheduler(target=self.target, max_attempt_count=self.max_attempt_count, measurement_type=self.measurement_type, unbounded_scheduler=self.unbounded_scheduler)

        for measurement_attempt in range(self.max_measurement_attempt_count):

            measurement_attempt_start_time = time.monotonic()
            logger.debug(
                "%s - conduct_measurement: Measurement attempt %d/%d with %s pending VPs",
                self.target, measurement_attempt + 1, self.max_measurement_attempt_count, ', '.join([vp.name for vp in vps_to_attempt]),
            )

            with timeit(storage=self.metadata[f"measurement_attempt_{measurement_attempt}"], name="acquire_vps_and_schedule_measurements"):
                acquisition_status = scheduler.acquire_vps_and_schedule_measurements(vps_to_attempt)

            with timeit(storage=self.metadata[f"measurement_attempt_{measurement_attempt}"], name="gather_results"):
                results = scheduler.gather_results()

            self.update_results(results)
            
            with timeit(storage=self.metadata[f"measurement_attempt_{measurement_attempt}"], name="analyse_results"):
                vps_to_attempt, status = self.analyse_results()
                # logger.debug("%s - conduct_measurement: Analysed the results and got status: %s", self.target, status)

            self.status = status if acquisition_status == MeasurementStatus.ACQUIRED else acquisition_status

            self.metadata[f"measurement_attempt_{measurement_attempt}"]['status'] = self.status.value
            self.metadata[f"measurement_attempt_{measurement_attempt}"]['results'] = results
            self.metadata[f"measurement_attempt_{measurement_attempt}"]['runtime'] = time.monotonic() - measurement_attempt_start_time
            self.metadata[f"measurement_attempt_{measurement_attempt}"]['failed_vps'] = [vp.name for vp in vps_to_attempt]
            self.metadata[f"measurement_attempt_{measurement_attempt}"]['scheduler_metadata']= scheduler.metadata[-1].copy()

            if measurement_attempt == self.max_measurement_attempt_count - 1 and self.status == MeasurementStatus.UNACQUIRED:
                break

            if self.status == MeasurementStatus.FINISHED:
                break
            
        self.failed_vps = [vp.name for vp in vps_to_attempt]
        self.runtime = time.monotonic() - measurement_start_time
        logger.info(
            "%s - Measurement finished: status=%s runtime=%.2fs results=%d/%d",
            self.target,
            self.status.value, self.runtime, len(self.results), len(self.vp_names),
        )

    def to_dict(self) -> dict:
        """
        A method to convert the measurement to a dictionary.
        
        :return: dict - the measurement as a dictionary.
        """
        return {
            "target": self.target,
            "vps": self.vp_names.copy(),
            "measurement_type": self.measurement_type,
            "results": self.results.copy(),
            "status": self.status.value,
            "runtime": self.runtime,
            "metadata": self.metadata.copy() if self.config.INCLUDE_METADATA else None,
        }
