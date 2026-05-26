"""
L8 Verify — verify the L7 script package and produce a decision package.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L7/script_package.json

Writes:
    output/{run_id}/L8/verification_package.json
    output/{run_id}/L8/summary.json
    output/{run_id}/L8/llm_calls.jsonl

LLM: yes, for section-level sentence support verification.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR
from src.llm.prompt_loader import load_prompt_bundle
from src.pipeline.L8_verify.decision_builder import build_verification_decision
from src.pipeline.L8_verify.rule_checks import run_rule_checks
from src.pipeline.L8_verify.sentence_map import build_sentence_map
from src.pipeline.L8_verify.support_verifier import verify_sentence_support


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    layer8_cfg = _layer8_config(manifest)
    print(f"[L8] Run: {run_id}")

    script_package = _load_l7_script_package(run_id)
    print(f"[L8] Input package: {script_package.get('package_type', '')}  status={script_package.get('status', '')}")
    if script_package.get("package_type") != "roundup_script":
        raise NotImplementedError("Layer 8 v1 supports only L7 package_type='roundup_script'")

    out_dir = OUTPUT_DIR / run_id / "L8"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_calls_path = out_dir / "llm_calls.jsonl"
    llm_calls_path.write_text("", encoding="utf-8")

    prompt_bundle = load_prompt_bundle(
        "sentence_support_verifier",
        layer8_cfg["support_verifier_prompt_version"],
    )
    sentence_map = build_sentence_map(script_package)
    print(f"[L8] Sentences: {len(sentence_map)}")
    rule_checks = run_rule_checks(script_package, sentence_map, layer8_cfg)
    sentence_verifications = verify_sentence_support(
        sentence_map,
        script_package,
        layer8_cfg=layer8_cfg,
        prompt_bundle=prompt_bundle,
        log_path=llm_calls_path,
    )
    decision = build_verification_decision(
        script_package=script_package,
        sentence_map=sentence_map,
        sentence_verifications=sentence_verifications,
        rule_checks=rule_checks,
    )

    package = {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "package_type": "roundup_verification",
        "status": decision["status"],
        "decision": decision["decision"],
        "verified_script_package": script_package,
        "sentence_map": sentence_map,
        "sentence_verifications": sentence_verifications,
        "rule_checks": rule_checks,
        "support_summary": decision["support_summary"],
        "revision_package": decision["revision_package"],
        "final_publish_package": decision["final_publish_package"],
        "layer9_handoff": decision["layer9_handoff"],
    }
    summary = _build_summary(package, llm_calls_path)
    package_path = out_dir / "verification_package.json"
    summary_path = out_dir / "summary.json"
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"[L8] Status: {package['status']}  "
        f"sentences={len(sentence_verifications)}  "
        f"llm_calls={summary['llm_call_count']}"
    )
    print(f"[L8] Wrote: {package_path}")
    return package_path


def _build_summary(package: dict, llm_calls_path: Path) -> dict:
    support_status_counts = Counter(
        item.get("support_status", "unknown") for item in package.get("sentence_verifications", [])
    )
    severity_counts = Counter(item.get("severity", "unknown") for item in package.get("sentence_verifications", []))
    return {
        "run_id": package["run_id"],
        "generated_at": _iso_now(),
        "status": package["status"],
        "package_type": package["package_type"],
        "ready_for_layer_9": package.get("layer9_handoff", {}).get("ready_for_layer_9", False),
        "sentence_count": len(package.get("sentence_map", [])),
        "sentence_verification_count": len(package.get("sentence_verifications", [])),
        "support_status_counts": dict(support_status_counts),
        "severity_counts": dict(severity_counts),
        "rule_check_status_counts": package.get("rule_checks", {}).get("status_counts", {}),
        "blocking_issue_count": package.get("decision", {}).get("blocking_issue_count", 0),
        "revision_issue_count": package.get("decision", {}).get("revision_issue_count", 0),
        "llm_call_count": _count_lines(llm_calls_path),
    }


def _layer8_config(manifest: dict) -> dict:
    cfg = manifest.get("layer_8")
    if not isinstance(cfg, dict):
        raise KeyError(
            "run_manifest.json is missing layer_8 config. "
            "Rerun Layer 0 after adding L8, then rerun the required upstream layers."
        )
    required = [
        "support_verifier_model",
        "support_verifier_prompt_version",
        "verifier_worker_count",
        "duration_tolerance_ratio",
    ]
    missing = [key for key in required if key not in cfg]
    if missing:
        raise KeyError(f"run_manifest.json layer_8 missing required keys: {missing}")
    return cfg


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if run_ref == "current":
        run_id = manifest.get("run_id")
        if not run_id:
            raise KeyError("output/current_manifest.json is missing run_id")
        run_manifest_path = OUTPUT_DIR / run_id / "run_manifest.json"
        if not run_manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found: {run_manifest_path}")
        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return manifest


def _load_l7_script_package(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L7" / "script_package.json"
    if not path.exists():
        raise FileNotFoundError(f"L7 script_package.json not found: {path}")
    package = json.loads(path.read_text(encoding="utf-8"))
    if "section_scripts" not in package or "evidence_usage" not in package:
        raise KeyError("L7 script_package.json is missing section_scripts or evidence_usage")
    return package


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="current")
    args = parser.parse_args()
    run(args.run_id)
