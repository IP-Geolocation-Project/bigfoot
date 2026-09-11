# pylint: disable=no-member
# TO Regenerate the pb2 files from .proto use this in the home directory
# python -m grpc_tools.protoc -I=. --python_out=. --grpc_python_out=. bigfoot/drivers/ark/ark_daemon.proto

import json
import logging
from pathlib import Path
import queue
import time
import threading
import concurrent.futures

from enum import Enum, auto
from typing import Optional
from dataclasses import dataclass, field

import grpc

from bigfoot.drivers.abstract_driver import AbstractDriver
from bigfoot.measurements import MeasurementStatus
from . import ark_daemon_pb2
from . import ark_daemon_pb2_grpc

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """
    An enum to represent the state of a session for a given daemon.
    """
    UNINITIALIZED = auto()  # Session created
    PENDING       = auto()  # Waiting for VP information
    READY         = auto()  # Initialized and VPs received

BAD_ARK_NODES = set(
    [
        'akl-nz',
        'ams8-nl',
        'atl3-us',
        'avv-au',
        'bbu2-ro',
        'bcb-us',
        'bed-us',
        'bfi-us',
        'bio-es',
        'bos6-us',
        'bre-de',
        'bwi3-us',
        'bzn-us',
        'cdg3-fr',
        'cld3-us',
        'cld4-us',
        'cld5-us',
        'cld6-us',
        'coe-us',
        'dps-id',
        'ens2-nl',
        'her2-gr',
        'ida-us',
        'igx2-us',
        'kun-lt',
        'las-us',
        'lej-de',
        'lex-us',
        'lgw-uk',
        'lis-pt',
        'lke2-us',
        'med2-co',
        'mem-us',
        'mhg-de',
        'muc4-de',
        'okc2-us',
        'ory5-fr',
        'pdx-us',
        'phl-us',
        'pit-us',
        'poa2-br',
        'psa-it',
        'pvu-us',
        'pvu3-us',
        'qlr-pt',
        'san2-us',
        'san4-us',
        'sav-us',
        'snn-ie',
        'svo-ru',
        'tlv3-il',
        'tpe-tw',
        'tul2-us',
        'tus-us',
        'tus2-us',
        'vie2-at',
        'ygk-ca',
        'zrh3-ch',
        'zrh4-ch',
        'dtw2-us',
        'lgw-uk',
        'lis-pt',
        'med2-co',
        'nrt3-jp',
        'ygk-ca',
        'yyc-ca'
    ]
)

@dataclass
class Session:
    """
    A data class to represent a session for a given daemon.
    """
    daemon_id: str
    load: int = field(default=0)
    scheduled_measurements: set = field(default_factory=set)

    state: SessionState = field(default=SessionState.UNINITIALIZED)

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def get_daemon_info(self) -> ark_daemon_pb2.DaemonInfo: # type: ignore[attr-defined, name-defined]
        """
        A method to get the daemon information.
       
        :return: ark_daemon_pb2.DaemonInfo - the daemon information.
        """
        return ark_daemon_pb2.DaemonInfo(daemon_id=self.daemon_id) # type: ignore[attr-defined]

    def is_initialized(self) -> bool:
        """
        A method to check if the session is initialized.
       
        :return: bool - True if the session is initialized, False otherwise.
        """
        with self._lock:
            return self.state != SessionState.UNINITIALIZED

    def is_pending(self) -> bool:
        """
        A method to check if the session is pending to receive the vantage points from the daemon.
       
        :return: bool - True if the session is pending, False otherwise.
        """
        with self._lock:
            return self.state == SessionState.PENDING

    def is_ready(self) -> bool:
        """
        A method to check if the session is ready to conduct measurements.
     
        :return: bool - True if the session is ready, False otherwise.
        """
        with self._lock:
            return self.state == SessionState.READY

    def initialize(self) -> None:
        """
        A method to initialize the session.
   
        :return: None
        """
        with self._lock:
            if self.state != SessionState.UNINITIALIZED:
                logger.warning("%s - initialize: session already initialized; refusing to reinitialize", self.daemon_id)
                raise DaemonException("Daemon is already initialized.") # pylint: disable=broad-exception-raised
            self.state = SessionState.PENDING
            logger.info("%s - initialize: session for daemon initialized (state=PENDING)", self.daemon_id)

    def schedule_measurement(
        self,
        target: str,
        vps: list[str],
        measurement_id: str,
    ) -> ark_daemon_pb2.MSM_REQ: # type: ignore[attr-defined, name-defined]
        """
        A method to schedule a measurement.
     
       :param: target: str - the target of the measurement.
        :param: vps: list[str] - the vantage points of the measurement.
        :param: measurement_id: str - the id of the measurement.
        :return: ark_daemon_pb2.MSM_REQ - the measurement request.
        """
        grpc_measurement_object = self.__convert_to_measurement_request(measurement_id, target, vps)
        with self._lock:
            self.load += 1
            self.scheduled_measurements.add(measurement_id)
            return grpc_measurement_object

    def __convert_to_measurement_request(
        self,
        measurement_id: str,
        target: str,
        vps: list[str]
    ) -> ark_daemon_pb2.MSM_REQ: # type: ignore[attr-defined, name-defined]
        return ark_daemon_pb2.MSM_REQ( # type: ignore[attr-defined, name-defined]
            measurement_id=str(measurement_id),
            target=target,
            vps=vps,
        )

    def discard_measurement(self, measurement_id: str) -> bool:
        """
        A method to discard a measurement.
       
        :param: measurement_id: str - the id of the measurement.
        :return: bool - True if the measurement was discarded, False otherwise.
        """
        with self._lock:
            if measurement_id in self.scheduled_measurements:
                self.scheduled_measurements.discard(measurement_id)
                self.load -= 1
                return True
            return False

    def vps_received(self):
        """
        A method to receive the information about the vantage points.
     
        :return: None
        """
        with self._lock:
            if self.state != SessionState.PENDING:
                logger.warning("%s - vps_received: session is not waiting for vantage points (state=%s).", self.daemon_id, self.state.name)
                raise DaemonException(f"{self.daemon_id} - vps_received: daemon is not waiting for vantage points.") # pylint: disable=broad-exception-raised

            self.state = SessionState.READY
            logger.info("%s - vps_received: session for daemon received vantage points (state=%s)", self.daemon_id, self.state)

    def request_vps_again(self):
        """
        A method to request the vantage points again.
    
        :return: None
        """
        with self._lock:
            if self.state is SessionState.UNINITIALIZED:
                raise DaemonException(f"{self.daemon_id} - request_vps_again: cannot invalidate vantage points on uninitialized session.") # pylint: disable=broad-exception-raised

            self.state = SessionState.PENDING
            logger.info("%s - request_vps_again: session for daemon reset to %s (will request vantage points again)", self.daemon_id, self.state)

    def reset(self):
        """
        A method to reset the session.
  
        :return: None
        """
        with self._lock:
            logger.info(
                "%s - reset: resetting session for daemon; discarding %d measurements",
                self.daemon_id, len(self.scheduled_measurements),
            )
            self.load = 0
            self.scheduled_measurements.clear()
            self.state = SessionState.UNINITIALIZED

class DaemonException(Exception):
    """
    A custom exception class for handling errors related to the daemon communication in the Ark C2 system.
    """
    def __init__(self, message):
        super().__init__(message)

class ArkPollingDriver(AbstractDriver, ark_daemon_pb2_grpc.MeasurementService):
    """
    A class to represent the ARK driver.
    """
    FIRST_MEASUREMENT_RETRIEVAL_TIMEOUT: int = 10

    MEASUREMENT_ID_LOCK: threading.Lock = threading.Lock()
    MEASUREMENT_ID_COUNTER: int = 0

    LOAD_CHECKING_PAUSE: int = 10

    def __init__(self,
        grpc_threads: int,
        grpc_hostname: str,
        grpc_port: str,
        cert_directory: Optional[str],
        measurement_timeout: int,
        polling_interval: int,
        max_workers: int,
    ):
        super().__init__(measurement_timeout, polling_interval, max_workers)
        self.grpc_threads = grpc_threads
        self.grpc_hostname = grpc_hostname
        self.grpc_port = grpc_port
        self.cert_directory = cert_directory
        self.sessions_lock = threading.Lock()
        self.daemon_sessions: dict[str, Session] = {}

        self.measurements_to_schedule: queue.Queue = queue.Queue()
        self.grpc_server = None
        self.grpc_server_thread = None

        logger.info("__init__: initialized ArkPollingDriver")

    def start(self, *args, **kwargs):
        """
        A method to start the ArkPollingDriver.
    
        :return: None
        """
        SERVER_OPTS = [
            ("grpc.http2.min_ping_interval_without_data_ms", 120_000),  # >= client keepalive_time
            ("grpc.http2.max_ping_strikes", 5),  # more tolerant

            ("grpc.keepalive_time_ms", 120_000),
            ("grpc.keepalive_timeout_ms", 30_000),
            ("grpc.keepalive_permit_without_calls", 0),  # avoid idle pings if possible
            ("grpc.http2.max_pings_without_data", 2),

            ("grpc.max_send_message_length", -1),
            ("grpc.max_receive_message_length", -1),
        ]

        self.grpc_server = grpc.server(
            concurrent.futures.ThreadPoolExecutor(max_workers=self.grpc_threads),
            options=SERVER_OPTS
        )

        ark_daemon_pb2_grpc.add_MeasurementServiceServicer_to_server(self, self.grpc_server)

        # if certificate directory is provided, load the certificates
        if self.cert_directory:
            SERVER_CERTIFICATE = ArkPollingDriver._load_credential_from_file(f"{self.cert_directory}/fullchain.pem")
            SERVER_CERTIFICATE_KEY = ArkPollingDriver._load_credential_from_file(f"{self.cert_directory}/privkey.pem")
            server_credentials = grpc.ssl_server_credentials(((SERVER_CERTIFICATE_KEY, SERVER_CERTIFICATE),))

            self.grpc_server.add_secure_port(f"{self.grpc_hostname}:{self.grpc_port}", server_credentials)
            logger.info("start: Starting gRPC server (secure) at %s:%s", self.grpc_hostname, self.grpc_port)

        else:
            self.grpc_server.add_insecure_port(f"{self.grpc_hostname}:{self.grpc_port}")
            logger.info("start: Starting gRPC server (insecure) at %s:%s", self.grpc_hostname, self.grpc_port)

        def run_grpc_server():
            self.grpc_server.start()
            try:
                self.grpc_server.wait_for_termination()
            except KeyboardInterrupt:
                logger.error("run_grpc_server: Received KeyboardInterrupt, stopping gRPC server for Ark Measurement Driver")
            except Exception: # pylint: disable=broad-exception-caught
                logger.exception("run_grpc_server: Error while running gRPC server for Ark Measurement Driver")
            finally:
                self.grpc_server.stop(grace=5)
                logger.info("run_grpc_server: gRPC server for Ark Measurement Driver stopped")

        self.grpc_server_thread = threading.Thread(
            target=run_grpc_server,
            daemon=True,
            name="ArkMeasurementDriverGRPCServer"
        )
        self.grpc_server_thread.start()

        logger.info("start: started gRPC server thread")

        self.wait_for_daemon_init()

        # retrieve_load_of_vps_stop_event = threading.Event()
        # retrieve_load_of_vps_thread = threading.Thread(
        #     target=self.retrieve_load_of_vps, args=(retrieve_load_of_vps_stop_event,),
        #     daemon=True
        # )
        # retrieve_load_of_vps_thread.start()
        # logger.info("start: Started background thread retrieve_load_of_vps for ArkPollingDriver")

        # self.BACKGROUND_TASKS['retrieve_load_of_vps'] = {
        #     'event': retrieve_load_of_vps_stop_event,
        #     'thread': retrieve_load_of_vps_thread
        # }

    def stop(self):
        """
        A method to stop the ArkPollingDriver.
    
        :return: None
        """
      

        logger.info("stop: Stopping ArkPollingDriver: signalling %d background tasks", len(self.BACKGROUND_TASKS))
        for thread_name, thread_info in self.BACKGROUND_TASKS.items():
            thread_info['event'].set()
            thread_info['thread'].join(timeout=30)
            logger.info("stop:Stopped background thread %s", thread_name)

        logger.info("stop: All ArkPollingDriver background tasks stopped; shutting down measurement executor")
        
        self.MEASUREMENT_EXECUTOR.shutdown(wait=True, cancel_futures=True)
        logger.info("stop: Measurement Executor for ArkPollingDriver stopped.")
        
        if self.grpc_server is not None:
            self.grpc_server.stop(grace=5).wait(timeout=10)
            logger.info('stop: Stopped gRPC server')
        if self.grpc_server_thread is not None:
            self.grpc_server_thread.join(timeout=10)
            logger.info('stop: Stopped gRPC server thread')

        logger.info("stop:ArkPollingDriver stopped")

    def schedule_ping_measurement(self, **kwargs) -> tuple[str, list[str], Optional[str]]:
        """
        A method to schedule a ping measurement on the Ark platform.

        :return: tuple[str, list[str], Optional[str]] - the target, vps, and measurement id.
        """
        target = kwargs.get("target")
        vps = kwargs.get("vps")

        if target is None or vps is None:
            return "", [], None
        if target == "" or vps == []:
            return "", [], None

        with ArkPollingDriver.MEASUREMENT_ID_LOCK:
            measurement_id = str(ArkPollingDriver.MEASUREMENT_ID_COUNTER)
            ArkPollingDriver.MEASUREMENT_ID_COUNTER += 1

        self.measurements_to_schedule.put((target, vps, measurement_id))
        logger.info("%s - schedule_ping_measurement: scheduled ping measurement %s with VPs %s", target, measurement_id, vps)
        
        return target, vps, measurement_id

    def query_results(self, measurement_id: str, target: str, vps: list[str]) -> dict[str, float]:
        """
        A method to query the results of a measurement from the Ark platform.

        :param: measurement_id: str - the id of the measurement.
        :param: target: str - the target of the measurement.
        :param: vps: list[str] - the vantage points of the measurement.
        :return: dict[str, float] - the results of the measurement.
        """

        results_querying_start_time = time.monotonic()
        results: dict[str, float] = {}
        while len(results) != len(vps) and time.monotonic() - results_querying_start_time < self.measurement_timeout:
            time.sleep(self.polling_interval)

            results = self.get_results(measurement_id)

        logger.info("%s - query_results: received the results for measurement %s: %d/%d", target, measurement_id, len(results), len(vps))

        return results

    def analyse_ping_results(self, results: dict[str, float], vps: list[str]) -> MeasurementStatus:
        """
        A method to analyse the results of a ping measurement.

        :param: results: dict[str, float] - the results of the measurement.
        :param: vps: list[str] - the vantage points of the measurement.
        :return: MeasurementStatus - the status of the measurement.
        """

        status = MeasurementStatus.FINISHED

        if set(results.keys()) != set(vps):
            status = MeasurementStatus.TIMEOUT
        else:
            for rtt in results.values():
                if rtt == -1.0:
                    status = MeasurementStatus.FAILED

        return status


    def retrieve_load_of_vps(self, stop_event: threading.Event):
        """
        A method to retrieve the load of the vantage points from the Ark platform.

        :param: stop_event: threading.Event - the event to stop the thread.
        :return: None
        """
        pass
        # while not stop_event.is_set():
        #     time.sleep(ArkPollingDriver.LOAD_CHECKING_PAUSE)
        #     with self.load_lock:
        #         with open('latest_load_of_ark_vps.json', 'w', encoding='utf-8') as f:
        #             json.dump(self.latest_load_of_vps, f, indent=4)
        # return

    def fetch_load_of_vp(self, vp_name: str) -> int:
        """
        A method to fetch the load of the vantage point from the Ark platform.

        :param: vp_name: str - the name of the vantage point.
        :return: int - the load of the vantage point.
        """
        return 0

    # DRIVER SPECIFIC METHODS
    def get_session(self, daemon_id: str) -> Optional[Session]:
        """
        A method to get the session for a given daemon.
       
        :param: daemon_id: str - the id of the daemon.
        :return: Optional[Session] - the session for the given daemon.
        """
        with self.sessions_lock:
            return self.daemon_sessions.get(daemon_id, None)

    def is_daemon_registered(self, daemon_id: str) -> bool:
        """
        A method to check if a given daemon is registered.
       
        :param: daemon_id: str - the id of the daemon.
        :return: bool - True if the daemon is registered, False otherwise.
        """
        with self.sessions_lock:
            return daemon_id in self.daemon_sessions

    def require_ready_session(self, daemon_id: str, context) -> Optional[Session]:
        """
        A method to return a ready session or abort the RPC. Aborts raise immediately.
       
        :param: daemon_id: str - the id of the daemon.
        :param: context: grpc.ServicerContext - the context of the RPC.
        :return: Optional[Session] - the ready session or None if the daemon is not registered or not ready.
        """

        session = self.get_session(daemon_id)
        if session is None:
            logger.warning("require_ready_session: rejecting RPC due to unregistered daemon %s", daemon_id)
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Daemon is not registered!")
            return None
        elif not session.is_ready():
            logger.warning("require_ready_session: rejecting RPC because daemon %s is not ready (vantage points not received)", daemon_id)
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Daemon has not sent vantage points yet!")
            return None
        else:
            return session

    def wait_for_daemon_init(self):
        """
        Block until at least one daemon has registered and sent its VPs.
        """
        logger.info("Waiting for at least one Ark daemon to register and send VPs")

        while True:

            time.sleep(0.5)
            with self.sessions_lock:
                sessions = list(self.daemon_sessions.values())
            for session in sessions:
                if session.is_ready():
                    logger.info("%s - wait_for_daemon_init: daemon is ready; ArkPollingDriver startup unblocked", session.daemon_id)
                    return True

    def RegisterDaemon(self, request, context): # pylint: disable=unused-argument
        """
        A gRPC method that is used by daemon to register itself with the Driver.

        :param: request: ark_daemon_pb2.DaemonRegisterRequest - the request from the daemon.
        :param: context: grpc.ServicerContext - the context of the RPC.
        :return: ark_daemon_pb2.DaemonConfig - the configuration for the daemon.
        """
        daemon_id = request.daemon_id

        new_session = Session(daemon_id=daemon_id)

        with self.sessions_lock:
            old_session = self.daemon_sessions.get(daemon_id)
            self.daemon_sessions[daemon_id] = new_session

        # Reset the old session after swap, since it wont be used anymore.
        if old_session is not None:
            try:
                old_session.reset()
                logger.info("%s - grpc.RegisterDaemon: reset the old session for daemon", daemon_id)
            except Exception: # pylint: disable=broad-exception-caught
                logger.exception("%s - grpc.RegisterDaemon: error resetting old session", daemon_id)

        try:
            new_session.initialize()
            logger.info("%s - grpc.RegisterDaemon: initialized the new session for daemon", daemon_id)
        except DaemonException:
            # Fresh session should never already be initialized; log & continue.
            logger.warning("%s - grpc.RegisterDaemon: new session was already initialized", daemon_id)

        return ark_daemon_pb2.DaemonConfig(
            daemon_info=new_session.get_daemon_info(),
        )


    def GetAllVantagePoints(self, request, context):
        """
        A gRPC method that is used by daemon to check if Driver is waiting for the information about the vantage points.

        :param: request: ark_daemon_pb2.DaemonInfo - the request from the daemon.
        :param: context: grpc.ServicerContext - the context of the RPC.
        :return: ark_daemon_pb2.VP_ACK - the acknowledgement of the vantage points.
        """
        daemon_id = request.daemon_id
        session = self.get_session(daemon_id)
        if session is None:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Daemon is not registered!")
            return

        status = bool(session.is_pending())
        if status:
            logger.debug("%s - grpc.GetAllVantagePoints: the session is waiting for daemon to send vantage points; asking it to send them", daemon_id)
        else:
            logger.debug("%s - grpc.GetAllVantagePoints: the daemon has already sent the information about the vantage points", daemon_id)

        return ark_daemon_pb2.VP_ACK(status=status)


    def SendVantagePoints(self, request, context):
        """
        A gRPC method that is used by daemon to send the information about the vantage points.

        :param: request: ark_daemon_pb2.DaemonInfo - the request from the daemon.
        :param: context: grpc.ServicerContext - the context of the RPC.
        :return: ark_daemon_pb2.VP_ACK - the acknowledgement of the vantage points.
        """
        daemon_info = request.daemon_info
        session = self.get_session(daemon_info.daemon_id)
        if session is None:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Daemon is not registered!")
        else:
            status = True
            try:
                vantage_points_data = json.loads(request.vantage_points_data)
                vps = {}
                for vp in vantage_points_data:
                    is_stable = True if vp['shortname'] not in BAD_ARK_NODES else False

                    vps[vp['shortname']] = {
                        "name": vp["name"],
                        "asn": vp["asn"],
                        "ipv4": vp["ipv4"],
                        "country_code": vp["country_code"],
                        "state": vp["state"],
                        "place": vp["place"],
                        "location": vp["location"],
                        "tags": vp["tags"],
                        "is_anchor": vp["is_anchor"],
                        'is_stable': is_stable,
                    }
                with self.vps_lock:
                    self.vps = vps
                session.vps_received()

            except (DaemonException, json.JSONDecodeError, TypeError):
                logger.exception("%s - grpc.SendVantagePoints: exception when processing vantage points received from daemon", daemon_info.daemon_id)
                status = False

            logger.info("%s - grpc.SendVantagePoints: daemon sent vantage points; total: %d", daemon_info.daemon_id, len(self.vps))
            return ark_daemon_pb2.VP_ACK(status=status)

    def SendMeasurementResultsBulk(self, request, context):  # pylint: disable=unused-argument
        """
        A gRPC method that is used by daemon to send the measurement results.

        :param: request: ark_daemon_pb2.MeasurementResultsBulk - the request from the daemon.
        :param: context: grpc.ServicerContext - the context of the RPC.
        :return: ark_daemon_pb2.MSM_ACK_BULK - the acknowledgement of the measurement results.
        """
        acks = []

        for measurement_result in request.measurement_results:
            # target = measurement_result.target
            measurement_id: str = measurement_result.measurement_id
            min_rtt = measurement_result.min_rtt
            instance = measurement_result.instance
            load_of_nodes = dict(measurement_result.load_of_nodes)
            load_of_instance = load_of_nodes.get(instance, 0)


            is_res_recorded: bool = self.record_measurement_result(measurement_id, instance, min_rtt)
            is_load_recorded: bool = self.record_vp_load(instance, load_of_instance)
            if is_res_recorded and is_load_recorded:
                acks.append(ark_daemon_pb2.MSM_ACK(measurement_id=measurement_id))

        
        logger.debug("grpc.SendMeasurementResultsBulk: recorded %d measurement results", len(acks))
        
        return ark_daemon_pb2.MSM_ACK_BULK(measurement_acknowledgements=acks)

    def GetMeasurementRequestsBulk(self, request, context):
        """
        A gRPC method that is used by daemon to get the measurement requests.

        :param: request: ark_daemon_pb2.MeasurementRequestsBulk - the request from the daemon.
        :param: context: grpc.ServicerContext - the context of the RPC.
        :return: ark_daemon_pb2.MSM_REQ_BULK - the measurement requests.
        """
        daemon_id = request.daemon_id

        session = self.require_ready_session(daemon_id, context)
        if session is None:
            return
        # Long-poll for the first item so idle daemons don't spin the RPC.
        try:
            target, vps, measurement_id = self.measurements_to_schedule.get(timeout=ArkPollingDriver.FIRST_MEASUREMENT_RETRIEVAL_TIMEOUT)
        except queue.Empty:
            context.abort(grpc.StatusCode.OUT_OF_RANGE, "No measurements to schedule!")
            return
        measurement_requests = []
        deferred: list[tuple[str, list[str], str]] = []

        # Try to schedule the first measurement.
        try:
            measurement_requests.append(session.schedule_measurement(
                target=target,
                vps=vps,
                measurement_id=measurement_id,
            ))
        except DaemonException:
            deferred.append((target, vps, measurement_id))

        # Drain the remaining measurements in a non-blocking way.
        while True:
            try:
                target, vps, measurement_id = self.measurements_to_schedule.get_nowait()
            except queue.Empty:
                break
            try:
                measurement_requests.append(session.schedule_measurement(
                    target=target,
                    vps=vps,
                    measurement_id=measurement_id,
                ))
            except DaemonException:
                deferred.append((target, vps, measurement_id))
                break

        # Put anything that wasnt scheduled back onto the queue so another
        # daemon (or a later poll) can pick it up again.
        for m in deferred:
            self.measurements_to_schedule.put(m)

        logger.debug(
            "%s - grpc.GetMeasurementRequestsBulk: dispatched %d measurements; deferred %d measurements",
            daemon_id, len(measurement_requests), len(deferred),
        )
        return ark_daemon_pb2.MSM_REQ_BULK(measurement_requests=measurement_requests)

    @staticmethod
    def _load_credential_from_file(filepath):
        """
        A helper function to load the credential from the file.
   
        :param: filepath: str - the path to the file that contains the credential.
        :return: bytes - the content of the file as bytes.
        :raise: FileNotFoundError: if the file does not exist.
        """

        if Path(filepath).is_absolute():
            real_path = Path(filepath).resolve()
        else:
            real_path = (Path.cwd() / filepath).resolve()

        if real_path.exists():
            with open(real_path, "rb") as f:
                return f.read()
        else:
            raise FileNotFoundError(f"File {filepath} not found.")
