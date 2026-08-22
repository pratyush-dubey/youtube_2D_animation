from fastapi.testclient import TestClient


def test_character_studio_page_is_available():
    from app.api.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/character-studio")
    assert response.status_code == 200
    assert "Describe what you want" in response.text
    assert "/api/character-studio/generate" in response.text
    assert "CHARACTER_GENERATION_ERROR" in response.text
    assert "Character API unavailable" in response.text
    assert "stages complete" in response.text


def test_character_studio_rejects_too_short_description():
    from app.api.app import create_app

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/character-studio/generate",
            json={"name": "Maya", "description": "too short", "mode": "master"},
        )
    assert response.status_code == 422
