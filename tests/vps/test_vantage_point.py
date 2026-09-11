import uuid
from types import SimpleNamespace

import pytest

from bigfoot.vps import vantage_point as vantage_point_module
from bigfoot.vps.vantage_point import HIGH_LOAD_ARK_NODES, VantagePoint


class Clock:
    def __init__(self, now: float = 100.0):
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeLoadFetcher:
    """Scripted stand-in for the driver's get_load_of_vp callback."""

    def __init__(self, loads=(0,)):
        self.loads = list(loads)
        self.calls: list[str] = []

    def __call__(self, name: str) -> int:
        attempt = len(self.calls)
        self.calls.append(name)
        return self.loads[attempt] if attempt < len(self.loads) else self.loads[-1]


@pytest.fixture
def clock(monkeypatch):
    frozen = Clock()
    monkeypatch.setattr(vantage_point_module.time, "monotonic", frozen.monotonic)
    return frozen


@pytest.fixture
def make_vantage_point():
    def _make_vantage_point(
        name: str = "vp1",
        platform: str = "ripe",
        measurement_rate: int = 2,
        get_load_of_vp=None,
        max_load_increase: int = -1,
        metadata=None,
    ) -> VantagePoint:
        kwargs = {
            "name": name,
            "platform": platform,
            "measurement_rate": measurement_rate,
            "get_load_of_vp": get_load_of_vp or FakeLoadFetcher(),
            "max_load_increase": max_load_increase,
        }
        if metadata is not None:
            kwargs["metadata"] = metadata
        return VantagePoint(**kwargs)

    return _make_vantage_point


class TestInit:

    def test_populates_fields_from_arguments(self, make_vantage_point, clock):
        load_fetcher = FakeLoadFetcher()
        vp = make_vantage_point(
            name="ams-nl",
            platform="ark",
            measurement_rate=4,
            get_load_of_vp=load_fetcher,
            max_load_increase=8,
        )

        assert vp.name == "ams-nl"
        assert vp.platform == "ark"
        assert vp.measurement_rate == 4
        assert vp.get_load_of_vp is load_fetcher
        assert vp.max_load_increase == 8
        assert vp.remaining_capacity == 4
        assert vp.current_load == 8
        assert vp.initial_load is None
        assert isinstance(vp.metadata, SimpleNamespace)
        assert load_fetcher.calls == []

    def test_converts_dict_metadata_to_a_namespace(self, make_vantage_point):
        vp = make_vantage_point(metadata={"city": "ams"})

        assert vp.metadata.city == "ams"

    def test_rejects_metadata_that_is_not_a_dict_or_namespace(self, make_vantage_point):
        with pytest.raises(TypeError, match="metadata must be a dict"):
            make_vantage_point(metadata=["not", "valid"])

    def test_rejects_a_negative_measurement_rate(self, make_vantage_point):
        with pytest.raises(ValueError, match="Request rate can not be less than zero"):
            make_vantage_point(measurement_rate=-1)

    def test_caps_high_load_ark_nodes_at_one_measurement_per_second(self, make_vantage_point):
        name = next(iter(HIGH_LOAD_ARK_NODES))
        vp = make_vantage_point(name=name, platform="ark", measurement_rate=10)

        assert vp.measurement_rate == 1
        assert vp.remaining_capacity == 1

    def test_does_not_cap_the_same_name_on_another_platform(self, make_vantage_point):
        name = next(iter(HIGH_LOAD_ARK_NODES))
        vp = make_vantage_point(name=name, platform="ripe", measurement_rate=10)

        assert vp.measurement_rate == 10

    def test_load_hint_threshold_is_zero_when_max_load_increase_is_not_positive(self, make_vantage_point):
        assert make_vantage_point(max_load_increase=-1).load_hint_threshold == 0
        assert make_vantage_point(max_load_increase=0).load_hint_threshold == 0

    def test_load_hint_threshold_is_a_quarter_of_a_positive_max_load_increase(self, make_vantage_point):
        assert make_vantage_point(max_load_increase=5).load_hint_threshold == 2


class TestTimePassedSinceStart:

    def test_measures_from_the_start_time(self, make_vantage_point, clock):
        vp = make_vantage_point()
        clock.advance(1.5)

        assert vp.time_passed_since_start() == 1.5


class TestAcquireCapacity:

    def test_first_acquire_succeeds_and_burns_one_slot(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=2)

        assert vp.acquire(uuid.uuid4()) == 0.0
        assert vp.remaining_capacity == 1

    def test_exhausting_capacity_returns_a_wait(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=2)
        vp.acquire(uuid.uuid4())
        vp.acquire(uuid.uuid4())

        sleep_time = vp.acquire(uuid.uuid4())

        assert sleep_time == 0.5
        assert len(vp.pending_measurements_queue) == 1

    def test_capacity_refills_after_one_second(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=1)
        vp.acquire(uuid.uuid4())
        clock.advance(1.0)

        assert vp.acquire(uuid.uuid4()) == 0.0
        assert vp.remaining_capacity == 0


class TestAcquireLoad:

    def test_load_hint_is_consumed_without_fetching(self, make_vantage_point, clock):
        load_fetcher = FakeLoadFetcher()
        vp = make_vantage_point(
            measurement_rate=10,
            get_load_of_vp=load_fetcher,
            max_load_increase=2,
        )

        vp.acquire(uuid.uuid4())
        vp.acquire(uuid.uuid4())

        assert load_fetcher.calls == []
        assert vp.current_load == 0

    def test_in_range_load_refills_the_hint(self, make_vantage_point, clock):
        load_fetcher = FakeLoadFetcher(loads=[5])
        vp = make_vantage_point(
            measurement_rate=10,
            get_load_of_vp=load_fetcher,
            max_load_increase=2,
        )
        vp.acquire(uuid.uuid4())
        vp.acquire(uuid.uuid4())

        assert vp.acquire(uuid.uuid4()) == 0.0
        assert load_fetcher.calls == ["vp1"]
        assert vp.initial_load == 5
        assert vp.current_load == 1

    def test_a_failed_load_fetch_waits_at_least_60_seconds(self, make_vantage_point, clock):
        load_fetcher = FakeLoadFetcher(loads=[-1])
        vp = make_vantage_point(
            measurement_rate=10,
            get_load_of_vp=load_fetcher,
            max_load_increase=1,
        )
        vp.acquire(uuid.uuid4())

        sleep_time = vp.acquire(uuid.uuid4())

        assert 60.0 <= sleep_time < 61.0
        assert len(vp.pending_measurements_queue) == 1

    def test_load_outside_the_allowed_increase_waits_at_least_60_seconds(self, make_vantage_point, clock):
        load_fetcher = FakeLoadFetcher(loads=[5, 10])
        vp = make_vantage_point(
            measurement_rate=10,
            get_load_of_vp=load_fetcher,
            max_load_increase=1,
        )
        vp.acquire(uuid.uuid4())
        vp.acquire(uuid.uuid4())

        sleep_time = vp.acquire(uuid.uuid4())

        assert 60.0 <= sleep_time < 61.0
        assert vp.initial_load == 5


class TestAcquireQueue:

    def test_expired_pending_entries_are_discarded(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=1)
        vp.acquire(uuid.uuid4())
        vp.acquire(uuid.uuid4())
        clock.advance(vp.TIME_SLACK + 1.1)

        assert vp.acquire(uuid.uuid4()) == 0.0
        assert len(vp.pending_measurements_queue) == 0

    def test_a_queued_id_acquires_once_capacity_refills(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=1)
        waiting_id = uuid.uuid4()
        vp.acquire(uuid.uuid4())
        vp.acquire(waiting_id)
        clock.advance(1.0)

        assert vp.acquire(waiting_id) == 0.0
        assert waiting_id not in vp.pending_measurements_queue

    def test_a_new_id_is_queued_while_others_are_pending(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=1)
        vp.acquire(uuid.uuid4())
        vp.acquire(uuid.uuid4())
        clock.advance(1.0)
        new_id = uuid.uuid4()

        sleep_time = vp.acquire(new_id)

        assert sleep_time == 2.0
        assert new_id in vp.pending_measurements_queue

    def test_a_queued_id_behind_remaining_capacity_is_rescheduled_between_later_entries(self, make_vantage_point, clock):
        vp = make_vantage_point(measurement_rate=1)
        ids = [uuid.uuid4() for _ in range(5)]
        vp.acquire(ids[0])
        for waiting_id in ids[1:]:
            vp.acquire(waiting_id)
        clock.advance(1.0)

        sleep_time = vp.acquire(ids[2])

        assert sleep_time == pytest.approx(2.5 + 10e-6)
        assert ids[2] in vp.pending_measurements_queue
