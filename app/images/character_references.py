"""Resolve identity-safe, licensed reference portraits for researched people."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_USER_AGENT = "AIYouTubeDocumentaryBot/1.0 (identity reference resolver)"


def attach_character_references(
    sheet: dict, output_dir: Path, allowed_people: list[str]
) -> dict:
    """Keep only researched people and attach their exact lead-image references."""
    allowed = {name.casefold(): name for name in allowed_people if name.strip()}
    characters = []
    for raw in sheet.get("characters", []):
        entry = dict(raw) if isinstance(raw, dict) else {}
        requested_name = str(entry.get("name", "")).strip()
        canonical_name = allowed.get(requested_name.casefold())
        if not canonical_name:
            continue
        entry["name"] = canonical_name
        # `Path("").exists()` resolves to the current working directory, which
        # always exists and reports a nonzero directory size on Windows - an
        # unset reference_image ("" default) was silently satisfying this
        # check, marking every fresh character "verified-local-reference" and
        # skipping the real Wikipedia lookup below entirely. is_file() (not
        # exists()) plus a non-empty-string guard closes that off.
        existing_raw = str(entry.get("reference_image", "")).strip()
        existing = Path(existing_raw) if existing_raw else None
        if existing is not None and existing.is_file() and existing.stat().st_size > 1000:
            entry["identity_reference_status"] = "verified-local-reference"
            characters.append(entry)
            continue
        local_reference = _find_local_reference(canonical_name)
        if local_reference:
            entry.update({
                "reference_image": str(local_reference.resolve()),
                "reference_source_url": "user-supplied",
                "reference_file_url": "user-supplied",
                "reference_license": "user-supplied; verify usage rights",
                "identity_reference_status": "verified-user-reference",
            })
            characters.append(entry)
            continue
        reference = resolve_wikimedia_portrait(canonical_name, output_dir)
        if reference:
            entry.update(reference)
            entry["identity_reference_status"] = "verified-wikimedia-reference"
        else:
            entry["identity_reference_status"] = "missing-reference"
        characters.append(entry)
    return {"characters": characters, "settings": sheet.get("settings", [])}


def resolve_wikimedia_portrait(name: str, output_dir: Path) -> dict | None:
    """Resolve an exact Wikipedia subject page to its Wikimedia lead image."""
    page_data = _api_json(
        _WIKIPEDIA_API,
        {
            "action": "query",
            "format": "json",
            "redirects": "1",
            "titles": name,
            "prop": "pageimages|info",
            "piprop": "thumbnail|original|name",
            "pithumbsize": "1200",
            "inprop": "url",
        },
    )
    pages = list(page_data.get("query", {}).get("pages", {}).values())
    if not pages or pages[0].get("missing") is not None:
        return None
    page = pages[0]
    image_name = str(page.get("pageimage", "")).strip()
    if not image_name:
        # The pageimages extension doesn't recognize every article's infobox
        # image (template/heuristic dependent) even when one clearly exists -
        # confirmed on R. N. Kao's own article, which has a portrait but no
        # `pageimage` in this response. The page-summary REST endpoint reads
        # the lead image directly instead of relying on that extension, so
        # it succeeds here where the prop above returns nothing.
        image_name = _rest_summary_image_name(str(page.get("title", name)))
        if not image_name:
            return None

    info = _lookup_imageinfo(image_name)
    if info is None:
        # Also confirmed on R. N. Kao: this exact portrait is a non-free,
        # locally-hosted file on en.wikipedia.org, not mirrored to Commons at
        # all (typical for fair-use portraits of deceased officials, which
        # Commons' free-license policy excludes) - _lookup_imageinfo already
        # tries both, so a None here means truly neither has it.
        return None
    mime = str(info.get("mime", ""))
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    image_url = str(info.get("thumburl") or info.get("url") or "")
    if not image_url:
        return None

    target_dir = output_dir / "characters" / "references"
    target_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:50]
    digest = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:10]
    target = target_dir / f"{slug}-{digest}.jpg"
    if not target.exists() or target.stat().st_size < 1000:
        request = urllib.request.Request(image_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        if len(data) < 1000:
            return None
        from PIL import Image
        import io
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
        image.save(target, "JPEG", quality=92)

    metadata = info.get("extmetadata", {})
    return {
        "reference_image": str(target.resolve()),
        "reference_public_url": image_url,
        "reference_source_url": str(page.get("fullurl", "")),
        "reference_file_url": str(info.get("descriptionurl") or info.get("url") or ""),
        "reference_license": _metadata_value(metadata, "LicenseShortName") or "unknown",
        "reference_artist": _strip_html(_metadata_value(metadata, "Artist")),
        "reference_attribution": _strip_html(
            _metadata_value(metadata, "Credit") or _metadata_value(metadata, "Attribution")
        ),
    }


def create_reference_scene(reference_path: Path, output_path: Path) -> Path:
    """Create an identity-safe archival frame when image-to-image is unavailable."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    portrait = Image.open(reference_path).convert("RGB")
    background = ImageOps.fit(
        portrait, (1920, 1080), method=Image.Resampling.LANCZOS
    ).filter(ImageFilter.GaussianBlur(28))
    background = ImageEnhance.Color(background).enhance(0.22)
    background = ImageEnhance.Brightness(background).enhance(0.28)
    tint = Image.new("RGB", background.size, "#061610")
    background = Image.blend(background, tint, 0.55).convert("RGBA")

    framed = ImageOps.contain(portrait, (760, 820), method=Image.Resampling.LANCZOS)
    framed = ImageEnhance.Color(framed).enhance(0.55)
    card = Image.new("RGBA", (framed.width + 46, framed.height + 70), (220, 211, 187, 255))
    card.alpha_composite(framed.convert("RGBA"), (23, 22))
    shadow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    shadow_box = (960 - card.width // 2 + 25, 105, 960 + card.width // 2 + 25, 105 + card.height)
    from PIL import ImageDraw
    ImageDraw.Draw(shadow).rounded_rectangle(shadow_box, 12, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    background = Image.alpha_composite(background, shadow)
    background.alpha_composite(card, (960 - card.width // 2, 80))
    background.convert("RGB").save(output_path, "JPEG", quality=93)
    return output_path


def _rest_summary_image_name(title: str) -> str | None:
    """Read the lead-section image straight off Wikipedia's page-summary API.

    More reliable than the `pageimages` prop for articles whose infobox
    template or image isn't picked up by that extension's heuristics.
    """
    try:
        encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
        request = urllib.request.Request(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    source = str((data.get("originalimage") or data.get("thumbnail") or {}).get("source") or "")
    if not source:
        return None
    return urllib.parse.unquote(source.rsplit("/", 1)[-1].split("?", 1)[0]) or None


def _lookup_imageinfo(image_name: str) -> dict | None:
    """Look up a File: page's imageinfo, trying Commons then local Wikipedia.

    Free-licensed images live on Commons; non-free fair-use portraits (common
    for deceased officials, who Commons' free-license policy excludes) are
    hosted locally on en.wikipedia.org instead. Checking only Commons misses
    every image in that second category even when the article clearly has one.
    """
    for endpoint in (_COMMONS_API, _WIKIPEDIA_API):
        try:
            data = _api_json(
                endpoint,
                {
                    "action": "query",
                    "format": "json",
                    "titles": f"File:{image_name}",
                    "prop": "imageinfo",
                    "iiprop": "url|mime|extmetadata",
                    "iiurlwidth": "1200",
                },
            )
        except Exception:
            continue
        pages = list(data.get("query", {}).get("pages", {}).values())
        if not pages or pages[0].get("missing") is not None:
            continue
        info_list = pages[0].get("imageinfo", [])
        if info_list:
            return info_list[0]
    return None


def _api_json(endpoint: str, params: dict[str, str]) -> dict:
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def _metadata_value(metadata: dict, key: str) -> str:
    value = metadata.get(key, {})
    return str(value.get("value", "")) if isinstance(value, dict) else str(value or "")


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _find_local_reference(name: str) -> Path | None:
    from app.config.settings import settings

    directory = settings.asset_dir / "characters"
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    for extension in ("jpg", "jpeg", "png", "webp"):
        candidate = directory / f"{slug}.{extension}"
        if candidate.exists() and candidate.stat().st_size > 1000:
            return candidate
    return None
