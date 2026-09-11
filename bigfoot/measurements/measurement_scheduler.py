from collections import defaultdict
import logging
import time
from typing import Optional
import uuid

from .sub_measurement import SubMeasurement
from .measurement_status import MeasurementStatus

from bigfoot.vps import VantagePoint
from bigfoot.timer import timeit

logger = logging.getLogger(__name__)


class MeasurementScheduler:

    MAXIMUM_WAIT_TIME: Optional[float] = None

    @classmethod
    def set_maximum_wait_time(cls, maximum_wait_time: float):
        """
        A method to set the maximum wait time that the measurement scheduler shold wait when gathering results.
        If the maximum wait time is set to None the measurement scheduler will wait indefinitely.
      
        :param: maximum_wait_time: float - the maximum wait time in seconds.
        :return: None
        """
        if maximum_wait_time != -1:
            cls.MAXIMUM_WAIT_TIME = maximum_wait_time

        logger.info(f"set_maximum_wait_time: Set maximum wait time to {cls.MAXIMUM_WAIT_TIME}")

    # TODO: how to handle max_attempt_count better
    def __init__(self, target: str, max_attempt_count: int, measurement_type: str, unbounded_scheduler: bool = False):
        self.target = target

        self.max_attempt_count = max_attempt_count
        self.measurement_type = measurement_type
        self.unbounded_scheduler = unbounded_scheduler

        self.RL_ID = uuid.uuid4()
        self.start_time = time.monotonic()
        self.last_scheduled_time = time.monotonic()

        self.scheduled_sub_measurements: list[SubMeasurement] = []
        self.metadata: list = []

        logger.info("%s - %s - __init__: MeasurementScheduler initialized", self.target, self.RL_ID)

    def get_timedelta(self) -> float:
        """
        A method to get the timedelta since the start of the rate limiter.
      
        :return: float - the timedelta since the start of the rate limiter.
        """
        return time.monotonic() - self.start_time

    def acquire_vps_and_schedule_measurements(self, vps: list[VantagePoint]) -> MeasurementStatus:
        """
        A method to acquire rate-limited vps for measurement.
     
        :param: vps: list[VantagePoint] - list of vantage points to attempt to acquire.
        :return: MeasurementStatus - the status of the measurement.
        """

        logger.info("%s - %s - acquire_vps_and_schedule_measurements: Acquiring %s VPs", self.target, self.RL_ID, ', '.join([vp.name for vp in vps]))
        self.scheduled_sub_measurements.clear()
        
        status = MeasurementStatus.ACQUIRING

        vps_to_attempt: list[VantagePoint] = vps.copy()

        # if max attempt count is less than or equal to the number of vps
        max_attempts = self.max_attempt_count
        if max_attempts <= len(vps_to_attempt):
            max_attempts = len(vps_to_attempt) * 2

        self.metadata.append(defaultdict(dict))
        self.metadata[-1]['rl_id'] = str(self.RL_ID)
        self.metadata[-1]['start_time'] = self.start_time
        
        for acquisition_attempt in range(max_attempts):
            try:
                with timeit(storage=self.metadata[-1], name=f"acquisition_attempt_{acquisition_attempt}"):
                    logger.debug(
                        "%s - %s - acquire_vps_and_schedule_measurements: acquisition attempt %d/%d (pending=%d)",
                        self.target, self.RL_ID, acquisition_attempt, max_attempts, len(vps_to_attempt),
                    )

                    acquired_vps: list[VantagePoint] = []
                    max_wait_time: float = 0

                    # try to acquire all vps
                    for vp in vps_to_attempt:
                        sleep_time: float = vp.acquire(self.RL_ID)

                        # if vantage point is acquired
                        # add to the list of acquired_vps and continue the loop
                        if sleep_time == 0.0:
                            acquired_vps.append(vp)
                            self.metadata[-1]['acquisition_timestamps'][vp.name] = time.monotonic() - self.start_time

                        # otherwise update the max_wait_time
                        # by checking if new sleep_time is greater than current max_wait_time
                        else:
                            max_wait_time = max(max_wait_time, sleep_time)

                    # check how many vps were acquired
                    if len(acquired_vps) > 0:
                        # schedule all acquired vps
                        self.schedule_sub_measurement(acquired_vps)

                        # remove acquired vps that are scheduled from vps_to_attempt
                        for vp in acquired_vps:
                            vps_to_attempt.remove(vp)

                        # clear list of acquired_vps
                        acquired_vps.clear()

                    # if there are no more vps to attempt, break the loop
                    if len(vps_to_attempt) == 0:
                        break

                    # wait for max_wait_time before next attempt
                    logger.info(
                        "%s - %s - acquire_vps_and_schedule_measurements: sleeping %.2fs before next acquisition attempt",
                        self.target, self.RL_ID, max_wait_time,
                    )

                with timeit(storage=self.metadata[-1], name=f"sleep_before_next_acquisition_attempt_{acquisition_attempt}"):
                    time.sleep(max_wait_time)
            except Exception as e:
                logger.exception(   
                    "%s - %s - acquire_vps_and_schedule_measurements: error acquiring vps and scheduling measurements.",
                    self.target, self.RL_ID,
                )
        else:
            status = MeasurementStatus.UNACQUIRED
            logger.warning(
                "%s - %s - acquire_vps_and_schedule_measurements: exhausted %d acquisition attempts; %d VPs unacquired",
                self.target, self.RL_ID, max_attempts, len(vps_to_attempt),
            )
            return status
      
        status = MeasurementStatus.ACQUIRED
        return status

    def schedule_sub_measurement(self, vps: list[VantagePoint]) -> None:
        """
        A method to schedule a sub measurement with acquired vantage points and add it to the list of scheduled measurements.
     
        :param: vps: list[VantagePoint] - list of acquired vantage points.
        :return: None
        """

        measurement = SubMeasurement(target=self.target, vps=vps, measurement_type=self.measurement_type)
        measurement.start_measurement()
        self.scheduled_sub_measurements.append(measurement)
        self.last_scheduled_time = time.monotonic()
        logger.info(
            "%s - %s - schedule_sub_measurement: scheduled SubMeasurement with vps=%s; scheduler now has %d sub-measurements",
            self.target, self.RL_ID, ', '.join([vp.name for vp in vps]), len(self.scheduled_sub_measurements),
        )

    def gather_results(self) -> dict[str, float]:
        """
        A method to gather the results of the scheduled measurements.
   
        :return: dict[str, float] - the results of the scheduled measurements.
        """
        logger.info(
            "%s - %s - gather_results: gathering results from %d sub-measurements", 
            self.target, self.RL_ID, len(self.scheduled_sub_measurements),
        )
        
        results: dict[str, float] = {}
        with timeit(storage=self.metadata[-1], name="gather_results"):
            for index, measurement in enumerate(self.scheduled_sub_measurements):
                time_passed = time.monotonic() - measurement.measurement_start_time
                if self.unbounded_scheduler:
                    measurement.completed_event.wait(timeout=None)
                else:
                    measurement.completed_event.wait(timeout=self.MAXIMUM_WAIT_TIME + 15 - time_passed if self.MAXIMUM_WAIT_TIME is not None else None)
                    
                results.update(measurement.results)
                self.metadata[-1][f"sub_measurement_{index}"] = measurement.metadata.copy()

                logger.info(
                    "%s - %s - gather_results: gathered results from sub-measurement %d",
                    self.target, self.RL_ID, index,
                )
        
        logger.info(
            "%s - %s - gather_results: gathered %d results from %d sub-measurements",
            self.target, self.RL_ID, len(results), len(self.scheduled_sub_measurements),
        )
        return results