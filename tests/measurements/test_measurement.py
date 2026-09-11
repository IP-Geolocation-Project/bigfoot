import pytest

from bigfoot.measurements.measurement import Measurement
from bigfoot.measurements.measurement_status import MeasurementStatus


class TestClassState:

    def test_set_config_stores_the_config(self, unconfigured_measurement_class, config_stub):
        unconfigured_measurement_class.set_config(config_stub)

        assert unconfigured_measurement_class.config is config_stub

    def test_set_vantage_point_mapping_stores_a_copy(self, unconfigured_measurement_class, vp_mapping, make_vp):
        unconfigured_measurement_class.set_vantage_point_mapping(vp_mapping)
        vp_mapping["vp4"] = make_vp("vp4")

        assert set(unconfigured_measurement_class.VantagePointMapping) == {"vp1", "vp2", "vp3"}

    def test_init_requires_config(self, unconfigured_measurement_class, vp_mapping):
        unconfigured_measurement_class.set_vantage_point_mapping(vp_mapping)

        with pytest.raises(ValueError, match="config is not set"):
            unconfigured_measurement_class(target="1.2.3.4", vps=["vp1"], measurement_type="ping")

    def test_init_requires_vantage_point_mapping(self, unconfigured_measurement_class, config_stub):
        unconfigured_measurement_class.set_config(config_stub)

        with pytest.raises(ValueError, match="VantagePointMapping is not set"):
            unconfigured_measurement_class(target="1.2.3.4", vps=["vp1"], measurement_type="ping")


class TestInit:

    def test_populates_fields_from_arguments_and_config(self, measurement_class, config_stub, vp_mapping):
        measurement = measurement_class(target="1.2.3.4", vps=["vp1", "vp2"], measurement_type="ping")

        assert measurement.target == "1.2.3.4"
        assert measurement.vp_names == ["vp1", "vp2"]
        assert measurement.vps == [vp_mapping["vp1"], vp_mapping["vp2"]]
        assert measurement.measurement_type == "ping"
        assert measurement.unbounded_scheduler is False
        assert measurement.results == {}
        assert measurement.status == MeasurementStatus.CREATED
        assert measurement.runtime == 0.0
        assert measurement.failed_vps == []
        assert measurement.max_measurement_attempt_count == config_stub.MAX_MEASUREMENT_ATTEMPT_COUNT
        assert measurement.max_attempt_count == config_stub.RATE_LIMITER_MAX_ATTEMPT_COUNT

    def test_does_not_alias_the_given_vp_list(self, measurement_class):
        vps = ["vp1", "vp2"]
        measurement = measurement_class(target="1.2.3.4", vps=vps, measurement_type="ping")
        vps.append("vp3")

        assert measurement.vp_names == ["vp1", "vp2"]

    def test_unknown_vp_name_raises(self, measurement_class):
        with pytest.raises(KeyError):
            measurement_class(target="1.2.3.4", vps=["unknown-vp"], measurement_type="ping")


class TestLookupVantagePoints:

    def test_returns_vantage_points_in_the_requested_order(self, make_measurement, vp_mapping):
        measurement = make_measurement()

        assert measurement.lookup_vantage_points(["vp3", "vp1"]) == [vp_mapping["vp3"], vp_mapping["vp1"]]

    def test_returns_empty_list_for_no_names(self, make_measurement):
        assert make_measurement().lookup_vantage_points([]) == []


class TestAnalyseResults:

    def test_all_vps_reported_a_valid_rtt(self, make_measurement):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0, "vp2": 20.0}

        vps_to_attempt, status = measurement.analyse_results()

        assert vps_to_attempt == []
        assert status == MeasurementStatus.FINISHED

    def test_invalid_rtt_marks_the_measurement_as_failed(self, make_measurement, vp_mapping):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0, "vp2": -1.0}

        vps_to_attempt, status = measurement.analyse_results()

        assert vps_to_attempt == [vp_mapping["vp2"]]
        assert status == MeasurementStatus.FAILED

    def test_missing_result_marks_the_measurement_as_timeout(self, make_measurement, vp_mapping):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0}

        vps_to_attempt, status = measurement.analyse_results()

        assert vps_to_attempt == [vp_mapping["vp2"]]
        assert status == MeasurementStatus.TIMEOUT

    def test_timeout_takes_priority_over_failed(self, make_measurement):
        measurement = make_measurement(vps=["vp1", "vp2", "vp3"])
        measurement.results = {"vp1": 10.0, "vp2": -1.0}

        vps_to_attempt, status = measurement.analyse_results()

        assert {vp.name for vp in vps_to_attempt} == {"vp2", "vp3"}
        assert status == MeasurementStatus.TIMEOUT

    def test_no_results_at_all(self, make_measurement):
        measurement = make_measurement()

        vps_to_attempt, status = measurement.analyse_results()

        assert {vp.name for vp in vps_to_attempt} == {"vp1", "vp2"}
        assert status == MeasurementStatus.TIMEOUT


class TestUpdateResults:

    def test_records_a_first_valid_result(self, make_measurement):
        measurement = make_measurement()

        measurement.update_results({"vp1": 10.0})

        assert measurement.results == {"vp1": 10.0}

    def test_drops_a_first_invalid_result(self, make_measurement):
        # current behaviour: an unseen VP reporting -1.0 is not recorded at all,
        # so analyse_results reports it as a timeout rather than a failure
        measurement = make_measurement()

        measurement.update_results({"vp1": -1.0})

        assert measurement.results == {}

    def test_keeps_the_smallest_valid_rtt(self, make_measurement):
        measurement = make_measurement()

        measurement.update_results({"vp1": 20.0})
        measurement.update_results({"vp1": 10.0})
        measurement.update_results({"vp1": 30.0})

        assert measurement.results == {"vp1": 10.0}

    def test_invalid_rtt_does_not_overwrite_a_valid_one(self, make_measurement):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0}

        measurement.update_results({"vp1": -1.0})

        assert measurement.results == {"vp1": 10.0}

    def test_valid_rtt_replaces_a_recorded_invalid_one(self, make_measurement):
        measurement = make_measurement()
        measurement.results = {"vp1": -1.0}

        measurement.update_results({"vp1": 10.0})

        assert measurement.results == {"vp1": 10.0}

    def test_merges_without_dropping_earlier_results(self, make_measurement):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0}

        measurement.update_results({"vp2": 20.0})

        assert measurement.results == {"vp1": 10.0, "vp2": 20.0}

    def test_empty_update_is_a_no_op(self, make_measurement):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0}

        measurement.update_results({})

        assert measurement.results == {"vp1": 10.0}


class TestConductMeasurement:

    def test_single_attempt_when_every_vp_reports(self, make_measurement, patch_scheduler):
        schedulers = patch_scheduler(results_per_attempt=[{"vp1": 10.0, "vp2": 20.0}])
        measurement = make_measurement()

        measurement.conduct_measurement()

        assert measurement.status == MeasurementStatus.FINISHED
        assert measurement.results == {"vp1": 10.0, "vp2": 20.0}
        assert measurement.failed_vps == []
        assert measurement.runtime >= 0.0
        assert schedulers[0].acquire_calls == [["vp1", "vp2"]]
        assert schedulers[0].gather_calls == 1

    def test_scheduler_is_constructed_once_with_the_measurement_settings(self, make_measurement, patch_scheduler, config_stub):
        schedulers = patch_scheduler(results_per_attempt=[{"vp1": 10.0, "vp2": 20.0}])
        measurement = make_measurement(target="8.8.8.8", measurement_type="ping", unbounded_scheduler=True)

        measurement.conduct_measurement()

        assert len(schedulers) == 1
        assert schedulers[0].init_kwargs == {
            "target": "8.8.8.8",
            "max_attempt_count": config_stub.RATE_LIMITER_MAX_ATTEMPT_COUNT,
            "measurement_type": "ping",
            "unbounded_scheduler": True,
        }

    def test_retries_only_the_vps_that_did_not_report(self, make_measurement, patch_scheduler):
        schedulers = patch_scheduler(results_per_attempt=[{"vp1": 10.0}, {"vp2": 20.0}])
        measurement = make_measurement()

        measurement.conduct_measurement()

        assert schedulers[0].acquire_calls == [["vp1", "vp2"], ["vp2"]]
        assert measurement.status == MeasurementStatus.FINISHED
        assert measurement.results == {"vp1": 10.0, "vp2": 20.0}
        assert measurement.failed_vps == []

    def test_stops_after_the_configured_number_of_attempts(self, make_measurement, patch_scheduler, config_stub):
        schedulers = patch_scheduler(results_per_attempt=[{"vp1": 10.0}])
        measurement = make_measurement()

        measurement.conduct_measurement()

        assert len(schedulers[0].acquire_calls) == config_stub.MAX_MEASUREMENT_ATTEMPT_COUNT
        assert measurement.status == MeasurementStatus.TIMEOUT
        assert measurement.failed_vps == ["vp2"]

    def test_acquisition_failure_overrides_the_analysis_status(self, make_measurement, patch_scheduler):
        patch_scheduler(
            results_per_attempt=[{}],
            acquisition_statuses=[MeasurementStatus.UNACQUIRED],
        )
        measurement = make_measurement()

        measurement.conduct_measurement()

        assert measurement.status == MeasurementStatus.UNACQUIRED
        assert measurement.results == {}
        assert sorted(measurement.failed_vps) == ["vp1", "vp2"]

    def test_records_metadata_per_attempt(self, make_measurement, patch_scheduler):
        patch_scheduler(results_per_attempt=[{"vp1": 10.0, "vp2": 20.0}])
        measurement = make_measurement()

        measurement.conduct_measurement()

        assert list(measurement.metadata) == ["measurement_attempt_0"]
        attempt_metadata = measurement.metadata["measurement_attempt_0"]
        assert attempt_metadata["status"] == MeasurementStatus.FINISHED.value
        assert attempt_metadata["results"] == {"vp1": 10.0, "vp2": 20.0}
        assert attempt_metadata["failed_vps"] == []
        assert attempt_metadata["runtime"] >= 0.0
        assert attempt_metadata["scheduler_metadata"] == {"acquisition_attempt": 0}
        assert {"acquire_vps_and_schedule_measurements", "gather_results", "analyse_results"} <= set(attempt_metadata)


class TestToDict:

    def test_returns_the_expected_shape(self, make_measurement, patch_scheduler):
        patch_scheduler(results_per_attempt=[{"vp1": 10.0, "vp2": 20.0}])
        measurement = make_measurement()
        measurement.conduct_measurement()

        as_dict = measurement.to_dict()

        assert as_dict == {
            "target": "1.2.3.4",
            "vps": ["vp1", "vp2"],
            "measurement_type": "ping",
            "results": {"vp1": 10.0, "vp2": 20.0},
            "status": "finished",
            "runtime": measurement.runtime,
            "metadata": None,
        }

    def test_metadata_is_included_when_configured(self, make_measurement, patch_scheduler, config_stub):
        config_stub.INCLUDE_METADATA = True
        patch_scheduler(results_per_attempt=[{"vp1": 10.0, "vp2": 20.0}])
        measurement = make_measurement()
        measurement.conduct_measurement()

        as_dict = measurement.to_dict()

        assert list(as_dict["metadata"]) == ["measurement_attempt_0"]

    def test_returns_copies_of_the_mutable_fields(self, make_measurement):
        measurement = make_measurement()
        measurement.results = {"vp1": 10.0}

        as_dict = measurement.to_dict()
        as_dict["vps"].append("vp3")
        as_dict["results"]["vp2"] = 20.0

        assert measurement.vp_names == ["vp1", "vp2"]
        assert measurement.results == {"vp1": 10.0}

    def test_reflects_the_initial_state_before_the_measurement_runs(self, make_measurement):
        as_dict = make_measurement().to_dict()

        assert as_dict["status"] == MeasurementStatus.CREATED.value
        assert as_dict["results"] == {}
        assert as_dict["runtime"] == 0.0
