"""
Module: quality_policy_loader
Layer: 0 — Channel Strategy + Run Control
Purpose: Load quality_rules.yaml and assemble the active quality policy for this run.
         This is where hallucination control rules are declared — all downstream layers enforce them.
"""

from pathlib import Path
import yaml


def load_quality_policy(
    quality_rules_path: Path,
    eligible_formats: list,
) -> dict:
    """
    Loads and normalizes the quality policy from quality_rules.yaml.

    Applies stricter rules when deep_dive, comparison, or evergreen is eligible
    (these formats require higher evidence standards than roundup).

    Returns:
        dict with: quality_policy_id, source_rules, claim_rules, language_rules,
        script_rules, risk_rules, memory_rules

    Raises:
        FileNotFoundError: if quality_rules_path does not exist
    """
    if not quality_rules_path.exists():
        raise FileNotFoundError(f"quality_rules.yaml not found at: {quality_rules_path}")

    with open(quality_rules_path, "r") as f:
        raw = yaml.safe_load(f)

    evidence_rules = raw.get("evidence_rules", {})
    language_rules = raw.get("language_rules", {})
    verification_rules = raw.get("verification_rules", {})
    memory_rules = raw.get("memory_rules", {})

    # Stricter independent-source requirement when high-evidence formats are eligible
    high_evidence_formats = {"deep_dive", "comparison", "evergreen"}
    requires_strict = any(f in high_evidence_formats for f in eligible_formats)

    return {
        "quality_policy_id": "evidence_first_v1",
        "source_rules": {
            "allow_community_sources_as_primary_truth": not evidence_rules.get(
                "community_signals_cannot_be_primary_truth", True
            ),
            "require_primary_source_for_deep_dive": evidence_rules.get(
                "require_source_span_for_every_claim", True
            ),
            "require_independent_source_for_major_claim": requires_strict,
            "min_trust_tier_for_primary_claim": evidence_rules.get(
                "min_trust_tier_for_primary_claim", 2
            ),
            "max_community_claim_ratio": evidence_rules.get("max_community_claim_ratio", 0.0),
        },
        "claim_rules": {
            "every_claim_requires_source_span": evidence_rules.get(
                "require_source_span_for_every_claim", True
            ),
            "unsupported_claim_action": "remove_or_flag",
        },
        "language_rules": {
            "uncertain_claims_require_hedging": language_rules.get(
                "uncertain_claims_require_hedging", True
            ),
            "quotes_must_be_attributed": language_rules.get("quotes_must_be_attributed", True),
            "company_only_claims_require_qualifier": language_rules.get(
                "company_only_claims_require_qualifier", True
            ),
        },
        "script_rules": {
            "require_sentence_source_mapping": verification_rules.get(
                "require_sentence_source_map", True
            ),
            "require_sentence_claim_mapping": verification_rules.get(
                "require_sentence_claim_map", True
            ),
            "allow_unsourced_fact": False,
            "allow_unsourced_opinion": True,
        },
        "risk_rules": {
            "block_unsupported_accusations": verification_rules.get(
                "block_scripts_with_unsupported_facts", True
            ),
            "block_rejected_claim_leakage": verification_rules.get(
                "block_rejected_claim_leakage", True
            ),
            "title_must_be_evidence_safe": verification_rules.get(
                "title_must_be_evidence_safe", True
            ),
        },
        "memory_rules": {
            "only_approved_scripts_update_memory": memory_rules.get(
                "only_approved_scripts_update_memory", True
            ),
            "rejected_claims_never_enter_knowledge_base": memory_rules.get(
                "rejected_claims_never_enter_knowledge_base", True
            ),
            "caution_markers_preserved_in_ledger": memory_rules.get(
                "caution_markers_preserved_in_ledger", True
            ),
        },
    }
