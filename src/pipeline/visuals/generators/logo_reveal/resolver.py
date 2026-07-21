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

SIMPLE_ICON_SLUGS = {
    "siAnthropic": "anthropic",
    "siApple": "apple",
    "siClaude": "claude",
    "siGithub": "github",
    "siGoogle": "google",
    "siGooglegemini": "googlegemini",
    "siHuggingface": "huggingface",
    "siMeta": "meta",
    "siNvidia": "nvidia",
    "siOpenai": "openai",
    "siTesla": "tesla",
    "siX": "x",
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
        logo_path = _materialize_simple_icon(
            simple_icon_export,
            primary_entity=primary_entity,
            output_dir=output_dir,
        )
        return {
            "status": "resolved",
            "logo_source": "simple_icons",
            "quality_class": "simple_icon",
            "primary_entity": primary_entity,
            "logo_path": str(logo_path) if logo_path else "",
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


def _materialize_simple_icon(
    export_name: str,
    *,
    primary_entity: str,
    output_dir: Path,
) -> Path | None:
    slug = SIMPLE_ICON_SLUGS.get(export_name)
    if not slug:
        return None
    source = (
        Path(__file__).resolve().parents[2]
        / "remotion_engine"
        / "node_modules"
        / "simple-icons"
        / "icons"
        / f"{slug}.svg"
    )
    if not source.is_file():
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{slugify(primary_entity)}_simple_icon.svg"
    target.write_bytes(source.read_bytes())
    return target


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
    safe_name = escape(normalized_name)
    name_fit = ' textLength="1040" lengthAdjust="spacingAndGlyphs"' if len(normalized_name) > 18 else ""
    path = output_dir / f"{slugify(primary_entity)}_text_logo.svg"
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="420" viewBox="0 0 1200 420">
  <text x="600" y="250" fill="#171611" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="150" font-weight="700"{name_fit}>{safe_name}</text>
  <line x1="210" y1="318" x2="990" y2="318" stroke="#b64b2d" stroke-width="8"/>
</svg>
""",
        encoding="utf-8",
    )
    return path
