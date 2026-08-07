from uuid import uuid4

from mgm8.api.app import create_app


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
