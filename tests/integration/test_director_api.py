from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import create_app


def test_default_page_is_single_director_workflow():
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "AI Video Director" in response.text
    assert "CREATE VIDEO" in response.text
    assert "Character Studio" not in response.text


def test_create_video_returns_project_and_job(monkeypatch):
    monkeypatch.setattr(
        "app.api.job_runner.submit_director_job",
        lambda project_id, video_request: "job-test-001",
    )
    with TestClient(create_app()) as client:
        response = client.post("/api/director/videos", json={
            "request": "Create a 60-second cinematic documentary about local history.",
            "duration_seconds": 60,
            "language": "English",
            "style": "Cinematic Documentary",
        })
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == "job-test-001"
    assert body["project_id"]
    assert body["url"].startswith("/projects/")


def test_approval_is_blocked_before_quality_passes(monkeypatch):
    monkeypatch.setattr(
        "app.api.job_runner.submit_director_job",
        lambda project_id, video_request: "job-test-002",
    )
    with TestClient(create_app()) as client:
        created = client.post("/api/director/videos", json={
            "request": "Create a short illustrated documentary about a city.",
            "duration_seconds": 60,
        }).json()
        response = client.post(
            f"/api/director/projects/{created['project_id']}/approve", json={}
        )
    assert response.status_code == 409


def test_bootstrap_failure_is_terminal_in_project_ui(monkeypatch):
    from app.api.job_store import job_store

    monkeypatch.setattr(
        "app.api.job_runner.submit_director_job",
        lambda project_id, video_request: "job-test-003",
    )
    with TestClient(create_app()) as client:
        created = client.post("/api/director/videos", json={
            "request": "Create a short documentary about Bangalore in 1980.",
            "duration_seconds": 60,
        }).json()
        job_store.create("job-test-003", created["project_id"])
        job_store.update(
            "job-test-003", status="requires_attention",
            error="Production could not be completed automatically.",
        )
        response = client.get(f"/api/director/projects/{created['project_id']}")

    assert response.status_code == 200
    assert response.json()["state"] == "REQUIRES_ATTENTION"
