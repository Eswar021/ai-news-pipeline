"""
Module: channel_thesis_loader
Layer: 0 — Channel Strategy + Run Control
Purpose: Load channel_thesis.yaml and return a structured channel_strategy dict for the run manifest.
"""

from pathlib import Path
from typing import Optional
import yaml


def load_channel_thesis(thesis_path: Path) -> dict:
    """
    Loads and validates channel_thesis.yaml.

    Supports the structured format (channel: / audience: / tone: / content_boundaries:).

    Returns:
        dict with: channel_thesis_id, channel_name, content_promise, primary_audience_id,
        secondary_audiences, tone, allowed_topics, excluded_topics, style_rules, preferred_angles

    Raises:
        FileNotFoundError: if thesis_path does not exist
        ValueError: if required fields are missing
    """
    if not thesis_path.exists():
        raise FileNotFoundError(f"channel_thesis.yaml not found at: {thesis_path}")

    with open(thesis_path, "r") as f:
        raw = yaml.safe_load(f)

    channel = raw.get("channel", {})
    audience = raw.get("audience", {})
    tone_raw = raw.get("tone", {})
    content_boundaries = raw.get("content_boundaries", {})

    channel_thesis_id = channel.get("channel_id") or raw.get("channel_thesis_id")
    if not channel_thesis_id:
        raise ValueError("channel_thesis.yaml must have channel.channel_id")

    content_promise = channel.get("content_promise") or raw.get("content_promise", "")
    if isinstance(content_promise, str):
        content_promise = content_promise.strip()
    if not content_promise:
        raise ValueError("channel_thesis.yaml must have channel.content_promise")

    primary_audience_id = audience.get("primary") or raw.get("target_audience", "technical_but_accessible")

    if isinstance(tone_raw, dict):
        tone = tone_raw
    else:
        # Flat string format — convert to structured
        tone = {
            "style": "clear_analytical",
            "energy": "medium_high",
            "attitude": "skeptical_but_constructive",
            "avoid": raw.get("avoid", []),
        }

    allowed_topics = content_boundaries.get("include", [])
    excluded_topics = content_boundaries.get("exclude", raw.get("out_of_scope_topics", []))

    return {
        "channel_thesis_id": channel_thesis_id,
        "channel_name": channel.get("channel_name", "AI Signal Brief"),
        "content_promise": content_promise,
        "primary_audience_id": primary_audience_id,
        "secondary_audiences": audience.get("secondary", []),
        "tone": tone,
        "allowed_topics": allowed_topics,
        "excluded_topics": excluded_topics,
        "style_rules": raw.get("style_rules", []),
        "preferred_angles": raw.get("preferred_angles", []),
    }
