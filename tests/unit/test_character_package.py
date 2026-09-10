from pathlib import Path

import pytest


def test_unconfigured_character_provider_blocks_every_image_operation(tmp_path):
    from app.characters.provider import BlockedCharacterImageProvider, CharacterGenerationBlocked

    provider = BlockedCharacterImageProvider()
    assert provider.configured is False
    with pytest.raises(CharacterGenerationBlocked, match="primitive"):
        provider.generate_master_character("Arun", tmp_path / "front.png")


def test_blocked_package_writes_specification_but_no_fake_images(tmp_path):
    from app.characters.package import CharacterPackageBuilder
    from app.characters.errors import CharacterGenerationError
    from app.characters.provider import BlockedCharacterImageProvider

    with pytest.raises(CharacterGenerationError, match="Primitive fallback is disabled"):
        CharacterPackageBuilder(tmp_path, BlockedCharacterImageProvider()).run()
    assert (tmp_path / "character_bible.json").is_file()
    assert (tmp_path / "reference_analysis.json").is_file()
    assert (tmp_path / "generation_manifest.json").is_file()
    assert not list(tmp_path.rglob("*.png"))


def test_character_bible_contains_required_identity_fields():
    from app.characters.package import default_arun_bible

    bible = default_arun_bible()
    required = {
        "character_id", "name", "age", "gender", "height", "body_type", "skin_tone",
        "face_shape", "jaw", "nose", "eyes", "eyebrows", "hair", "hair_color",
        "hair_style", "facial_hair", "body_proportions", "clothing", "shoes",
        "accessories", "color_palette", "art_style", "era", "personality",
        "default_expression", "reference_images", "master_reference",
    }
    assert required <= set(bible)


def test_custom_character_prompt_replaces_arun_identity(tmp_path):
    from app.characters.package import CharacterPackageBuilder, character_bible_from_prompt
    from app.characters.provider import BlockedCharacterImageProvider

    bible = character_bible_from_prompt(
        "Maya",
        "An adult Indian woman with shoulder-length black hair and a blue cotton sari",
    )
    builder = CharacterPackageBuilder(tmp_path, BlockedCharacterImageProvider())
    prompts = builder._prompts(bible)
    assert "Maya" in prompts["master_front"]
    assert "blue cotton sari" in prompts["master_front"]
    assert "Same exact Maya" in prompts["master:side"]


def test_character_studio_slug_blocks_path_syntax():
    from app.characters.web_jobs import safe_slug

    assert safe_slug("../../My Character\\test") == "my_character_test"
