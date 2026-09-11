from bigfoot import start_system, Measurement, Config, configure_logging
import random

# PRE-STARTUP:
# First you should export RIPE_API_KEY environment variable with the API key generated on the RIPE Atlas interface.

# used to configure the logging of the system. All submodules will inherit this logger.
# logger = configure_logging()

# used to define the runtime parameters of the system.
config = Config(
    RIPE_API_KEY='YOUR_API_KEY',
    RIPE_MEASUREMENT_TIMEOUT=40,
    RIPE_POLLING_INTERVAL=10,
)

# start the system and get an instance of VantagePointManager.
vp_manager = start_system(config, start_ripe_polling_driver=True)

# get the names of the RIPE Atlas vantage points. 
ripe_vps = vp_manager.get_vp_names_of_platform(platform="ripe")

# or get names of all vantage points by calling get_vp_names()
# in this case they are the same as the RIPE Atlas vantage points.
all_vps = vp_manager.get_vp_names()

print(f"There are {len(ripe_vps)} RIPE Atlas vantage points")
print(f"There are {len(all_vps)} all vantage points")

# create a ping measurement with 3 RIPE Atlas vantage points to 8.8.8.8.
measurement = Measurement(
    target="8.8.8.8", 
    vps=random.sample(ripe_vps, 3), 
    measurement_type="ping",
)
# conduct the measurement
measurement.conduct_measurement()

print(f"Measurement finished with status {measurement.status}")
print(f"Results: {measurement.results}")