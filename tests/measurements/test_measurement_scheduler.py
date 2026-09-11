from bigfoot.measurements.measurement_status import MeasurementStatus


class TestClassState:

    def test_set_maximum_wait_time_stores_the_value(self, scheduler_class):
        scheduler_class.set_maximum_wait_time(5.0)

        assert scheduler_class.MAXIMUM_WAIT_TIME == 5.0

    def test_minus_one_keeps_the_current_value(self, scheduler_class):
        scheduler_class.set_maximum_wait_time(5.0)
        scheduler_class.set_maximum_wait_time(-1)

        assert scheduler_class.MAXIMUM_WAIT_TIME == 5.0


class TestInit:

    def test_populates_fields_from_arguments(self, make_scheduler):
        scheduler = make_scheduler(target="8.8.8.8", max_attempt_count=3, measurement_type="ping", unbounded_scheduler=True)

        assert scheduler.target == "8.8.8.8"
        assert scheduler.max_attempt_count == 3
        assert scheduler.measurement_type == "ping"
        assert scheduler.unbounded_scheduler is True
        assert scheduler.scheduled_sub_measurements == []
        assert scheduler.metadata == []

    def test_get_timedelta_measures_from_the_start_time(self, make_scheduler):
        assert make_scheduler().get_timedelta() >= 0.0


class TestAcquireVpsAndScheduleMeasurements:

    def test_all_vps_acquired_in_a_single_attempt(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler()

        status = scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1"), make_vp("vp2")])

        assert status == MeasurementStatus.ACQUIRED
        assert len(patch_sub_measurement) == 1
        assert patch_sub_measurement[0].vp_names == ["vp1", "vp2"]
        assert patch_sub_measurement[0].started is True
        assert sleep_calls == []

    def test_sub_measurements_are_built_with_the_scheduler_settings(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler(target="8.8.8.8", measurement_type="ping")

        scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1")])

        assert patch_sub_measurement[0].target == "8.8.8.8"
        assert patch_sub_measurement[0].measurement_type == "ping"

    def test_late_vps_are_scheduled_in_a_separate_sub_measurement(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler()

        status = scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1"), make_vp("vp2", sleep_times=[2.0, 0.0])])

        assert status == MeasurementStatus.ACQUIRED
        assert [sub_measurement.vp_names for sub_measurement in patch_sub_measurement] == [["vp1"], ["vp2"]]
        assert len(scheduler.scheduled_sub_measurements) == 2

    def test_sleeps_for_the_longest_wait_time_reported_in_an_attempt(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler()

        scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1", sleep_times=[1.0, 0.0]), make_vp("vp2", sleep_times=[3.0, 0.0])])

        assert sleep_calls == [3.0]

    def test_returns_unacquired_when_no_vp_is_ever_acquired(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler(max_attempt_count=3)
        vp = make_vp("vp1", sleep_times=[1.0])

        status = scheduler.acquire_vps_and_schedule_measurements([vp])

        assert status == MeasurementStatus.UNACQUIRED
        assert vp.acquire_calls == 3
        assert patch_sub_measurement == []

    def test_attempt_budget_doubles_when_it_does_not_exceed_the_vp_count(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler(max_attempt_count=2)
        vps = [make_vp("vp1", sleep_times=[1.0]), make_vp("vp2", sleep_times=[1.0])]

        status = scheduler.acquire_vps_and_schedule_measurements(vps)

        assert status == MeasurementStatus.UNACQUIRED
        assert [vp.acquire_calls for vp in vps] == [4, 4]

    def test_a_failing_acquisition_does_not_propagate(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler(max_attempt_count=3)
        vp = make_vp("vp1", sleep_times=[RuntimeError("vp is unreachable")])

        status = scheduler.acquire_vps_and_schedule_measurements([vp])

        assert status == MeasurementStatus.UNACQUIRED
        assert vp.acquire_calls == 3

    def test_sub_measurements_of_a_previous_call_are_discarded(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler()

        scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1")])
        scheduler.acquire_vps_and_schedule_measurements([make_vp("vp2")])

        assert len(patch_sub_measurement) == 2
        assert scheduler.scheduled_sub_measurements == [patch_sub_measurement[1]]

    def test_records_metadata_per_call(self, make_scheduler, make_vp, patch_sub_measurement, sleep_calls):
        scheduler = make_scheduler()

        scheduler.acquire_vps_and_schedule_measurements([make_vp("vp1"), make_vp("vp2")])

        assert len(scheduler.metadata) == 1
        metadata = scheduler.metadata[-1]
        assert metadata["rl_id"] == str(scheduler.RL_ID)
        assert metadata["start_time"] == scheduler.start_time
        assert set(metadata["acquisition_timestamps"]) == {"vp1", "vp2"}
        assert "acquisition_attempt_0" in metadata


class TestScheduleSubMeasurement:

    def test_starts_and_records_the_sub_measurement(self, make_scheduler, make_vp, patch_sub_measurement):
        scheduler = make_scheduler()
        scheduler.last_scheduled_time = 0.0

        scheduler.schedule_sub_measurement([make_vp("vp1")])

        assert len(patch_sub_measurement) == 1
        assert patch_sub_measurement[0].started is True
        assert scheduler.scheduled_sub_measurements == [patch_sub_measurement[0]]
        assert scheduler.last_scheduled_time > 0.0


class TestGatherResults:

    def test_merges_the_results_of_every_sub_measurement(self, make_acquired_scheduler, patch_sub_measurement):
        scheduler = make_acquired_scheduler()
        patch_sub_measurement[0].results = {"vp1": 10.0}
        patch_sub_measurement[1].results = {"vp2": 20.0}

        results = scheduler.gather_results()

        assert results == {"vp1": 10.0, "vp2": 20.0}

    def test_records_the_metadata_of_every_sub_measurement(self, make_acquired_scheduler, patch_sub_measurement):
        scheduler = make_acquired_scheduler()

        scheduler.gather_results()

        metadata = scheduler.metadata[-1]
        assert metadata["sub_measurement_0"] == patch_sub_measurement[0].metadata
        assert metadata["sub_measurement_1"] == patch_sub_measurement[1].metadata
        assert "gather_results" in metadata

    def test_waits_indefinitely_when_unbounded(self, scheduler_class, make_acquired_scheduler, patch_sub_measurement):
        scheduler_class.set_maximum_wait_time(5.0)
        scheduler = make_acquired_scheduler(unbounded_scheduler=True)

        scheduler.gather_results()

        assert patch_sub_measurement[0].completed_event.wait_timeouts == [None]

    def test_waits_indefinitely_when_no_maximum_wait_time_is_set(self, make_acquired_scheduler, patch_sub_measurement):
        scheduler = make_acquired_scheduler()

        scheduler.gather_results()

        assert patch_sub_measurement[0].completed_event.wait_timeouts == [None]

    def test_waits_for_the_maximum_wait_time_minus_the_time_already_spent(self, scheduler_class, make_acquired_scheduler, patch_sub_measurement):
        scheduler_class.set_maximum_wait_time(5.0)
        scheduler = make_acquired_scheduler()

        scheduler.gather_results()

        timeout = patch_sub_measurement[0].completed_event.wait_timeouts[0]
        assert 0.0 < timeout <= 20.0
