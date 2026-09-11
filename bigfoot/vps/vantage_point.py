import logging
import math
import random
import time
from types import SimpleNamespace
import uuid
import threading

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from bigfoot.rate_limiter.rate_limiter_queue import RateLimiterQueue

logger = logging.getLogger(__name__)

HIGH_LOAD_ARK_NODES = set(
    [
        "fra-de", 
        "jfk2-us", 
        "lgw2-uk", 
        "hkg4-cn", 
        "lax4-us", 
        "ory8-fr", 
        "waw-pl"
    ]
)

@dataclass
class VantagePoint:
    """
    A class to represent a vantage point.
    """

    name: str
    platform: str
    measurement_rate: int # number of measurements on vantage point per second
    get_load_of_vp: Callable # a method of driver that should be used to fetch the current load of the vantage point. Will be different based on the platform.
    max_load_increase: int = field(default=-1)

    metadata: SimpleNamespace = field(default_factory=SimpleNamespace)

    remaining_capacity: int = field(init=False)
    load_hint_threshold: int = field(init=False)
    current_load: int = field(init=False)
    start_time: float = field(init=False)
    last_acquisition_timestamp: int = field(init=False)
    initial_load: Optional[int] = field(init=False, default=None)
    acquisition_lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    pending_measurements_queue: RateLimiterQueue = field(init=False, default_factory=RateLimiterQueue)

    TIME_SLACK: float = 1.0

    def __post_init__(self,):
        """
        A method to post initialize the vantage point.
        """
        if self.measurement_rate < 0:
            raise ValueError("Request rate can not be less than zero")

        if isinstance(self.metadata, dict):
            self.metadata= SimpleNamespace(**self.metadata)
        elif not isinstance(self.metadata, SimpleNamespace):
            raise TypeError(f"metadata must be a dict, got {type(self.metadata).__name__}")

        if self.platform == 'ark' and self.name in HIGH_LOAD_ARK_NODES:
            self.measurement_rate = 1

        self.remaining_capacity = self.measurement_rate
        # self.initial_load = self.get_load_of_vp(self.name)
        self.load_hint_threshold = math.ceil(self.max_load_increase*0.25) if self.max_load_increase > 0 else 0
        self.current_load = self.max_load_increase
        self.start_time = time.monotonic()
        self.last_acquisition_timestamp = math.floor(self.time_passed_since_start())

        # logger.debug(
            # "VantagePoint constructed: name=%s platform=%s measurement_rate=%d max_load_increase=%d",
            # self.name, self.platform, self.measurement_rate, self.max_load_increase,
        # )

    def time_passed_since_start(self) -> float:
        """
        A method to get the time passed since the start of the vantage point.
       
        :return: float - the time passed since the start of the vantage point.
        """
        return time.monotonic() - self.start_time

    def acquire(self, measurement_rl_id: uuid.UUID) -> float:
        """
        A method to acquire the vantage point.
      
        :param: measurement_rl_id: uuid.UUID - the id that is used by rate limiter instance to schedule the measurement.
        :return: float - the sleep time in seconds.
        """

        with self.acquisition_lock:

            now = self.time_passed_since_start()

            expired_measurements = []
            for pending_measurement, timestamp in self.pending_measurements_queue:
                if timestamp + self.TIME_SLACK < now:
                    expired_measurements.append(pending_measurement)
                else:
                    break

            for expired_measurement in expired_measurements:
                self.pending_measurements_queue.discard(expired_measurement)
            
            logger.debug("%s - %s - acquire: Cleared expired measurements", measurement_rl_id, self.name)

            if self.max_load_increase > 0:
                if self.current_load:
                    self.current_load -= 1

                else:
                    load_of_vp = self.get_load_of_vp(self.name)
                    if self.initial_load is None:
                        self.initial_load = load_of_vp

                    if load_of_vp == -1 or abs(load_of_vp - self.initial_load) > self.max_load_increase:
                        self.pending_measurements_queue.discard(measurement_rl_id)

                        sleep_time = max((len(self.pending_measurements_queue) + 1) / self.measurement_rate, 60 + random.uniform(0, 1))
                        wake_up_time = now + sleep_time
                        self.pending_measurements_queue.push(measurement_rl_id, wake_up_time)
                        logger.warning(
                            "%s - %s - acquire: measurement is added to pending acquisition queue in failure scenario 5; sleep time is %d seconds; load is outside the range [initial=%d, max_load=%d]",
                            measurement_rl_id, self.name, sleep_time, self.initial_load, self.initial_load + self.max_load_increase,
                        )
                        return sleep_time
                    else:
                        self.current_load = (self.initial_load + self.max_load_increase - load_of_vp)
                        self.current_load -= 1
                        logger.debug(
                            "%s - %s - acquire: load is below the max load - %d/%d, available load is %d",
                            measurement_rl_id, self.name, load_of_vp, self.initial_load + self.max_load_increase, self.current_load,
                        )

            if now - self.last_acquisition_timestamp >= 1.0:
                self.remaining_capacity = self.measurement_rate
                self.last_acquisition_timestamp = math.floor(now)
                logger.debug(
                    "%s - %s - acquire: new acquisition window is opened at %d second; remaining capacity is %d",
                    measurement_rl_id, self.name, self.last_acquisition_timestamp, self.remaining_capacity,
                )

            if self.remaining_capacity > 0 and len(self.pending_measurements_queue) == 0:
                self.remaining_capacity -= 1
                logger.info(
                    "%s - %s - acquire: successful acquisition in successful scenario 1; remaining capacity is %d",
                    measurement_rl_id, self.name, self.remaining_capacity,
                )
                return 0.0

            elif self.remaining_capacity == 0:
                self.pending_measurements_queue.discard(measurement_rl_id)

                sleep_time = (len(self.pending_measurements_queue) + 1) / self.measurement_rate
                wake_up_time = now + sleep_time
                self.pending_measurements_queue.push(measurement_rl_id, wake_up_time)

                logger.warning(
                    "%s - %s - acquire: measurement is added to pending acquisition queue in failure scenario 1; sleep time is %d seconds",
                    measurement_rl_id, self.name, sleep_time,
                )
                return sleep_time

            elif self.remaining_capacity > 0 and len(self.pending_measurements_queue) > 0:
                if measurement_rl_id in self.pending_measurements_queue:
                    position = self.pending_measurements_queue.get_position(measurement_rl_id)

                    if position < self.remaining_capacity:
                        self.remaining_capacity -= 1
                        self.pending_measurements_queue.discard(measurement_rl_id)
                        logger.info(
                            "%s - %s - acquire: successful acquisition in successful scenario 2; remaining capacity is %d",
                            measurement_rl_id, self.name, self.remaining_capacity,
                        )
                        return 0.0
                    else:
                        if position + (self.measurement_rate + 1) >= len(self.pending_measurements_queue):
                            self.pending_measurements_queue.discard(measurement_rl_id)
                            sleep_time = (len(self.pending_measurements_queue) + 1) / self.measurement_rate

                            wake_up_time = now + sleep_time
                            self.pending_measurements_queue.push(measurement_rl_id, wake_up_time)
                            logger.warning(
                                "%s - %s - acquire: measurement is added to pending acquisition queue in failure scenario 2; sleep time is %d seconds",
                                measurement_rl_id, self.name, sleep_time,
                            )
                            return sleep_time
                        else:
                            sub_last_entry = self.pending_measurements_queue[position + self.measurement_rate]
                            last_entry = self.pending_measurements_queue[position + self.measurement_rate + 1]

                            wake_up_time_between_last_2_entries = ( sub_last_entry[1] + last_entry[1] ) / 2
                            sleep_time = max(wake_up_time_between_last_2_entries, now) - now


                            # if sleep time is less than 1 second mark it up to a random value between remaining time in the current second and 2 times of the remaining time in the current second to avoid additional attempt in the same second
                            remaining_time_in_current_second = 1.0 - (now - math.floor(now))

                            if sleep_time <= remaining_time_in_current_second:
                                sleep_time += random.uniform(remaining_time_in_current_second, remaining_time_in_current_second * 2)
                            else:
                                sleep_time += 10e-6

                            wake_up_time = now + sleep_time

                            self.pending_measurements_queue.discard(measurement_rl_id)
                            self.pending_measurements_queue.push(measurement_rl_id, wake_up_time)
                            logger.warning(
                                "%s - %s - acquire: measurement is added to pending acquisition queue in failure scenario 3; sleep time is %d seconds",
                                measurement_rl_id, self.name, sleep_time,
                            )
                            return sleep_time
                else:
                    sleep_time = (len(self.pending_measurements_queue) + 1) / self.measurement_rate
                    wake_up_time = now + sleep_time
                    self.pending_measurements_queue.push(measurement_rl_id, wake_up_time)
                    logger.warning(
                        "%s - %s - acquire: measurement is added to pending acquisition queue in failure scenario 4; sleep time is %d seconds",
                        measurement_rl_id, self.name, sleep_time,
                    )
                    return sleep_time
            return 0.0
