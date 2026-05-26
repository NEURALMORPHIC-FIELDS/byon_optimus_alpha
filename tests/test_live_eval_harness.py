"""Tests for the live evaluation harness (Gate 1).

Unit-portable: verifies the harness loads and exposes the criteria. The actual live run is
performed against a running gateway and is skipped here when none is reachable."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("httpx")

_HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "live_byon_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_byon_eval", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_harness_module_loads_and_has_api():
    m = _load()
    assert hasattr(m, "Harness") and hasattr(m.Harness, "run") and hasattr(m.Harness, "research")
    assert str(m.REPORT).endswith("live_byon_eval_report.json")


def test_harness_covers_all_pass_criteria():
    import inspect
    src = inspect.getsource(_load().Harness.run)
    for gate in ["1_identity", "2_capabilities", "3_memory_state", "4_dynamics", "5_proof",
                 "6_chat_history", "7_followup", "8_memory_action", "9_vault", "10_secret",
                 "11a_teach", "12_unknown_weboff", "13_isolation"]:
        assert gate in src, f"harness missing criterion {gate}"


def test_harness_covers_adversarial_cases():
    import inspect
    m = _load()
    src = inspect.getsource(m.Harness._adversarial) + inspect.getsource(m.Harness._restart_recall_gate)
    for gate in ["adv_style_learning", "adv_stale_vault", "adv_followup_chain",
                 "adv_memory_action", "adv_contradiction_teachB", "adv_vault_intent_separation",
                 "adv_secret", "adv_web_disabled", "adv_restart_recall"]:
        assert gate in src, f"harness missing adversarial case {gate}"


def test_harness_covers_paraphrase_and_source_cases():
    import inspect
    src = inspect.getsource(_load().Harness._paraphrase_suite)
    for gate in ["pp_system_fcem_approve", "pp_system_auditor_bypass", "pp_system_level",
                 "pp_vault_auditor", "pp_vault_fcem", "pp_vault_dcortex",
                 "pp_objective_worldcup", "pp_bleed_fcem_disputed", "pp_bleed_level3_disputed"]:
        assert gate in src, f"harness missing paraphrase case {gate}"


def test_harness_covers_substrate_gates():
    import inspect
    src = inspect.getsource(_load().Harness._substrate_suite)
    for gate in ["vault_report_coherent", "no_duplicate_writer", "lock_status_clean",
                 "source_bleed_still_blocked_during_indexing", "fresh_write_immediate_recall",
                 "vault_error_report_exists_if_errors"]:
        assert gate in src, f"harness missing substrate gate {gate}"


def test_harness_covers_cycle5_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle5_suite)
    for gate in ["read_consistency_during_write", "no_false_zero_vault_count_during_write",
                 "batch_write_status", "tombstone_excluded_from_search", "compaction_dry_run",
                 "compaction_apply_if_enabled", "vault_active_vs_tombstoned_counts",
                 "source_bleed_still_blocked_after_compaction", "recent_write_buffer_still_works"]:
        assert gate in src, f"harness missing Cycle 5 gate {gate}"


def test_harness_covers_cycle6_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle6_suite)
    for gate in ["lifeloop_status_v2", "unknown_creates_pressure",
                 "repeated_unknown_creates_research_task", "secret_does_not_create_research_task",
                 "negative_feedback_increases_pressure", "consolidation_reduces_pressure",
                 "disputed_answer_triggers_consolidation_queue", "self_state_snapshots_written",
                 "pending_tasks_visible", "approve_web_required_for_web_task",
                 "lifeloop_does_not_answer_directly", "source_bleed_still_blocked",
                 "recent_write_buffer_still_works", "tombstoned_facts_still_excluded"]:
        assert gate in src, f"harness missing Cycle 6 gate {gate}"


def test_harness_covers_cycle7_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle7_suite)
    for gate in ["in_engine_consistency_status_present", "memory_only_task_auto_runs",
                 "web_task_blocked_without_permission", "approve_web_required_for_external_task",
                 "secret_task_not_created_or_run", "task_result_stored_as_candidate",
                 "pressure_reduced_after_successful_task", "failed_task_keeps_pressure",
                 "task_execution_log_written", "source_bleed_still_blocked",
                 "tombstoned_facts_still_excluded", "recent_write_buffer_still_works",
                 "LifeLoop_still_not_truth_authority", "FULL_LEVEL3_NOT_DECLARED_preserved"]:
        assert gate in src, f"harness missing Cycle 7 gate {gate}"


def test_harness_covers_cycle8_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle8_suite)
    for gate in ["task_result_creates_candidate", "repeated_task_result_reinforces_candidate",
                 "candidate_commits_after_evidence_threshold", "committed_candidate_retrievable_after_restart",
                 "contradiction_creates_disputed_challenger", "disputed_candidate_answer_is_disputed",
                 "stale_candidate_archives", "archived_candidate_not_used_for_answer",
                 "candidate_provenance_visible", "fce_influences_priority_not_truth",
                 "vault_candidate_not_objective_truth", "web_candidate_requires_verification",
                 "secret_creates_no_candidate", "source_bleed_still_blocked",
                 "tombstoned_facts_still_excluded", "LifeLoop_still_not_truth_authority",
                 "FULL_LEVEL3_NOT_DECLARED_preserved"]:
        assert gate in src, f"harness missing Cycle 8 gate {gate}"


def test_harness_covers_cycle9_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle9_suite)
    for gate in ["semantic_same_claim_merges", "semantic_contradiction_disputes",
                 "unrelated_same_topic_not_merged", "canonical_conflict_beats_vault_claim",
                 "two_same_source_not_enough_to_commit", "two_independent_sources_commit",
                 "evidence_quality_visible", "disputed_answer_explains_why",
                 "candidate_quality_blocks_weak_commit", "restart_recall_still_passes",
                 "source_bleed_still_blocked", "tombstoned_facts_still_excluded",
                 "LifeLoop_still_not_truth_authority", "FULL_LEVEL3_NOT_DECLARED_preserved"]:
        assert gate in src, f"harness missing Cycle 9 gate {gate}"


def test_harness_covers_cycle10_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle10_suite)
    for gate in ["relation_field_status_present", "entity_created_for_BYON",
                 "relation_BYON_has_component_D_Cortex", "relation_BYON_has_component_FCE_M",
                 "relation_Claude_not_truth_authority", "contradiction_relation_visible",
                 "relation_query_answers_from_relation_field", "relation_answer_includes_sources",
                 "relation_field_not_truth_authority", "temporal_relation_change_visible",
                 "source_bleed_still_blocked", "candidate_lifecycle_still_passes",
                 "tombstoned_facts_still_excluded", "restart_recall_still_passes",
                 "FULL_LEVEL3_NOT_DECLARED_preserved"]:
        assert gate in src, f"harness missing Cycle 10 gate {gate}"


def test_harness_covers_cycle11_gates():
    import inspect
    src = inspect.getsource(_load().Harness._cycle11_suite)
    for gate in ["relation_inference_from_committed_fact", "relation_inference_from_vault_content",
                 "relation_candidate_has_quote", "inferred_relation_starts_candidate",
                 "relation_reinforces_after_independent_source", "relation_commits_after_threshold",
                 "contradictory_relation_disputes", "multi_hop_path_query",
                 "disputed_hop_marks_path_disputed", "relation_proposal_to_candidate_lifecycle",
                 "relation_field_still_not_truth_authority", "source_policy_still_dominant",
                 "source_bleed_still_blocked", "candidate_lifecycle_still_passes",
                 "restart_recall_still_passes", "FULL_LEVEL3_NOT_DECLARED_preserved"]:
        assert gate in src, f"harness missing Cycle 11 gate {gate}"


def test_harness_report_has_epistemic_fields():
    import inspect
    src = inspect.getsource(_load().Harness.run)
    for field in ["pass_count", "fail_count", "skipped_count", "failure_categories",
                  "any_vault_used_incorrectly", "all_statuses_epistemically_valid",
                  "any_objective_grounded_in_user_memory", "any_cross_user_leak",
                  "source_classes_used", "vault_primary_gates", "canonical_required_gates",
                  "restart_recall", "root_cause_hint"]:
        assert field in src, f"report missing field {field}"


def test_categorize_maps_reasons():
    m = _load()
    assert m._categorize("a source contains forbidden 'vault:'")[0] == m.CAT_SOURCE_BLEED
    assert m._categorize("answer lacks ('x',)")[0] == "content"
    assert m._categorize("status=KNOWN not in (...)")[0] == "epistemic_status"
    assert m._categorize("intent=X != Y")[0] == "intent_routing"
    assert m._categorize("CROSS_USER_LEAK")[0] == m.CAT_CROSS_USER
    assert m._categorize("canonical override")[0] == m.CAT_CANONICAL_OVERRIDE
    assert m._categorize("objective fact from_user_memory")[0] == m.CAT_OBJECTIVE_FROM_USER
    assert m._categorize("memory did not survive restart")[0] == m.CAT_RESTART
    assert m._categorize("request failed: boom")[0] == "transport"


@pytest.mark.live
def test_live_eval_all_pass_if_gateway_up():
    import httpx
    m = _load()
    try:
        httpx.get("http://127.0.0.1:8090/v1/health", timeout=3)
    except Exception:
        pytest.skip("no live gateway on :8090")
    rep = m.Harness("http://127.0.0.1:8090").run()
    failed = [r["gate"] for r in rep["results"] if not r["pass"]]
    assert rep["all_pass"], f"live eval failures: {failed}"
