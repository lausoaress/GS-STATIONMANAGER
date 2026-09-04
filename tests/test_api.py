from uuid import uuid4

import pytest

from mgm8.api.app import create_app

ISS_TLE_BODY = {
    "line1": "1 25544U 98067A   24080.53237268  .00016942  00000-0  30588-3 0  9990",
    "line2": "2 25544  51.6396 193.2647 0005852 108.9591 251.2216 15.49607995446243",
    "name": "ISS (ZARYA)",
}


def test_health_check():
    response = create_app().test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_create_pass_and_return_conflict():
    client = create_app().test_client()
    payload = {"satellite_id": str(uuid4()), "aos": "2030-01-01T10:00:00+00:00", "los": "2030-01-01T10:08:00+00:00", "center_frequency_hz": 437_200_000}
    assert client.post("/api/passes", json=payload).status_code == 201
    payload["satellite_id"] = str(uuid4())
    payload["aos"] = "2030-01-01T10:05:00+00:00"
    assert client.post("/api/passes", json=payload).status_code == 409


def test_predict_passes_returns_windows_or_503():
    client = create_app().test_client()

    response = client.post("/api/passes/predict", json={"tle": ISS_TLE_BODY, "horizon_hours": 72})

    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert isinstance(response.get_json()["passes"], list)


def test_discover_passes_schedules_and_matches_pass_list():
    app = create_app()
    if app.config["PASS_PREDICTOR"] is None:
        pytest.skip("propagation extra not installed")

    client = app.test_client()
    body = {
        "satellite_id": str(uuid4()),
        "center_frequency_hz": 437_200_000,
        "tle": ISS_TLE_BODY,
        "horizon_hours": 72,
    }

    response = client.post("/api/passes/discover", json=body)

    assert response.status_code == 201
    data = response.get_json()
    assert len(data["scheduled"]) == len(app.config["PASS_SCHEDULER"].list_passes())
    assert data["scheduled"], "ISS should yield at least one pass over 72 h"


def test_predict_passes_rejects_bad_tle():
    app = create_app()
    if app.config["PASS_PREDICTOR"] is None:
        pytest.skip("propagation extra not installed")

    response = app.test_client().post("/api/passes/predict", json={"tle": {"line1": "nope", "line2": "nope"}})

    assert response.status_code == 400


def test_schedule_and_list_telecommand():
    client = create_app().test_client()

    created = client.post("/api/telecommands", json={
        "telecommand_definition_id": str(uuid4()),
        "execute_at": "2030-01-01T10:04:00+00:00",
        "frame_hex": "40 7e 00 ff",
        "requires_approval": True,
    })
    assert created.status_code == 201
    tc_id = created.get_json()["id"]

    listed = client.get("/api/telecommands").get_json()["telecommands"]
    assert len(listed) == 1
    assert listed[0]["id"] == tc_id
    assert listed[0]["frame_bytes"] == 4
    assert listed[0]["is_ready_for_execution"] is False


def test_telecommand_guard_interval_conflict_returns_409():
    client = create_app().test_client()
    body = {"telecommand_definition_id": str(uuid4()), "execute_at": "2030-01-01T10:00:00+00:00"}
    assert client.post("/api/telecommands", json=body).status_code == 201

    body["telecommand_definition_id"] = str(uuid4())
    body["execute_at"] = "2030-01-01T10:00:03+00:00"
    conflict = client.post("/api/telecommands", json=body)
    assert conflict.status_code == 409
    assert len(conflict.get_json()["conflicting_ids"]) == 1


def test_telecommand_rejects_bad_frame_hex():
    client = create_app().test_client()
    response = client.post("/api/telecommands", json={
        "telecommand_definition_id": str(uuid4()),
        "execute_at": "2030-01-01T10:00:00+00:00",
        "frame_hex": "xyz",
    })
    assert response.status_code == 409


def test_approve_then_cancel_telecommand():
    client = create_app().test_client()
    tc_id = client.post("/api/telecommands", json={
        "telecommand_definition_id": str(uuid4()),
        "execute_at": "2030-01-01T10:00:00+00:00",
        "requires_approval": True,
    }).get_json()["id"]

    approved = client.post(f"/api/telecommands/{tc_id}/approve", json={"approved_by": "controller"})
    assert approved.status_code == 200
    assert approved.get_json()["approved_by"] == "controller"

    cancelled = client.post(f"/api/telecommands/{tc_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.get_json()["status"] == "Cancelled"


def test_approve_missing_telecommand_returns_404():
    client = create_app().test_client()
    response = client.post(f"/api/telecommands/{uuid4()}/approve", json={"approved_by": "x"})
    assert response.status_code == 404
