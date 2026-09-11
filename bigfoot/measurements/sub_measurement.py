import logging
import time
import threading

from typing import Optional
from collections import defaultdict

from bigfoot.vps import VantagePoint
from .measurement_status import MeasurementStatus

logger = logging.getLogger(__name__)

class SubMeasurement:

    MEASUREMENT_DRIVERS: Optional[dict[str, "AbstractDriver"]] = None
     
    @classmethod
    def configure_measurement_drivers(cls, drivers: dict[str, "AbstractDriver"]):
        """
        A method to configure the measurement drivers that should be used to run the measurements. 
       
:param:: drivers: dict[str, "AbstractDriver"] - a dictionary representing measurement drivers with platform names as keys and instances of the "AbstractDriver" as values. 
        """
        cls.MEASUREMENT_DRIVERS = drivers.copy()
        logger.info("SubMeasurement.MEASUREMENT_DRIVERS configured for platforms: %s", list(drivers.keys()))

    def __init__(self, target: str, vps: list[VantagePoint], measurement_type: str):
        """
        A method to initialize the AbstractMeasurement class.
      
        :param: target: str - the target for the measurent.
        :param: vps: list[VantagePoint] - the instances of the VantagePoint class reprenting vantage points to conduct the measurements from.
        :param: measurement_type: str - the type of measurement to conduct.
        :return: None
        """

        if SubMeasurement.MEASUREMENT_DRIVERS is None:
            raise ValueError(f"{target} - SubMeasurement.MEASUREMENT_DRIVERS were not configured")
        
        self.target = target
        self.vps = vps.copy()
        self.measurement_type = measurement_type
        
        self.scheduled_measurements: dict["AbstractDriver", dict[str, str]] = {}
        self.status: MeasurementStatus = MeasurementStatus.CREATED
        self.results: dict = {}
        self.measurement_start_time = time.monotonic()
        self.runtime: float = 0.0
        self.completed_event = threading.Event()

        self.lock = threading.Lock()
        self.pending_callbacks = 0

        self.metadata: dict = {
            'start_time': time.monotonic(),
            'vps': [vp.name for vp in vps],
            'measurement_type': measurement_type,
            'load_of_vps': {},
        }

        logger.info("%s - __init__: SubMeasurement initialized with vps=%s for measurement_type=%s", self.target, ', '.join([vp.name for vp in vps]), measurement_type)

    def callback(self, results: dict, status: MeasurementStatus, metadata: Optional[dict]):
        """
        A callback method invoked by a driver when its portion of the measurement is completed.
        Safe to be called concurrently from multiple drivers; results are merged and the
        completed_event is only set once every dispatched driver has reported.
       
        :param: results: dict[str, float] - the results of the measurement.
        :param: status: MeasurementStatus - the status of the measurement.
        :param: metadata: dict - the metadata of the measurement.
        :return: None
        """

        with self.lock:
            metadata = metadata or {}
            if metadata:
                self.metadata.update({
                    metadata['measurement_id']: metadata['runtimes'],
                })
                self.metadata['load_of_vps'].update(metadata['load_of_vps'])

            self.results.update(results)
             
            self.runtime = time.monotonic() - self.measurement_start_time

            self.pending_callbacks -= 1
            logger.debug(
                "%s - callback: returned with status=%s and results=%s; There are %d pending callbacks.",
                self.target, status, results, self.pending_callbacks,
            )

            if self.pending_callbacks <= 0:
                self.status = self.analyse_results()
          
                self.metadata.update({
                    'runtime': self.runtime,
                    'end_time': time.monotonic(),
                    'status': self.status.value,
                    'results': self.results.copy(),
                })

                self.completed_event.set()
                logger.info(
                    "%s - callback: completed with status=%s runtime=%.2fs results=%d/%d - %s",
                    self.target, self.status, self.runtime, len(self.results), len(self.vps), self.results,
                )

    def analyse_results(self) -> MeasurementStatus:
        """
        A method to analyse the results of the measurement.
      
        :return: MeasurementStatus - the status of the measurement.
        """
        logger.info("%s - analyse_results: analysing the results=%s;", self.target, self.results)

        if len(self.results) != len(self.vps):
            return MeasurementStatus.TIMEOUT
        else:
            for rtt in self.results.values():
                if rtt == -1.0:
                    return MeasurementStatus.FAILED
            return MeasurementStatus.FINISHED
            
    def start_measurement(self):
        """
        A method to start the measurement.
      
        :return: None
        """
        try:
            logger.debug("%s - start_measurement: starting measurement with vps=%s", self.target, ', '.join([vp.name for vp in self.vps]))
            self.measurement_start_time = time.monotonic()

            vp_names_per_driver: dict["AbstractDriver", list[str]] = defaultdict(list)
            for vp in self.vps:
                vp_names_per_driver[ SubMeasurement.MEASUREMENT_DRIVERS.get(vp.platform, None) ].append(vp.name)

            with self.lock:
                self.pending_callbacks = len(vp_names_per_driver)
                self.status = MeasurementStatus.RUNNING

            for driver, vp_names in vp_names_per_driver.items():

                if driver is None:
                    logger.error(
                        "%s - start_measurement: no driver registered for vantage points: %s",
                        self.target, ", ".join(vp_names),
                    )
                    self.callback({}, MeasurementStatus.FAILED, {})
                    continue
                driver.conduct_measurement(
                    completed_callback=self.callback,
                    measurement_type=self.measurement_type,
                    target=self.target,
                    vps=vp_names
                )

                logger.info(
                    "%s - start_measurement: dispatched a SubMeasurement to driver=%s",
                    self.target, type(driver).__name__,
                )
        except Exception as e:
            logger.exception("%s - start_measurement: error starting measurement: %s", self.target, e)
            self.callback({}, MeasurementStatus.FAILED, {})
