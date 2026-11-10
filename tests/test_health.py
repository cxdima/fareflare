"""The status page reports whether checks run and how the last day went."""

from fastapi.testclient import TestClient

from fareflare.api import create_app
from fareflare.health import KEY, RETAINED_HOURS, record_run, status_report
from fareflare.store import Conflict

HOUR = 3600
NOW = 1_800_000_000 - 1_800_000_000 % HOUR + 600  # ten minutes into an hour


def component(report, name):
    return next(item for item in report["components"] if item["id"] == name)


def test_runs_are_folded_into_hourly_counters_and_old_hours_are_dropped(store):
    record_run(store, NOW - 50 * HOUR, {"collected": 9, "failed": 0})
    record_run(store, NOW - HOUR, {"collected": 2, "failed": 1, "alerts_sent": 1})
    record_run(store, NOW, {"collected": 1, "failed": 0, "failure_codes": {}})
    record_run(store, NOW + 60, {"collected": 0, "failed": 1, "failure_codes": {"timeout": 1}})

    data = store.get(KEY).data
    current = str(NOW - NOW % HOUR)
    assert data["last_worker_at"] == NOW + 60
    # The latest run's own counters stay on the record for operators.
    assert data["failure_codes"] == {"timeout": 1}
    assert data["hours"][current] == {"runs": 2, "collected": 1, "failed": 1, "alerts_sent": 0}
    assert data["hours"][str(NOW - HOUR - 600)] == {
        "runs": 1,
        "collected": 2,
        "failed": 1,
        "alerts_sent": 1,
    }
    assert len(data["hours"]) == 2
    assert all(int(start) > NOW - RETAINED_HOURS * HOUR for start in data["hours"])


def test_a_new_installation_reports_that_nothing_is_recorded_yet(store):
    report = status_report(store, NOW)

    assert report["status"] == "unknown"
    assert component(report, "website")["status"] == "operational"
    assert component(report, "price_checks") == {
        "id": "price_checks",
        "status": "unknown",
        "reason": None,
        "last_run_at": None,
        "checks": 0,
        "succeeded": 0,
    }
    assert [hour["status"] for hour in report["hours"]] == ["none"] * 24
    assert report["hours"][-1]["start"] == NOW - NOW % HOUR


def test_ordinary_failures_are_working_and_many_failures_are_trouble(store):
    for minute in range(10):
        record_run(store, NOW - 600 + minute * 60, {"collected": 1, "failed": int(minute == 0)})
    report = status_report(store, NOW)
    checks = component(report, "price_checks")
    assert (report["status"], checks["status"], checks["reason"]) == (
        "operational",
        "operational",
        None,
    )
    assert (checks["checks"], checks["succeeded"], checks["last_run_at"]) == (11, 10, NOW - 60)
    assert report["hours"][-1]["status"] == "operational"

    for minute in range(10):
        record_run(store, NOW + minute, {"collected": 0, "failed": 1})
    report = status_report(store, NOW + 60)
    checks = component(report, "price_checks")
    assert (report["status"], checks["status"], checks["reason"]) == (
        "degraded",
        "degraded",
        "failing",
    )
    assert component(report, "alerts")["status"] == "operational"

    for minute in range(200):
        record_run(store, NOW + 60 + minute, {"collected": 0, "failed": 1})
    assert status_report(store, NOW + 300)["status"] == "major"


def test_a_few_failed_checks_in_a_quiet_hour_are_not_an_incident(store):
    record_run(store, NOW, {"collected": 0, "failed": 3})
    report = status_report(store, NOW + 30)
    assert report["status"] == "operational"
    assert report["hours"][-1] == {
        "start": NOW - 600,
        "runs": 1,
        "collected": 0,
        "failed": 3,
        "alerts_sent": 0,
        "status": "operational",
    }


def test_checks_that_stopped_running_pause_alerts_too(store):
    record_run(store, NOW, {"collected": 5, "failed": 0, "alerts_sent": 2})
    assert status_report(store, NOW + 20 * 60)["status"] == "operational"

    report = status_report(store, NOW + 20 * 60 + 1)
    assert report["status"] == "major"
    assert component(report, "price_checks")["reason"] == "stalled"
    assert component(report, "alerts") == {
        "id": "alerts",
        "status": "major",
        "reason": "stalled",
        "sent": 2,
    }
    assert component(report, "website")["status"] == "operational"


def test_recording_never_fails_a_run_that_lost_a_race():
    class Racing:
        def get(self, key):
            return None

        def commit(self, documents):
            raise Conflict("changed")

    record_run(Racing(), NOW, {"collected": 1})


def test_the_status_endpoint_is_public_and_carries_counters_only(service, clock):
    client = TestClient(create_app(service, {"tenant": "k" * 40}))
    record_run(service.store, clock[0] - 30, {"collected": 4, "failed": 1, "alerts_sent": 1})

    response = client.get("/v1/status")

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "operational"
    assert report["updated_at"] == clock[0]
    assert report["window_hours"] == 24 and len(report["hours"]) == 24
    assert {item["id"] for item in report["components"]} == {"website", "price_checks", "alerts"}
    assert set(report["hours"][-1]) == {
        "start",
        "runs",
        "collected",
        "failed",
        "alerts_sent",
        "status",
    }
