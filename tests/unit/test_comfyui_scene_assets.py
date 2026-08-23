
from PIL import Image

from app.agents.asset_agent import AssetAgent


def test_comfyui_scene_generation_converts_result_to_jpeg(tmp_path, monkeypatch):
    calls = {}

    def fake_generate(self, workflow, prompt, output, **options):
        calls.update({"workflow": workflow, "prompt": prompt, **options})
        Image.new("RGB", (768, 432), "navy").save(output, "PNG")
        return output

    monkeypatch.setattr("app.image_generation.comfyui_client.ComfyUIClient.generate", fake_generate)
    output = tmp_path / "scene_001.jpg"

    result = AssetAgent()._comfyui("1980 Bangalore street", output, 1)

    assert result == output
    assert output.is_file()
    assert Image.open(output).format == "JPEG"
    assert calls["width"] == 768
    assert calls["height"] == 432
