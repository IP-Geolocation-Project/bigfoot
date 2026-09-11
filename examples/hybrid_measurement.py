from bigfoot import start_system, Measurement, Config, configure_logging
import random

# PRE-STARTUP:
# First you should export RIPE_API_KEY environment variable with the API key generated on the RIPE Atlas interface.
# Also you should start the Ark daemon client on the server with the direct connection to the Ark platform.

# used to configure the logging of the system. All submodules will inherit this logger.
# logger = configure_logging()

# used to define the runtime parameters of the system.
config = Config(
    GRPC_HOSTNAME='YOUR_HOSTNAME',
    GRPC_PORT='YOUR_PORT',
    RIPE_API_KEY='YOUR_API_KEY',
    RIPE_MEASUREMENT_TIMEOUT=40,
    RIPE_POLLING_INTERVAL=10,
    ARK_POLLING_INTERVAL=5,
    ARK_MEASUREMENT_TIMEOUT=20,
)

# start the system and get an instance of VantagePointManager.
vp_manager = start_system(config, start_ripe_polling_driver=True, start_ark_polling_driver=True)

# get the names of the vantage points from each measurement platform. 
ripe_vps = vp_manager.get_vp_names_of_platform(platform="ripe")
ark_vps = vp_manager.get_vp_names_of_platform(platform="ark")

# or get names of all vantage points by calling get_vp_names()
all_vps = vp_manager.get_vp_names()

print(f"There are {len(ripe_vps)} RIPE Atlas vantage points")
print(f"There are {len(ark_vps)} ARK vantage points")

# create a ping measurement with 3 RIPE Atlas and 3 ARK vantage points to 8.8.8.8.
measurement = Measurement(
    target="8.8.8.8", 
    vps=random.sample(ripe_vps, 3) + random.sample(ark_vps, 3), 
    measurement_type="ping",
)
# conduct the measurement
measurement.conduct_measurement()

print(f"Measurement finished with status {measurement.status}")
print(f"Results: {measurement.results}")