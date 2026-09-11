import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class Config:
    """
        Class to define runtime configuration.
                
        Args:
            Credentials and endpoints:
                RIPE_API_KEY (str): RIPE Atlas API key.
                GRPC_HOSTNAME (str): gRPC hostname of the ARK gRPC server.
                GRPC_PORT (str): gRPC port of the ARK gRPC server.

            Rate Limiter:
                MAX_MEASUREMENT_ATTEMPT_COUNT (int): Maximum number of attempts to obtain RTT from the set of requested vantage points. Default is 1 attempt, meaning that there will be no additional attempt on failure.
                RATE_LIMITER_MAX_ATTEMPT_COUNT (int): Maximum number of times a rate-limiter will attempt to acquire each requested vantage point. Default is 10.

            RIPE Atlas:
                RIPE_MAX_CONCURRENT_MEASUREMENTS (int): Maximum number of concurrent measurements on RIPE Atlas. Default is 100 concurrent measurements. When reached, the driver will sleep for 6 minutes before scheduling the next measurement.
                RIPE_MEASUREMENT_TIMEOUT (int): Measurement timeout in seconds. Default is 30 seconds.
                RIPE_POLLING_INTERVAL (int): Result polling interval in seconds. Default is 5 seconds.
                RIPE_SCHEDULING_ATTEMPTS (int): Number of attempts to schedule a measurement on RIPE Atlas. Default is 3 attempts.
                RIPE_MAX_LOAD_INCREASE (int): Maximum allowed increase of the RIPE Atlas probe/anchor load. Default is 200 measurements more than the initially recorded load.
                RIPE_MEASUREMENT_RATE (int): Maximum number of measurements that could be dispatched per second on each probe/anchor. Default is 6 for RIPE Atlas.
                RIPE_MEASUREMENT_POOL_SIZE (int): Size of the Thread Pool for the RIPE Atlas Driver. Default is 100 threads.

            ARK:
                ARK_DAEMON_CERT_DIR (Optional[str]): The certificate directory for the gRPC server used by Ark. By default it is set to None, meaning that the server will start in the insecure mode.
                ARK_MEASUREMENT_TIMEOUT (int): Measurement timeout in seconds. Default is 30 seconds.
                ARK_POLLING_INTERVAL (int): Result polling interval in seconds. Default is 5 seconds.
                ARK_MEASUREMENT_RATE (int): Maximum number of measurements that could be dispatched per second on each node. Default is 20 measurements.
                ARK_MAX_LOAD_INCREASE (int): Maximum allowed increase of the Ark node load. Default is -1, meaning that there is no cap on Ark nodes.
                ARK_MEASUREMENT_POOL_SIZE (int): Size of the Thread Pool for the Ark Driver. Default is 1000 threads.
                GRPC_THREADS (int): gRPC thread pool size. Default is 100 threads.

            Metadata:
                INCLUDE_METADATA (bool): A flag used to indicate whether metadata should be exported during conversion of Measurement class to dictionary. Default is set to False.
    """

    _lock = threading.Lock()
    _instance = None

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
        RIPE_API_KEY: str = None, 
        GRPC_HOSTNAME: str = None,
        GRPC_PORT: str = None,

        MAX_MEASUREMENT_ATTEMPT_COUNT: int = 1, 
        RATE_LIMITER_MAX_ATTEMPT_COUNT: int = 10,

        RIPE_MAX_CONCURRENT_MEASUREMENTS: int = 100,
        RIPE_MEASUREMENT_TIMEOUT: int = 30,
        RIPE_POLLING_INTERVAL: int = 5,
        RIPE_SCHEDULING_ATTEMPTS: int = 3,
        RIPE_MAX_LOAD_INCREASE: int = 200,
        RIPE_MEASUREMENT_RATE: int = 6,
        RIPE_MEASUREMENT_POOL_SIZE: int = 100, # default number of concurrent measurements

        ARK_DAEMON_CERT_DIR: Optional[str] = None,
        ARK_POLLING_INTERVAL: int = 5,
        ARK_MEASUREMENT_TIMEOUT: int = 30,
        GRPC_THREADS: int = 100,
        ARK_MAX_LOAD_INCREASE: int = -1,
        ARK_MEASUREMENT_RATE: int = 20,
        ARK_MEASUREMENT_POOL_SIZE: int = 1000,

        INCLUDE_METADATA: bool = False,
    ) -> None:

        if hasattr(self, '_initialized'):
            return

        if RIPE_API_KEY is None and GRPC_HOSTNAME is None and GRPC_PORT is None:
            raise Exception("Either RIPE Atlas or Ark Driver must be configured!")
        
        if RIPE_API_KEY is None:
            if (GRPC_HOSTNAME is None and GRPC_PORT is not None) or (GRPC_PORT is not None and GRPC_HOSTNAME is None):
                raise Exception("Both GRPC_HOSTNAME and GRPC_PORT parameters are required to start the Ark Driver")
            
        self._initialized = True

        self.RIPE_API_KEY = RIPE_API_KEY
        self.GRPC_HOSTNAME = GRPC_HOSTNAME
        self.GRPC_PORT = GRPC_PORT
        self.ARK_DAEMON_CERT_DIR = ARK_DAEMON_CERT_DIR

        self.MAX_MEASUREMENT_ATTEMPT_COUNT = MAX_MEASUREMENT_ATTEMPT_COUNT
        self.RATE_LIMITER_MAX_ATTEMPT_COUNT = RATE_LIMITER_MAX_ATTEMPT_COUNT
        
        self.RIPE_MAX_CONCURRENT_MEASUREMENTS = RIPE_MAX_CONCURRENT_MEASUREMENTS
        self.RIPE_MEASUREMENT_TIMEOUT = RIPE_MEASUREMENT_TIMEOUT
        self.RIPE_POLLING_INTERVAL = RIPE_POLLING_INTERVAL
        self.RIPE_SCHEDULING_ATTEMPTS = RIPE_SCHEDULING_ATTEMPTS
        self.RIPE_MAX_LOAD_INCREASE = RIPE_MAX_LOAD_INCREASE
        self.RIPE_MEASUREMENT_RATE = RIPE_MEASUREMENT_RATE
        self.RIPE_MEASUREMENT_POOL_SIZE = RIPE_MEASUREMENT_POOL_SIZE

        self.ARK_MEASUREMENT_TIMEOUT = ARK_MEASUREMENT_TIMEOUT
        self.ARK_POLLING_INTERVAL = ARK_POLLING_INTERVAL
        self.GRPC_THREADS = GRPC_THREADS
        self.ARK_MAX_LOAD_INCREASE = ARK_MAX_LOAD_INCREASE
        self.ARK_MEASUREMENT_RATE = ARK_MEASUREMENT_RATE
        self.ARK_MEASUREMENT_POOL_SIZE = ARK_MEASUREMENT_POOL_SIZE

        self.INCLUDE_METADATA = INCLUDE_METADATA
        logger.info("Config is initialized: %s", self)

    def __str__(self):
        """Returns a formatted string representation of the configuration"""
        result = ["\n Metron Configuration Settings:", "═" * 50]
        for key, value in vars(self).items():
            if key == '_initialized':
                continue
            result.append(f"\t{key.ljust(30)}: {value}")
        result.append("═" * 50)
        return "\n".join(result)