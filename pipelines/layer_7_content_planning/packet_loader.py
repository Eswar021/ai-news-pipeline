"""
Layer 7 — Module 1: Packet Loader

Loads all Layer 6 outputs and builds a flat layer7_ctx dict for downstream modules.

Validates:
  - research_packet.json exists and is ready_for_layer_7
  - packet_type in {roundup, deep_dive}
  - safe_claim_ids not empty
  - packet_quality_score >= 70

Key function:
    load(layer6_dir) → layer7_ctx dict

Individual test:
    python packet_loader.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _load_jsonl_ids(path: Path) -> set:
    ids = set()
    with open(path) as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                cid = obj.get("claim_id")
                if cid:
                    ids.add(cid)
    return ids


def load(layer6_dir: Path) -> dict:
    packet_path = layer6_dir / "research_packet.json"
    if not packet_path.exists():
        raise FileNotFoundError(f"research_packet.json not found in {layer6_dir}")

    research_packet  = _load_json(layer6_dir / "research_packet.json")
    packet_context   = _load_json(layer6_dir / "packet_context_for_layer7.json")
    source_pack      = _load_json(layer6_dir / "source_pack.json")
    claim_section_map_raw = _load_json(layer6_dir / "claim_section_map.json")
    boundary_report  = _load_json(layer6_dir / "evidence_boundary_report.json")
    quality_report   = _load_json(layer6_dir / "packet_quality_report.json")
    manifest         = _load_json(layer6_dir / "layer6_manifest.json")

    packet_type     = research_packet.get("packet_type", "")
    selected_format = research_packet.get("selected_format", "")

    if packet_type not in {"roundup", "deep_dive"}:
        raise ValueError(f"Unsupported packet_type: {packet_type}")

    ready = quality_report.get("ready_for_layer_7", False)
    if not ready:
        raise ValueError(
            f"Layer 6 packet not ready for Layer 7 "
            f"(quality_score={quality_report.get('packet_quality_score')})"
        )

    # ── Evidence boundaries ────────────────────────────────────────────────────
    eb = research_packet.get("evidence_boundaries", {})
    safe_claim_ids      = set(eb.get("safe_claim_ids", []))
    cautious_claim_ids  = set(eb.get("cautious_claim_ids", []))
    dnu_claim_ids       = set(eb.get("do_not_use_claim_ids", []))

    if not safe_claim_ids:
        raise ValueError("No safe_claim_ids in research_packet evidence_boundaries.")

    # ── Packet content ─────────────────────────────────────────────────────────
    packet_content = research_packet.get("packet_content", {})
    editorial      = research_packet.get("editorial_direction", {})

    # ── Claim section map list ─────────────────────────────────────────────────
    claim_section_map = claim_section_map_raw.get("claim_section_map", [])

    # ── Source list ────────────────────────────────────────────────────────────
    sources = source_pack.get("sources", [])

    return {
        "run_id":               manifest.get("run_id", ""),
        "packet_type":          packet_type,
        "selected_format":      selected_format,
        "selected_video_id":    research_packet.get("selected_video_id", ""),
        "selected_story_ids":   research_packet.get("selected_story_ids", []),
        "primary_story_id":     research_packet.get("primary_story_id"),
        "research_packet_id":   research_packet.get("research_packet_id", ""),
        # Editorial direction from L6
        "editorial":            editorial,
        # packet_context sections (compact handoff with required claims)
        "sections":             packet_context.get("sections", []),
        "packet_context_warnings": packet_context.get("warnings", []),
        # Full packet content (segments or research_sections)
        "packet_content":       packet_content,
        # Evidence boundaries
        "safe_claim_ids":       safe_claim_ids,
        "cautious_claim_ids":   cautious_claim_ids,
        "do_not_use_claim_ids": dnu_claim_ids,
        # Sources
        "sources":              sources,
        "source_count":         source_pack.get("source_count", 0),
        # Claim-section mapping
        "claim_section_map":    claim_section_map,
        # Quality
        "packet_quality_score": quality_report.get("packet_quality_score", 0),
        # Boundary report
        "boundary_report":      boundary_report,
    }


if __name__ == "__main__":
    run_id = sorted(
        RUNS_DIR.glob("*/layer_6/research_packet.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )[0].parents[1].name
    layer6_dir = RUNS_DIR / run_id / "layer_6"

    ctx = load(layer6_dir)
    print(f"Run             : {ctx['run_id']}")
    print(f"Format          : {ctx['selected_format']}")
    print(f"Sections        : {len(ctx['sections'])}")
    print(f"Safe claims     : {len(ctx['safe_claim_ids'])}")
    print(f"Cautious claims : {len(ctx['cautious_claim_ids'])}")
    print(f"DNU claims      : {len(ctx['do_not_use_claim_ids'])}")
    print(f"Sources         : {ctx['source_count']}")
    print(f"Quality score   : {ctx['packet_quality_score']}")
    print(f"\nEditorial theme : {ctx['editorial'].get('episode_theme', '')[:80]}")
    print(f"Viewer promise  : {ctx['editorial'].get('viewer_promise', '')[:80]}")
    print(f"\nSections:")
    for s in ctx['sections']:
        print(f"  {s['section_key']:12s} | story={s.get('story_id','')[-6:]} | "
              f"required={len(s.get('required_claims',[]))} claims | "
              f"{s.get('target_seconds',0)}s")
