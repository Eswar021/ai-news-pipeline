from __future__ import annotations

from pathlib import Path
from typing import Any

from ...common import clean_text, slugify


SIMPLE_ICON_ALIASES = {
    "amazon": "siAmazon",
    "amazon bedrock": "siAmazon",
    "amazon web services": "siAmazon",
    "anthropic": "siAnthropic",
    "apple": "siApple",
    "aws": "siAmazon",
    "bedrock": "siAmazon",
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
) -> dict[str, Any]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    primary_entity = clean_text(payload.get("primary_entity", "")) or "AI"
    local_logo = _local_logo_path(primary_entity, local_logo_dir)
    if local_logo:
        return {
            "status": "resolved",
            "logo_source": "local_override",
            "primary_entity": primary_entity,
            "logo_path": str(local_logo),
            "simple_icon_export": "",
            "fallback_svg_path": "",
        }

    simple_icon_export = _simple_icon_for(primary_entity)
    fallback_svg_path = _write_text_logo_svg(primary_entity, output_dir)
    return {
        "status": "resolved",
        "logo_source": "simple_icons" if simple_icon_export else "text_fallback",
        "primary_entity": primary_entity,
        "logo_path": "",
        "simple_icon_export": simple_icon_export or "",
        "fallback_svg_path": str(fallback_svg_path),
    }


def _simple_icon_for(primary_entity: str) -> str | None:
    normalized = primary_entity.lower().strip()
    if normalized in SIMPLE_ICON_ALIASES:
        return SIMPLE_ICON_ALIASES[normalized]
    for alias, export_name in SIMPLE_ICON_ALIASES.items():
        if alias in normalized:
            return export_name
    return None


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
    initials = "".join(part[0] for part in primary_entity.split() if part)[:3].upper() or "AI"
    safe_name = clean_text(primary_entity).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    path = output_dir / f"{slugify(primary_entity)}_text_logo.svg"
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="118" fill="#07101a"/>
  <circle cx="256" cy="256" r="196" fill="#101d2d" stroke="#63d7ff" stroke-width="10"/>
  <text x="256" y="246" fill="#f7fbff" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="128" font-weight="900">{initials}</text>
  <text x="256" y="326" fill="#9fb2c7" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="30" font-weight="700">{safe_name[:18]}</text>
</svg>
""",
        encoding="utf-8",
    )
    return path
