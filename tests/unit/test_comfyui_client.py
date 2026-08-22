import pytest


def test_wait_surfaces_comfyui_execution_error(monkeypatch):
    from app.image_generation.comfyui_client import ComfyUIClient, ComfyUIError

    client = ComfyUIClient(timeout=1)
    monkeypatch.setattr(
        client,
        "history",
        lambda prompt_id: {
            prompt_id: {
                "status": {
                    "status_str": "error",
                    "messages": [["execution_error", {"node_id": "4", "exception_message": "Checkpoint not found"}]],
                }
            }
        },
    )
    with pytest.raises(ComfyUIError, match="Checkpoint not found"):
        client.wait("prompt-1", poll_seconds=0)


def test_generation_timeout_uses_new_environment_name(monkeypatch):
    from app.characters.provider import ComfyUICharacterProvider

    monkeypatch.setenv("COMFYUI_GENERATION_TIMEOUT_SECONDS", "777")
    monkeypatch.setenv("COMFYUI_TIMEOUT_SECONDS", "123")
    provider = ComfyUICharacterProvider("http://127.0.0.1:8188")
    assert provider.client.timeout == 777
