"""Fast CPU tests for the off-Colab D_Cortex harness.

These do NOT run the heavy training audits (see test_full_audit.py, marked slow).
They verify importability, the chronodynamic tempo layer, the real-BYON level3
import path, and the idempotent server patch.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_version():
    import dcortex
    assert dcortex.__version__ == "10.0.0"


def test_v99_source_imports_without_running():
    mod = importlib.import_module("dcortex.v99_source")
    # module-level config object exists and honors the fast-run env (set in conftest)
    assert hasattr(mod, "C")
    assert mod.C.fast_run is True
    assert mod._v99_env_truthy("D_CORTEX_FAST_RUN_REQUESTED") is True
    assert mod._v99_env_truthy("DEFINITELY_NOT_SET_XYZ") is False


def test_chronodynamic_tempo_audit(tmp_path):
    """The v9.9 chronodynamic layer must run with no training and produce a
    verifiable temporal hash chain where stress accelerates internal tempo."""
    mod = importlib.import_module("dcortex.v99_source")
    report = mod.run_v99_chronodynamic_audit(mod.C, tmp_path)
    crit = report["criteria"]
    assert crit["temporal_hash_chain_ok"] is True
    assert crit["internal_tick_advances"] is True
    assert crit["anti_rollback_hash_present"] is True
    assert crit["stress_accelerates_internal_tempo"] is True
    assert report["stress_to_low_ratio"] >= 1.0
    assert report["passes"] is True


def test_temporal_hash_chain_detects_tampering(tmp_path):
    """Anti-rollback: mutating a committed temporal event must break verification."""
    mod = importlib.import_module("dcortex.v99_source")
    chain = mod.V99TemporalHashChain(tmp_path / "ledger.jsonl")
    state = mod.V99InternalTempoState()
    anchor = mod.V99ExternalTimeAnchor.capture()
    for i in range(5):
        state.internal_tick = i
        chain.append("tick", f"event {i}", state, anchor, strength=0.5)
    assert chain.verify()["ok"] is True
    # tamper a sealed event's hash-bound field
    chain.events[2]["internal_tick"] = 9999
    assert chain.verify()["ok"] is False


@pytest.mark.integration
def test_real_byon_level3_import(level3_available):
    if not level3_available:
        pytest.skip("level3-research checkout not staged")
    mod = importlib.import_module("dcortex.v99_source")
    bundle = mod.RealBYONLevel3Bundle(mod.C)
    bundle.import_real_modules()
    smoke = bundle.smoke_real_byon()
    assert smoke["buffer_total"] >= 1
    assert bundle.MemoryEvent is not None
    assert bundle.ZMetabolismRuntime is not None


def test_epistemic_contract_unknown_on_empty_memory():
    """v9.9.2: with no valid persistent memory the cortex must answer UNKNOWN
    (decision argmax == n_values), and only assert a value once memory holds the key."""
    import torch
    mod = importlib.import_module("dcortex.v99_source")
    cfg = mod.V92Config(fast_run=True).apply_fast()
    device = torch.device("cpu")
    model = mod.ForwardBoundMorphogeneticCortex(cfg, morphogenetic=True, plastic=True).to(device)
    mod.clear_persistent_cortex_memory(model, cfg)
    UNKNOWN = cfg.n_values  # last class in the (n_values + 1)-wide decision head

    # decision head must expose the explicit UNKNOWN class
    assert model.decision_head.net[-1].out_features == cfg.n_values + 1

    # a direct-key query with EMPTY memory -> UNKNOWN
    x = torch.zeros(1, cfg.seq_len, 8, dtype=torch.long, device=device)
    x[:, :, 0] = mod.EV_QUERY
    x[:, :, 1] = 0          # key 0
    x[:, :, 4] = 0          # rel == key -> direct query
    x[:, :, 6] = 2          # trusted hint
    x[:, :, 7] = 1          # query flag
    pred_empty = model(x)["decision"].argmax(dim=-1)
    assert (pred_empty == UNKNOWN).all(), "cortex must abstain (UNKNOWN) with no memory"

    # teach a domain so key 0 is grounded, then the same query asserts a real value
    spec = mod.build_continual_domain_spec(cfg, domain_id=5)
    mod.ingest_continual_domain_experience(model, cfg, spec, device)
    pred_known = model(x)["decision"].argmax(dim=-1)
    assert (pred_known != UNKNOWN).all(), "with grounded memory the cortex must assert a value"
    assert int(pred_known[0, -1].item()) == int(spec["values"][0]), "asserted value must match memory"


def test_server_patch_idempotent():
    """apply_server_patch must inject actions once and be a no-op on re-apply."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "orchestration"))
    integrate = importlib.import_module("integrate")
    fake = (
        "from fcem_backend import FcemBackend\n"
        "fcem: Optional[FcemBackend] = None\n"
        "    global handlers, fcem, start_time\n"
        '    logger.info(\n        "Memory backend mode: %s (FCE-M enabled=%s).", backend_mode, fcem.enabled\n    )\n'
        '    elif action == "embed_batch":\n        return await embed_texts(request)\n\n'
        '    else:\n        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")\n'
    )
    once = integrate.apply_server_patch(fake)
    assert "DCortexV99Adapter" in once
    assert "dcortex_v99_status" in once
    assert "dcortex_v99_run_audit" in once
    twice = integrate.apply_server_patch(once)
    assert twice == once  # idempotent
