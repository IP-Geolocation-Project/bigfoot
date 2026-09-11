import os
import logging
import threading

from .config import Config
from .drivers import ArkPollingDriver, RipePollingDriver, AbstractDriver
from .measurements import Measurement, SubMeasurement, MeasurementScheduler

from .vps import VantagePointManager, VantagePoint

logger = logging.getLogger(__name__)


def start_system(
    config: Config,
    start_ripe_polling_driver: bool = False,
    start_ark_polling_driver: bool = False,
) -> VantagePointManager:
    """
    A function to start  the system.
  
    :param: config: Config - the configuration for the system.
    :param: start_ripe_polling_driver: bool - whether to start the Ripe Polling Driver.
    :param: start_ark_polling_driver: bool - whether to start the Ark Polling Driver.
    :return: VantagePointManager - the vantage point manager.
    """
    logger.info(
        "System is starting with drivers: ripe_polling=%s ark_polling=%s",
        start_ripe_polling_driver, start_ark_polling_driver,
    )

    vp_manager: VantagePointManager = VantagePointManager()
    vantage_points: dict[str, VantagePoint] = {}
  
    active_drivers: dict[str, AbstractDriver] = {}
    
    max_wait_time = -1

    if start_ripe_polling_driver:
        
        ripe_polling_driver: RipePollingDriver = RipePollingDriver(
            ripe_api_key=config.RIPE_API_KEY,
            scheduling_attempts=config.RIPE_SCHEDULING_ATTEMPTS,
            concurrency_limit=config.RIPE_MAX_CONCURRENT_MEASUREMENTS,
            measurement_timeout=config.RIPE_MEASUREMENT_TIMEOUT,
            polling_interval=config.RIPE_POLLING_INTERVAL,
            max_workers=config.RIPE_MEASUREMENT_POOL_SIZE,
        )

        ripe_vps = ripe_polling_driver.get_vps_details()
        logger.info("RipePollingDriver started; %d VPs available from RIPE Atlas", len(ripe_vps))

        for vp_name, vp_details in ripe_vps.items():
            vantage_point = VantagePoint(
                name=vp_name,
                platform='ripe',
                measurement_rate=config.RIPE_MEASUREMENT_RATE,
                get_load_of_vp=ripe_polling_driver.get_load_of_vp,
                max_load_increase=config.RIPE_MAX_LOAD_INCREASE,
                metadata=vp_details.copy()
            )
            vantage_points[vp_name] = vantage_point
            
        ripe_polling_driver.start()
        active_drivers['ripe'] = ripe_polling_driver
        max_wait_time = max(max_wait_time, config.RIPE_MEASUREMENT_TIMEOUT)

    else:
        logger.info("RIPE Atlas will not be connected")

    if start_ark_polling_driver:
        ark_polling_driver: ArkPollingDriver = ArkPollingDriver(
            grpc_threads=config.GRPC_THREADS,
            grpc_hostname=config.GRPC_HOSTNAME,
            grpc_port=config.GRPC_PORT,
            cert_directory=config.ARK_DAEMON_CERT_DIR,
            measurement_timeout=config.ARK_MEASUREMENT_TIMEOUT,
            polling_interval=config.ARK_POLLING_INTERVAL,
            max_workers=config.ARK_MEASUREMENT_POOL_SIZE,
        )
        ark_polling_driver.start()
        ark_vps = ark_polling_driver.get_vps_details()
        logger.info("ArkPollingDriver started; %d VPs available from Ark daemons", len(ark_vps))

        for vp_name, vp_details in ark_vps.items():
            vantage_point = VantagePoint(
                name=vp_name,
                platform='ark',
                measurement_rate=config.ARK_MEASUREMENT_RATE,
                get_load_of_vp=ark_polling_driver.get_load_of_vp,
                max_load_increase=config.ARK_MAX_LOAD_INCREASE,
                metadata=vp_details.copy()
            )
            vantage_points[vp_name] = vantage_point
        active_drivers['ark'] = ark_polling_driver

        max_wait_time = max(max_wait_time, config.ARK_MEASUREMENT_TIMEOUT)

    else:
        logger.info("Ark will not be connected")

    vp_manager.add_vps(vantage_points)

    Measurement.set_config(config)
    Measurement.set_vantage_point_mapping(vantage_points)
    SubMeasurement.configure_measurement_drivers(active_drivers)
    MeasurementScheduler.set_maximum_wait_time(max_wait_time)

    logger.info(
        "start_system finished: %d VPs registered, active drivers=%s",
        len(vantage_points), list(active_drivers.keys()),
    )

    for driver_name, driver in active_drivers.items():
        threading._register_atexit(driver.stop)
        logger.info("Registered atexit handler for %s driver", driver_name)

    return vp_manager
