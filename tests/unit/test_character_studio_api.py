from fastapi.testclient import TestClient

from app.api.app import create_app


def test_character_studio_page_is_available():
    with TestClient(create_app()) as client:
        response = client.get("/character-studio")
    assert response.status_code == 200
    assert "Describe what you want" in response.text
    assert "/api/character-studio/generate" in response.text
    assert "CHARACTER_GENERATION_ERROR" in response.text
    assert "Character API unavailable" in response.text
    assert "stages complete" in response.text


def test_character_studio_rejects_too_short_description():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/character-studio/generate",
            json={"name": "Maya", "description": "too short", "mode": "master"},
        )
    assert response.status_code == 422


def test_expired_character_job_returns_terminal_state():
    with TestClient(create_app()) as client:
        response = client.get("/api/character-studio/jobs/no-longer-in-memory")

    assert response.status_code == 200
    assert response.json()["status"] == "expired"
