import pytest

from bigfoot.measurements.measurement_status import MeasurementStatus


class TestClassState:

    def test_configure_measurement_drivers_stores_a_copy(self, unconfigured_sub_measurement_class, make_driver):
        drivers = {"ripe": make_driver("ripe")}

        unconfigured_sub_measurement_class.configure_measurement_drivers(drivers)
        drivers["ark"] = make_driver("ark")

        assert set(unconfigured_sub_measurement_class.MEASUREMENT_DRIVERS) == {"ripe"}

    def test_init_requires_configured_drivers(self, unconfigured_sub_measurement_class, make_vp):
        with pytest.raises(ValueError, match="were not configured"):
            unconfigured_sub_measurement_class(target="1.2.3.4", vps=[make_vp("vp1")], measurement_type="ping")


class TestInit:

    def test_populates_fields_from_arguments(self, make_sub_measurement, make_vp):
        vps = [make_vp("vp1"), make_vp("vp2")]

        sub_measurement = make_sub_measurement(target="8.8.8.8", vps=vps, measurement_type="ping")

        assert sub_measurement.target == "8.8.8.8"
        assert sub_measurement.vps == vps
        assert sub_measurement.measurement_type == "ping"
        assert sub_measurement.status == MeasurementStatus.CREATED
        assert sub_measurement.results == {}
        assert sub_measurement.runtime == 0.0
        assert sub_measurement.pending_callbacks == 0
        assert sub_measurement.completed_event.is_set() is False

    def test_does_not_alias_the_given_vp_list(self, make_sub_measurement, make_vp):
        vps = [make_vp("vp1")]

        sub_measurement = make_sub_measurement(vps=vps)
        vps.append(make_vp("vp2"))

        assert [vp.name for vp in sub_measurement.vps] == ["vp1"]

    def test_records_the_initial_metadata(self, make_sub_measurement):
        sub_measurement = make_sub_measurement()

        assert sub_measurement.metadata["vps"] == ["vp1", "vp2"]
        assert sub_measurement.metadata["measurement_type"] == "ping"
        assert sub_measurement.metadata["load_of_vps"] == {}
        assert sub_measurement.metadata["start_time"] > 0.0


class TestAnalyseResults:

    def test_finished_when_every_vp_reported_a_valid_rtt(self, make_sub_measurement):
        sub_measurement = make_sub_measurement()
        sub_measurement.results = {"vp1": 10.0, "vp2": 20.0}

        assert sub_measurement.analyse_results() == MeasurementStatus.FINISHED

    def test_failed_when_a_vp_reported_an_invalid_rtt(self, make_sub_measurement):
        sub_measurement = make_sub_measurement()
        sub_measurement.results = {"vp1": 10.0, "vp2": -1.0}

        assert sub_measurement.analyse_results() == MeasurementStatus.FAILED

    def test_timeout_when_a_vp_is_missing_from_the_results(self, make_sub_measurement):
        sub_measurement = make_sub_measurement()
        sub_measurement.results = {"vp1": 10.0}

        assert sub_measurement.analyse_results() == MeasurementStatus.TIMEOUT


class TestStartMeasurement:

    def test_dispatches_one_measurement_per_driver(self, make_sub_measurement, make_vp, driver_mapping):
        sub_measurement = make_sub_measurement(vps=[make_vp("vp1"), make_vp("vp2", platform="ark")])

        sub_measurement.start_measurement()

        assert driver_mapping["ripe"].calls[0]["vps"] == ["vp1"]
        assert driver_mapping["ark"].calls[0]["vps"] == ["vp2"]
        assert sub_measurement.pending_callbacks == 2
        assert sub_measurement.status == MeasurementStatus.RUNNING
        assert sub_measurement.completed_event.is_set() is False

    def test_dispatches_with_the_sub_measurement_settings(self, make_sub_measurement, make_vp, driver_mapping):
        sub_measurement = make_sub_measurement(target="8.8.8.8", vps=[make_vp("vp1")], measurement_type="ping")

        sub_measurement.start_measurement()

        assert driver_mapping["ripe"].calls[0]["target"] == "8.8.8.8"
        assert driver_mapping["ripe"].calls[0]["measurement_type"] == "ping"
        assert driver_mapping["ripe"].calls[0]["completed_callback"] == sub_measurement.callback

    def test_vps_of_the_same_platform_share_a_single_dispatch(self, make_sub_measurement, driver_mapping):
        sub_measurement = make_sub_measurement()

        sub_measurement.start_measurement()

        assert len(driver_mapping["ripe"].calls) == 1
        assert driver_mapping["ripe"].calls[0]["vps"] == ["vp1", "vp2"]
        assert sub_measurement.pending_callbacks == 1

    def test_vps_without_a_driver_complete_immediately(self, make_sub_measurement, make_vp, driver_mapping):
        # current behaviour: an unroutable VP reports no results, so the analysis calls it a timeout
        sub_measurement = make_sub_measurement(vps=[make_vp("vp1", platform="unknown")])

        sub_measurement.start_measurement()

        assert driver_mapping["ripe"].calls == []
        assert sub_measurement.completed_event.is_set() is True
        assert sub_measurement.status == MeasurementStatus.TIMEOUT

    def test_vps_without_a_driver_do_not_complete_the_whole_sub_measurement(self, make_sub_measurement, make_vp, driver_mapping):
        sub_measurement = make_sub_measurement(vps=[make_vp("vp1"), make_vp("vp2", platform="unknown")])

        sub_measurement.start_measurement()

        assert driver_mapping["ripe"].calls[0]["vps"] == ["vp1"]
        assert sub_measurement.pending_callbacks == 1
        assert sub_measurement.completed_event.is_set() is False

    def test_a_failing_driver_does_not_propagate(self, make_sub_measurement, make_vp, driver_mapping):
        driver_mapping["ripe"].error = RuntimeError("driver is unreachable")
        sub_measurement = make_sub_measurement(vps=[make_vp("vp1")])

        sub_measurement.start_measurement()

        assert sub_measurement.completed_event.is_set() is True
        assert sub_measurement.results == {}


class TestCallback:

    def test_the_last_driver_to_report_completes_the_sub_measurement(self, make_sub_measurement, driver_mapping):
        sub_measurement = make_sub_measurement()
        sub_measurement.start_measurement()

        driver_mapping["ripe"].report({"vp1": 10.0, "vp2": 20.0})

        assert sub_measurement.status == MeasurementStatus.FINISHED
        assert sub_measurement.results == {"vp1": 10.0, "vp2": 20.0}
        assert sub_measurement.runtime >= 0.0
        assert sub_measurement.completed_event.is_set() is True

    def test_results_are_merged_and_completion_waits_for_every_driver(self, make_sub_measurement, make_vp, driver_mapping):
        sub_measurement = make_sub_measurement(vps=[make_vp("vp1"), make_vp("vp2", platform="ark")])
        sub_measurement.start_measurement()

        driver_mapping["ripe"].report({"vp1": 10.0})

        assert sub_measurement.results == {"vp1": 10.0}
        assert sub_measurement.completed_event.is_set() is False

        driver_mapping["ark"].report({"vp2": 20.0})

        assert sub_measurement.results == {"vp1": 10.0, "vp2": 20.0}
        assert sub_measurement.status == MeasurementStatus.FINISHED
        assert sub_measurement.completed_event.is_set() is True

    def test_the_reported_status_does_not_override_the_analysis(self, make_sub_measurement, driver_mapping):
        sub_measurement = make_sub_measurement()
        sub_measurement.start_measurement()

        driver_mapping["ripe"].report({"vp1": 10.0}, status=MeasurementStatus.FINISHED)

        assert sub_measurement.status == MeasurementStatus.TIMEOUT

    def test_records_the_completion_metadata(self, make_sub_measurement, driver_mapping):
        sub_measurement = make_sub_measurement()
        sub_measurement.start_measurement()

        driver_mapping["ripe"].report({"vp1": 10.0, "vp2": 20.0})

        assert sub_measurement.metadata["status"] == MeasurementStatus.FINISHED.value
        assert sub_measurement.metadata["results"] == {"vp1": 10.0, "vp2": 20.0}
        assert sub_measurement.metadata["runtime"] == sub_measurement.runtime
        assert sub_measurement.metadata["end_time"] > 0.0

    def test_records_driver_metadata_under_its_measurement_id(self, make_sub_measurement, driver_mapping):
        sub_measurement = make_sub_measurement()
        sub_measurement.start_measurement()

        driver_mapping["ripe"].report(
            {"vp1": 10.0, "vp2": 20.0},
            metadata={
                "measurement_id": "measurement-1",
                "runtimes": {"dispatch": 0.5},
                "load_of_vps": {"vp1": 3},
            },
        )

        assert sub_measurement.metadata["measurement-1"] == {"dispatch": 0.5}
        assert sub_measurement.metadata["load_of_vps"] == {"vp1": 3}

    def test_empty_driver_metadata_is_ignored(self, make_sub_measurement, driver_mapping):
        sub_measurement = make_sub_measurement()
        sub_measurement.start_measurement()

        driver_mapping["ripe"].report({"vp1": 10.0, "vp2": 20.0}, metadata={})

        assert sub_measurement.metadata["load_of_vps"] == {}
        assert sub_measurement.status == MeasurementStatus.FINISHED
