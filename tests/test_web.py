from uuid import uuid4

from mgm8.api.app import create_app


def test_dashboard_renders():
    response = create_app().test_client().get("/")
    assert response.status_code == 200
    assert b"Station Manager" in response.data
    assert b"Schedule Pass" in response.data
    assert b'type="submit"' in response.data
    assert b'action="/pass/create"' in response.data
    assert b"Schedule Telecommand" in response.data
    assert b'action="/telecommand/create"' in response.data


def test_schedule_and_approve_telecommand_from_web():
    app = create_app()
    client = app.test_client()

    response = client.post("/telecommand/create", data={
        "telecommand_definition_id": str(uuid4()),
        "execute_at": "2030-01-01T10:04:00+00:00",
        "frame_hex": "40 7e ff",
        "requires_approval": "on",
        "created_by": "operator",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Telecommand scheduled successfully" in response.data

    telecommand = app.config["TC_SCHEDULER"].list_telecommands()[0]
    assert telecommand.requires_approval and telecommand.approved_at is None

    approved = client.post(f"/telecommand/approve/{telecommand.id}", follow_redirects=True)
    assert approved.status_code == 200
    assert b"Telecommand approved" in approved.data


def test_web_telecommand_guard_conflict_flashes_error():
    client = create_app().test_client()
    base = {"telecommand_definition_id": str(uuid4()), "execute_at": "2030-01-01T10:00:00+00:00"}
    client.post("/telecommand/create", data=base)

    response = client.post("/telecommand/create", data={
        "telecommand_definition_id": str(uuid4()),
        "execute_at": "2030-01-01T10:00:02+00:00",
    }, follow_redirects=True)
    assert b"Telecommand rejected" in response.data


def test_create_pass_from_web_form():
    client = create_app().test_client()
    satellite_id = str(uuid4())
    response = client.post("/pass/create", data={
        "satellite_id": satellite_id,
        "aos": "2030-01-01T10:00:00+00:00",
        "los": "2030-01-01T10:08:00+00:00",
        "center_frequency_hz": "437200000",
        "auto_execute": "on",
        "created_by": "operator",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Pass scheduled successfully" in response.data


def test_cancel_pass_from_web():
    app = create_app()
    client = app.test_client()
    satellite_id = str(uuid4())
    client.post("/pass/create", data={
        "satellite_id": satellite_id,
        "aos": "2030-01-01T10:00:00+00:00",
        "los": "2030-01-01T10:08:00+00:00",
        "center_frequency_hz": "437200000",
    })
    pass_id = app.config["PASS_SCHEDULER"].list_passes()[0].id
    response = client.post(f"/pass/cancel/{pass_id}", follow_redirects=True)
    assert response.status_code == 200
    assert b"Pass cancelled" in response.data
