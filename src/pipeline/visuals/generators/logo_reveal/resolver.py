from __future__ import annotations

from functools import lru_cache
from html import escape
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ...common import clean_text, slugify


SIMPLE_ICON_ALIASES = {
    "anthropic": "siAnthropic",
    "apple": "siApple",
    "claude": "siClaude",
    "chatgpt": "siOpenai",
    "gemini": "siGooglegemini",
    "github": "siGithub",
    "google": "siGoogle",
    "google gemini": "siGooglegemini",
    "hugging face": "siHuggingface",
    "ibm": "siIbm",
    "meta": "siMeta",
    "nvidia": "siNvidia",
    "openai": "siOpenai",
    "openai chatgpt": "siOpenai",
    "oracle": "siOracle",
    "tesla": "siTesla",
    "xai": "siX",
}


def resolve_logo_asset(
    *,
    scene: dict[str, Any],
    output_dir: Path,
    local_logo_dir: Path | None = None,
    simple_icons_enabled: bool = True,
    favicon_fallback_enabled: bool = False,
    text_fallback_enabled: bool = True,
    favicon_timeout_seconds: int = 10,
) -> dict[str, Any]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    primary_entity = clean_text(payload.get("primary_entity", ""))
    if not primary_entity:
        return {
            "status": "failed",
            "logo_source": "unresolved",
            "quality_class": "unresolved",
            "primary_entity": "",
            "logo_path": "",
            "simple_icon_export": "",
            "fallback_svg_path": "",
            "error": "logo_reveal_scene.payload.primary_entity is required",
        }
    local_logo = _local_logo_path(primary_entity, local_logo_dir)
    if local_logo:
        return {
            "status": "resolved",
            "logo_source": "local_override",
            "quality_class": "verified_logo",
            "primary_entity": primary_entity,
            "logo_path": str(local_logo),
            "simple_icon_export": "",
            "fallback_svg_path": "",
        }

    simple_icon_export = simple_icon_export_for(primary_entity) if simple_icons_enabled else None
    if simple_icon_export:
        return {
            "status": "resolved",
            "logo_source": "simple_icons",
            "quality_class": "simple_icon",
            "primary_entity": primary_entity,
            "logo_path": "",
            "simple_icon_export": simple_icon_export,
            "fallback_svg_path": "",
        }

    favicon_path = None
    if favicon_fallback_enabled:
        favicon_path = _download_domain_favicon(
            clean_text(payload.get("favicon_domain_url", "")),
            primary_entity=primary_entity,
            output_dir=output_dir,
            timeout_seconds=favicon_timeout_seconds,
        )
    if favicon_path:
        return {
            "status": "resolved",
            "logo_source": "domain_favicon",
            "quality_class": "domain_favicon",
            "primary_entity": primary_entity,
            "logo_path": str(favicon_path),
            "simple_icon_export": "",
            "fallback_svg_path": "",
        }

    if text_fallback_enabled:
        fallback_svg_path = _write_text_logo_svg(primary_entity, output_dir)
        return {
            "status": "fallback",
            "logo_source": "text_fallback",
            "quality_class": "text_identity_fallback",
            "primary_entity": primary_entity,
            "logo_path": "",
            "simple_icon_export": "",
            "fallback_svg_path": str(fallback_svg_path),
        }
    return {
        "status": "failed",
        "logo_source": "unresolved",
        "quality_class": "unresolved",
        "primary_entity": primary_entity,
        "logo_path": "",
        "simple_icon_export": "",
        "fallback_svg_path": "",
        "error": "No configured logo source resolved this entity.",
    }


def simple_icon_export_for(primary_entity: str) -> str | None:
    normalized = primary_entity.lower().strip()
    export_name = SIMPLE_ICON_ALIASES.get(normalized)
    if not export_name or export_name not in _available_simple_icon_exports():
        return None
    return export_name


@lru_cache(maxsize=1)
def _available_simple_icon_exports() -> frozenset[str]:
    index_path = (
        Path(__file__).resolve().parents[2]
        / "remotion_engine"
        / "node_modules"
        / "simple-icons"
        / "index.js"
    )
    if not index_path.exists():
        return frozenset()
    source = index_path.read_text(encoding="utf-8", errors="ignore")
    return frozenset(re.findall(r"\b(si[A-Za-z0-9]+):\{", source))


def _download_domain_favicon(
    page_url: str,
    *,
    primary_entity: str,
    output_dir: Path,
    timeout_seconds: int,
) -> Path | None:
    parsed = urlparse(page_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    favicon_url = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    try:
        request = Request(
            favicon_url,
            headers={"User-Agent": "AIContentCreation/2.0 (logo resolver)"},
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            data = response.read(2_000_001)
            content_type = clean_text(response.headers.get("Content-Type", "")).lower()
        if not data or len(data) > 2_000_000:
            return None
        if content_type and "image" not in content_type and not data.startswith((b"\x00\x00\x01\x00", b"\x89PNG", b"GIF8", b"\xff\xd8")):
            return None
    except Exception:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{slugify(primary_entity)}_favicon.ico"
    path.write_bytes(data)
    return path


def _local_logo_path(primary_entity: str, local_logo_dir: Path | None) -> Path | None:
    if not local_logo_dir or not local_logo_dir.exists():
        return None
    slug = slugify(primary_entity)
    for extension in ("svg", "png", "jpg", "jpeg", "webp"):
        candidate = local_logo_dir / f"{slug}.{extension}"
        if candidate.exists():
            return candidate
    return None


def _write_text_logo_svg(primary_entity: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_name = clean_text(primary_entity)
    initials = "".join(part[0] for part in normalized_name.split() if part)[:3].upper()
    if not initials:
        initials = next((character.upper() for character in normalized_name if character.isalnum()), "?")
    safe_name = escape(normalized_name)
    name_fit = ' textLength="400" lengthAdjust="spacingAndGlyphs"' if len(normalized_name) > 18 else ""
    path = output_dir / f"{slugify(primary_entity)}_text_logo.svg"
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="118" fill="#07101a"/>
  <circle cx="256" cy="256" r="196" fill="#101d2d" stroke="#63d7ff" stroke-width="10"/>
  <text x="256" y="246" fill="#f7fbff" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="128" font-weight="900">{initials}</text>
  <text x="256" y="326" fill="#9fb2c7" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="30" font-weight="700"{name_fit}>{safe_name}</text>
</svg>
""",
        encoding="utf-8",
    )
    return path
