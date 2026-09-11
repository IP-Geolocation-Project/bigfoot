# Bigfoot

`Bigfoot` is a metaplatform for conducting active network measurements across multiple measurement platforms. In the current iteration, `Bigfoot` supports the following measurement platforms:

| Platform | Measurements | Mode |
| --- | --- | --- |
| [RIPE Atlas](https://atlas.ripe.net) | ping | polling |
| [CAIDA Ark](https://www.caida.org/projects/ark/) | ping | polling |

## Documentation
A complete documentation of the `Bigfoot` codebase can be found at https://ip-geolocation-project.github.io/bigfoot/.

## Installation

`Bigfoot` was tested using __Python 3.14__. Currently, it can be installed from its GitHub repository.

- From the GitHub repository:
```bash
pip install git+https://github.com/IP-Geolocation-Project/bigfoot.git
```

## Usage
This section describes the steps that should be followed to start `Bigfoot` and run a measurement.

### Startup

To use `Bigfoot`, the following steps should be done on startup:

1. Create an instance of the `Config` class to define the runtime parameters. Depending on which drivers are used, a set of required parameters described below must be provided (information about all parameters can be found at [Configuration parameters](#configuration-parameters)).

    <details>
    <summary><b> RIPE Atlas</b></summary>

    - To conduct measurements on __RIPE Atlas__, export the `RIPE_API_KEY` environment variable with the respective API key.

    </details>

    <details>
    <summary><b> CAIDA Ark</b></summary>

    - To conduct measurements on __CAIDA Ark__, set the `GRPC_HOSTNAME` and `GRPC_PORT` parameters.
      - If the machine does not have a public domain name, set `GRPC_HOSTNAME` to `localhost` and create a tunnel to that machine using tunneling software such as `ngrok`.
    - To interact with the Ark platform, `Bigfoot` host runs a gRPC server. To start the server in __secure mode__, set the `ARK_DAEMON_CERT_DIR` parameter.
      - The directory given in `ARK_DAEMON_CERT_DIR` should contain `fullchain.pem` and `privkey.pem` in order to start the gRPC server in secure mode. By default, this parameter is set to `None`, therefore the gRPC server will start in insecure mode.
    - Then, start the daemon client on the machine connected to the __Ark__ platform, configured with the same hostname and port, and with the secure flag set to match the mode the gRPC server is running in. (More details can be found at https://github.com/IP-Geolocation-Project/ark_daemon_client.)
      - If tunneling software was used, set the hostname and port to the provided domain name and port.

    </details>

2. Call `start_system()`, passing the instance of the `Config` class and the (`start_ripe_polling_driver`, `start_ark_polling_driver`) flags. This function will configure the runtime parameters across `Bigfoot` and start the respective drivers in daemon threads.
3. Optionally, call `configure_logging()` to enable logging across the system.

### Running a measurement

#### Vantage Points
The `start_system` function returns an instance of the `VantagePointManager` class, which stores the list of all available vantage points across all used platforms. Two main methods are used to obtain the names of the vantage points from the `VantagePointManager`:

| Method | Returns |
| --- | --- |
| `get_vp_names()` | Names of all vantage points across every platform. |
| `get_vp_names_of_platform(platform)` | Names of vantage points from the specified platform ('ripe' or 'ark'). |

#### Measurement
A single measurement is managed by an instance of the `Measurement` class created using three parameters: a target, a set of vantage point names, and a measurement type. To conduct a measurement, the `conduct_measurement()` method of that instance should be called. Once the measurement is completed, its results and status can be obtained by accessing the attributes of that instance.

The measurement can finish with one of four statuses presented in the table below in order of precedence:

| Status | Description |
| --- | --- |
| `FINISHED` | Every vantage point returned a valid RTT. |
| `UNACQUIRED` | At least one vantage point never cleared the rate limiter, which is used to prevent each vantage point from being overloaded. This status is obtained when too many measurements using the same vantage point were scheduled in a short window of time. |
| `TIMEOUT` | At least one vantage point returned nothing within the platform timeout. |
| `FAILED` | At least one vantage point returned an invalid RTT (`-1` on RIPE Atlas). |

### Example
The snippet below can be used to conduct a measurement using a hybrid set of vantage points. More examples can be found in the _examples_ directory.

```python
from bigfoot import start_system, Measurement, Config, configure_logging
import random

# PRE-STARTUP:
# You should start the Ark daemon client on the server with a direct connection to the Ark platform.

# This function is used to configure the logging across the system. All submodules inherit this logger.
# logger = configure_logging()

# used to define the runtime parameters of the system.
config = Config(
    RIPE_API_KEY='API_KEY',
    RIPE_MEASUREMENT_TIMEOUT=40,
    RIPE_POLLING_INTERVAL=10,

    GRPC_HOSTNAME='HOSTNAME',
    GRPC_PORT='PORT',
    ARK_DAEMON_CERT_DIR=None, # if not None, the gRPC server will start in secure mode
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
```

## Configuration parameters

Every parameter below is a keyword argument of the singleton `Config` class.

### Rate Limiter

| Parameter | Type | Default | Description |
| ----- | ----- | ----- | ----- |
| `MAX_MEASUREMENT_ATTEMPT_COUNT` | `int` | `1` | Maximum number of attempts to obtain RTT from the set of requested vantage points. Default is 1 attempt, meaning that there will be no additional attempt on failure. |
| `RATE_LIMITER_MAX_ATTEMPT_COUNT` | `int` | `10` | Maximum number of times a rate-limiter will attempt to acquire each requested vantage point. Default is 10. |

### RIPE Atlas

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `RIPE_API_KEY` | `str` | - | RIPE Atlas API Key (__required parameter__). |
| `RIPE_MAX_CONCURRENT_MEASUREMENTS` | `int` | `100` | Maximum number of concurrent measurements on RIPE Atlas. Default is 100 concurrent measurements. When reached, the driver will sleep for 6 minutes before scheduling the next measurement. |
| `RIPE_MEASUREMENT_TIMEOUT` | `int` | `30` | Measurement timeout in seconds. Default is 30 seconds. |
| `RIPE_POLLING_INTERVAL` | `int` | `5` | Result polling interval in seconds. Default is 5 seconds. |
| `RIPE_SCHEDULING_ATTEMPTS` | `int` | `3` | Number of attempts to schedule a measurement on RIPE Atlas. Default is 3 attempts. |
| `RIPE_MAX_LOAD_INCREASE` | `int` | `200` | Maximum allowed increase of the RIPE Atlas probe/anchor load. Default is 200 measurements more than the initially recorded load. |
| `RIPE_MEASUREMENT_RATE` | `int` | `6` | Maximum number of measurements that could be dispatched per second on each probe/anchor. Default is 6 for RIPE Atlas. |
| `RIPE_MEASUREMENT_POOL_SIZE` | `int` | `100` | Size of the Thread Pool for the RIPE Atlas Driver. Default is 100 threads. |

### CAIDA Ark

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `GRPC_HOSTNAME` | `str` | - | gRPC hostname of the ARK gRPC server (__required parameter__).|
| `GRPC_PORT` | `str` | - | gRPC port of the ARK gRPC server (__required parameter__). |
| `ARK_DAEMON_CERT_DIR` | `Optional[str]` | `None` | The certificate directory for the gRPC server used by Ark. By default it is set to `None`, meaning that the server will start in the insecure mode. |
| `ARK_MEASUREMENT_TIMEOUT` | `int` | `30` | Measurement timeout in seconds. Default is 30 seconds. |
| `ARK_POLLING_INTERVAL` | `int` | `5` | Result polling interval in seconds. Default is 5 seconds. |
| `ARK_MAX_LOAD_INCREASE` | `int` | `-1` | Maximum allowed increase of the Ark node load. Default is -1, meaning that there is no cap on Ark nodes. |
| `ARK_MEASUREMENT_RATE` | `int` | `20` | Maximum number of measurements that could be dispatched per second on each node. Default is 20 measurements. |
| `ARK_MEASUREMENT_POOL_SIZE` | `int` | `1000` | Size of the Thread Pool for the Ark Driver. Default is 1000 threads. |
| `GRPC_THREADS` | `int` | `100` | gRPC thread pool size. Default is 100 threads. |

### Metadata

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `INCLUDE_METADATA` | `bool` | `False` | A flag used to indicate whether metadata should be exported during conversion of Measurement class to dictionary. Default is set to False. |

## License
This project is licensed under the MIT license.
