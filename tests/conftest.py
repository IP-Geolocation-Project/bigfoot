import time
from types import SimpleNamespace
from typing import Optional, Sequence, Union

import pytest

from bigfoot.measurements import measurement as measurement_module
from bigfoot.measurements import measurement_scheduler as measurement_scheduler_module
from bigfoot.measurements.measurement import Measurement
from bigfoot.measurements.measurement_scheduler import MeasurementScheduler
from bigfoot.measurements.measurement_status import MeasurementStatus
from bigfoot.measurements.sub_measurement import SubMeasurement


@pytest.fixture
def config_stub() -> SimpleNamespace:
    """Minimal stand-in for Config; the real one is a singleton and would leak across tests."""
    return SimpleNamespace(
        MAX_MEASUREMENT_ATTEMPT_COUNT=2,
        RATE_LIMITER_MAX_ATTEMPT_COUNT=10,
        INCLUDE_METADATA=False,
    )


class FakeVantagePoint:
    """
    Stand-in for VantagePoint with a scripted acquire().
    Each entry of sleep_times is returned by one acquire() call; the last entry is reused once the
    script is exhausted. An exception entry is raised instead of being returned.
    """

    def __init__(
        self,
        name: str,
        platform: str = "ripe",
        sleep_times: Sequence[Union[float, Exception]] = (0.0,),
    ):
        self.name = name
        self.platform = platform
        self.sleep_times = list(sleep_times)
        self.acquire_calls: int = 0

    def acquire(self, measurement_rl_id) -> float:
        attempt = self.acquire_calls
        self.acquire_calls += 1

        sleep_time = self.sleep_times[attempt] if attempt < len(self.sleep_times) else self.sleep_times[-1]
        if isinstance(sleep_time, Exception):
            raise sleep_time
        return sleep_time


@pytest.fixture
def make_vp():
    def _make_vp(
        name: str,
        platform: str = "ripe",
        sleep_times: Sequence[Union[float, Exception]] = (0.0,),
    ) -> FakeVantagePoint:
        return FakeVantagePoint(name, platform, sleep_times)

    return _make_vp


@pytest.fixture
def vp_mapping(make_vp) -> dict[str, FakeVantagePoint]:
    return {name: make_vp(name) for name in ("vp1", "vp2", "vp3")}


@pytest.fixture
def measurement_class(config_stub, vp_mapping):
    """Measurement with its class-level state configured, restored afterwards."""
    previous_config = Measurement.config
    previous_mapping = Measurement.VantagePointMapping

    Measurement.set_config(config_stub)
    Measurement.set_vantage_point_mapping(vp_mapping)

    yield Measurement

    Measurement.config = previous_config
    Measurement.VantagePointMapping = previous_mapping


@pytest.fixture
def unconfigured_measurement_class():
    """Measurement with its class-level state cleared, restored afterwards."""
    previous_config = Measurement.config
    previous_mapping = Measurement.VantagePointMapping

    Measurement.config = None
    Measurement.VantagePointMapping = None

    yield Measurement

    Measurement.config = previous_config
    Measurement.VantagePointMapping = previous_mapping


@pytest.fixture
def make_measurement(measurement_class):
    def _make_measurement(
        target: str = "1.2.3.4",
        vps: Optional[list[str]] = None,
        measurement_type: str = "ping",
        unbounded_scheduler: bool = False,
    ) -> Measurement:
        return measurement_class(
            target=target,
            vps=["vp1", "vp2"] if vps is None else vps,
            measurement_type=measurement_type,
            unbounded_scheduler=unbounded_scheduler,
        )

    return _make_measurement


class FakeScheduler:
    """
    Scripted stand-in for MeasurementScheduler.
    Each entry of acquisition_statuses/results_per_attempt is consumed by one measurement attempt;
    the last entry is reused once the script is exhausted.
    """

    def __init__(
        self,
        acquisition_statuses: list[MeasurementStatus],
        results_per_attempt: list[dict[str, float]],
        init_kwargs: dict,
    ):
        self.acquisition_statuses = acquisition_statuses
        self.results_per_attempt = results_per_attempt
        self.init_kwargs = init_kwargs

        self.metadata: list[dict] = []
        self.acquire_calls: list[list[str]] = []
        self.gather_calls: int = 0

    @staticmethod
    def _for_attempt(script: list, attempt: int):
        return script[attempt] if attempt < len(script) else script[-1]

    def acquire_vps_and_schedule_measurements(self, vps) -> MeasurementStatus:
        attempt = len(self.acquire_calls)
        self.acquire_calls.append([vp.name for vp in vps])
        self.metadata.append({"acquisition_attempt": attempt})
        return self._for_attempt(self.acquisition_statuses, attempt)

    def gather_results(self) -> dict[str, float]:
        results = self._for_attempt(self.results_per_attempt, self.gather_calls)
        self.gather_calls += 1
        return dict(results)


@pytest.fixture
def patch_scheduler(monkeypatch):
    """Replaces MeasurementScheduler with FakeScheduler and returns the list of instances created."""

    def _patch_scheduler(
        results_per_attempt: list[dict[str, float]],
        acquisition_statuses: Optional[list[MeasurementStatus]] = None,
    ) -> list[FakeScheduler]:
        statuses = acquisition_statuses or [MeasurementStatus.ACQUIRED]
        created: list[FakeScheduler] = []

        def factory(**kwargs) -> FakeScheduler:
            scheduler = FakeScheduler(statuses, results_per_attempt, kwargs)
            created.append(scheduler)
            return scheduler

        monkeypatch.setattr(measurement_module, "MeasurementScheduler", factory)
        return created

    return _patch_scheduler


class FakeCompletedEvent:
    """Stand-in for threading.Event that records the timeouts it was waited on with."""

    def __init__(self):
        self.wait_timeouts: list[Optional[float]] = []

    def wait(self, timeout: Optional[float] = None) -> bool:
        self.wait_timeouts.append(timeout)
        return True


class FakeSubMeasurement:
    """Stand-in for SubMeasurement; never dispatches anything to a driver."""

    def __init__(self, target: str, vps: list, measurement_type: str):
        self.target = target
        self.vps = list(vps)
        self.measurement_type = measurement_type

        self.started = False
        self.results: dict[str, float] = {}
        self.metadata: dict = {"vps": [vp.name for vp in vps]}
        self.measurement_start_time = time.monotonic()
        self.completed_event = FakeCompletedEvent()

    @property
    def vp_names(self) -> list[str]:
        return [vp.name for vp in self.vps]

    def start_measurement(self) -> None:
        self.started = True


@pytest.fixture
def patch_sub_measurement(monkeypatch) -> list[FakeSubMeasurement]:
    """Replaces SubMeasurement with FakeSubMeasurement and returns the list of instances created."""
    created: list[FakeSubMeasurement] = []

    def factory(**kwargs) -> FakeSubMeasurement:
        sub_measurement = FakeSubMeasurement(**kwargs)
        created.append(sub_measurement)
        return sub_measurement

    monkeypatch.setattr(measurement_scheduler_module, "SubMeasurement", factory)
    return created


@pytest.fixture
def sleep_calls(monkeypatch) -> list[float]:
    """Records the sleeps the scheduler asks for instead of performing them."""
    calls: list[float] = []
    monkeypatch.setattr(measurement_scheduler_module.time, "sleep", calls.append)
    return calls


@pytest.fixture
def scheduler_class():
    """MeasurementScheduler with its class-level wait time cleared, restored afterwards."""
    previous_maximum_wait_time = MeasurementScheduler.MAXIMUM_WAIT_TIME
    MeasurementScheduler.MAXIMUM_WAIT_TIME = None

    yield MeasurementScheduler

    MeasurementScheduler.MAXIMUM_WAIT_TIME = previous_maximum_wait_time


@pytest.fixture
def make_scheduler(scheduler_class):
    def _make_scheduler(
        target: str = "1.2.3.4",
        max_attempt_count: int = 10,
        measurement_type: str = "ping",
        unbounded_scheduler: bool = False,
    ) -> MeasurementScheduler:
        return scheduler_class(
            target=target,
            max_attempt_count=max_attempt_count,
            measurement_type=measurement_type,
            unbounded_scheduler=unbounded_scheduler,
        )

    return _make_scheduler


@pytest.fixture
def make_acquired_scheduler(make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
    """Scheduler that acquired vp1 straight away and vp2 on the second attempt, leaving two sub-measurements."""

    def _make_acquired_scheduler(unbounded_scheduler: bool = False) -> MeasurementScheduler:
        scheduler = make_scheduler(unbounded_scheduler=unbounded_scheduler)
        scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1"), make_vp("vp2", sleep_times=[2.0, 0.0])])
        return scheduler

    return _make_acquired_scheduler


class FakeDriver:
    """
    Stand-in for AbstractDriver that records the dispatches it receives instead of measuring.
    The recorded completed_callback is only invoked when a test calls report().
    """

    def __init__(self, platform: str = "ripe", error: Optional[Exception] = None):
        self.platform = platform
        self.error = error
        self.calls: list[dict] = []

    def conduct_measurement(self, completed_callback, measurement_type: str, target: str, vps: list[str]) -> None:
        self.calls.append({
            "completed_callback": completed_callback,
            "measurement_type": measurement_type,
            "target": target,
            "vps": list(vps),
        })

        if self.error is not None:
            raise self.error

    def report(
        self,
        results: dict[str, float],
        status: MeasurementStatus = MeasurementStatus.FINISHED,
        metadata: Optional[dict] = None,
        call: int = 0,
    ) -> None:
        """Replays what a driver would report back through the callback it was dispatched with."""
        self.calls[call]["completed_callback"](results, status, metadata)


@pytest.fixture
def make_driver():
    def _make_driver(platform: str = "ripe", error: Optional[Exception] = None) -> FakeDriver:
        return FakeDriver(platform, error)

    return _make_driver


@pytest.fixture
def driver_mapping(make_driver) -> dict[str, FakeDriver]:
    return {platform: make_driver(platform) for platform in ("ripe", "ark")}


@pytest.fixture
def sub_measurement_class(driver_mapping):
    """SubMeasurement with its class-level drivers configured, restored afterwards."""
    previous_drivers = SubMeasurement.MEASUREMENT_DRIVERS

    SubMeasurement.configure_measurement_drivers(driver_mapping)

    yield SubMeasurement

    SubMeasurement.MEASUREMENT_DRIVERS = previous_drivers


@pytest.fixture
def unconfigured_sub_measurement_class():
    """SubMeasurement with its class-level drivers cleared, restored afterwards."""
    previous_drivers = SubMeasurement.MEASUREMENT_DRIVERS

    SubMeasurement.MEASUREMENT_DRIVERS = None

    yield SubMeasurement

    SubMeasurement.MEASUREMENT_DRIVERS = previous_drivers


@pytest.fixture
def make_sub_measurement(sub_measurement_class, make_vp):
    def _make_sub_measurement(
        target: str = "1.2.3.4",
        vps: Optional[list] = None,
        measurement_type: str = "ping",
    ) -> SubMeasurement:
        return sub_measurement_class(
            target=target,
            vps=[make_vp("vp1"), make_vp("vp2")] if vps is None else vps,
            measurement_type=measurement_type,
        )

    return _make_sub_measurement
