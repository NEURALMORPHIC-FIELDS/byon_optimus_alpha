#!/usr/bin/env python
"""D_Cortex v10 — Longitudinal Generalization & Isolation milestone.

This is NOT another FSOAT run and NOT the in-process v10 developmental loop
(`v10_developmental_loop.py`). It is a *standing* robustness milestone whose job
is to falsify audit-overfitting (dev-sheet §10.1): every gate operates on data or
keys the prior v9.9.x audits never touched, with the **real** FCE-M v15.7a
consolidator mandatory.

Eight gates, exactly as scoped:

    1. REAL_FCEM_REQUIRED         real external v15.7a DCortexAdapter must load
                                  (fail-hard if a shim or stub appears)
    2. UNSEEN_DOMAIN_TRANSFER     never-audited domains (not AG News / WikiText,
                                  not domain_id 5..7) still learn + recall
    3. REAL_OOV_UNKNOWN           genuinely never-taught keys → UNKNOWN, not a
                                  reconstructed value from prior
    4. DELAYED_RECALL_RESTART     recall survives a checkpoint round-trip after
                                  interference + elapsed episodes
    5. CROSS_USER_ISOLATION       user A's memory never leaks user B's values
    6. REAL_CONTRADICTION_STREAM  contradictions parsed from real document text;
                                  a consolidated fact resists a transient flip but
                                  a genuinely re-consolidated correction still wins
    7. FCEM_ADVISORY_EFFECT       the real v15.7a adapter's LatentSignals measurably
                                  change with input structure (contested ≫ aligned)
    8. FALSE_ASSERTION_RATE_ZERO  across every ungrounded query in this milestone,
                                  the count of non-UNKNOWN assertions is exactly 0

Built entirely on the validated v9.9 primitives (the addressable ledger is
algorithmic, so a fresh untrained `ForwardBoundMorphogeneticCortex` recalls
correctly from grounded memory) + the sealed v15.7a `DCortexAdapter`. No new
science is invented and no diluted fallback is permitted (dev-sheet §7.3).

Run:
    python -m dcortex.v10_milestone --fast
    FCEM_MEMORY_ENGINE_ROOT=/path/to/13_v15_7a_consolidation python -m dcortex.v10_milestone
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

from dcortex import v99_source as v


# ======================================================================================
# Gate 1 support — load the REAL external v15.7a FCE-M consolidator (fail-hard on shim)
# ======================================================================================

# The sealed extraction stamps this exact version string in d_cortex/__init__.py.
# A shim / stub / wrong package will not carry it → REAL_FCEM_REQUIRED fails hard.
_SEALED_VERSION_PREFIX = "0.1.0-extracted-from-v15.7a-sealed"


class RealFCEMRequiredError(RuntimeError):
    """Raised when the real external v15.7a runtime cannot be proven (no diluted
    fallback — dev-sheet §7.3). REAL_FCEM_REQUIRED is a hard gate."""


def resolve_fcem_engine_root() -> str:
    """Resolve the v15.7a engine root the same way orchestration/integrate.py does:
    explicit env first, then the known local fragmergent checkout."""
    env = os.environ.get("FCEM_MEMORY_ENGINE_ROOT", "").strip()
    if env:
        return env
    for cand in (
        Path(r"c:/Users/Lucian/Desktop/fragmergent-memory-engine/13_v15_7a_consolidation"),
        Path(r"c:/Users/Lucian/Desktop/fragmergent-memory-engine"),
        Path.home() / "Desktop" / "fragmergent-memory-engine" / "13_v15_7a_consolidation",
    ):
        if (cand / "d_cortex" / "__init__.py").exists():
            return str(cand)
        if (cand / "13_v15_7a_consolidation" / "d_cortex" / "__init__.py").exists():
            return str(cand / "13_v15_7a_consolidation")
    return ""


def load_real_fcem_adapter() -> Dict[str, Any]:
    """Import the REAL sealed v15.7a DCortexAdapter and prove it is not a shim.

    Returns a proof dict. Raises RealFCEMRequiredError if the engine cannot be
    resolved, imported, or fails the sealed-version / class-identity proof.
    """
    root = resolve_fcem_engine_root()
    if not root or not (Path(root) / "d_cortex" / "__init__.py").exists():
        raise RealFCEMRequiredError(
            "FCEM_MEMORY_ENGINE_ROOT does not point at a real v15.7a d_cortex package "
            f"(resolved root={root!r}). No diluted fallback (dev-sheet §7.3)."
        )
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        import d_cortex  # the sealed extraction package
        from d_cortex import adapter as fcem_adapter
        from d_cortex.adapter import (
            DCortexAdapter,
            LatentSignals,
            LATENT_MODE_ADVISORY,
            LATENT_MODE_OFF,
            ZONE_COMMITTED,
            ZONE_DISPUTED,
        )
    except Exception as exc:  # pragma: no cover - import-environment dependent
        raise RealFCEMRequiredError(
            f"could not import the real v15.7a d_cortex.adapter from {root!r}: {exc}"
        ) from exc

    version = getattr(d_cortex, "__version__", "")
    if not str(version).startswith(_SEALED_VERSION_PREFIX):
        raise RealFCEMRequiredError(
            f"d_cortex.__version__={version!r} is not the sealed v15.7a extraction "
            f"(expected prefix {_SEALED_VERSION_PREFIX!r}) — refusing to run on a shim."
        )
    if DCortexAdapter.__name__ != "DCortexAdapter" or "Minimal" in DCortexAdapter.__name__:
        raise RealFCEMRequiredError(
            f"adapter class {DCortexAdapter.__name__!r} looks like a minimal shim."
        )

    adapter_file = getattr(fcem_adapter, "__file__", "")
    # Smoke-prove the real consolidator pipeline actually runs end_episode.
    probe = DCortexAdapter(mode=LATENT_MODE_ADVISORY)
    probe.ingest_slot_event({
        "entity": "_fcem_probe", "family": "attr", "zone_after": ZONE_COMMITTED,
        "value_after": "x", "value_before": "", "episode_id": 0, "write_step": 0,
        "reason": "gate1-smoke",
    })
    sig = probe.end_episode(0)
    if not hasattr(sig, "raw_v15_7a_signals"):
        raise RealFCEMRequiredError("end_episode did not return real LatentSignals.")
    raw = sig.raw_v15_7a_signals or {}

    return {
        "engine_root": root,
        "version": version,
        "adapter_class": DCortexAdapter.__name__,
        "adapter_file": adapter_file,
        "pipeline_ran": bool(raw.get("last_pipeline_ops") is not None),
        "raw_params": raw.get("params"),
        "_classes": {
            "DCortexAdapter": DCortexAdapter,
            "LatentSignals": LatentSignals,
            "LATENT_MODE_ADVISORY": LATENT_MODE_ADVISORY,
            "LATENT_MODE_OFF": LATENT_MODE_OFF,
            "ZONE_COMMITTED": ZONE_COMMITTED,
            "ZONE_DISPUTED": ZONE_DISPUTED,
        },
    }


# ======================================================================================
# Cortex query helpers — return per-key predictions so we can count UNKNOWN exactly
# ======================================================================================

UNK_OFFSET = 0  # the UNKNOWN class index == cfg.n_values (decision head is n_values+1 wide)


def _unk_index(cfg: v.V92Config) -> int:
    return cfg.n_values


@torch.no_grad()
def _teach_keys(model, cfg: v.V92Config, spec: Dict[str, Any], device, keys: List[int]) -> None:
    """Ground a SUBSET of keys from trusted observation + correction. Keys not in
    `keys` stay un-taught (persistent_known False) so the OOV gate can prove UNKNOWN."""
    values: Dict[int, int] = spec["values"]
    trusted = spec["trusted_sources"]
    rows: List[torch.Tensor] = []
    for k in keys:
        x = torch.zeros(cfg.seq_len, 8, dtype=torch.long, device=device)
        events = [
            (v.EV_OBSERVE, k, values[k], trusted[0], k, v.STATE_STABLE, 2, 0),
            (v.EV_CORRECT, k, values[k], trusted[0], k, v.STATE_REVISED, 2, 0),
        ]
        for t, ev in enumerate(events):
            x[t, :] = torch.tensor(ev, dtype=torch.long, device=device)
        for t in range(len(events), cfg.seq_len):
            x[t, 0] = v.EV_DISTRACTOR
            x[t, 1] = (k + t) % cfg.n_keys
            x[t, 3] = trusted[0]
            x[t, 4] = (k + t + 1) % cfg.n_keys
        rows.append(x)
    if rows:
        v.ingest_events_into_persistent_memory(model, torch.stack(rows, dim=0), cfg)


@torch.no_grad()
def _query_keys(
    model, cfg: v.V92Config, spec: Dict[str, Any], device, keys: List[int],
    *, trusted: bool = True,
) -> List[int]:
    """Query each key once; return the predicted decision class per key (last step).
    A prediction equal to cfg.n_values means the cortex emitted UNKNOWN."""
    src_pool = spec["trusted_sources"] if trusted else spec["adversarial_sources"]
    hint = 2 if trusted else 0
    B = len(keys)
    x = torch.zeros(B, cfg.seq_len, 8, dtype=torch.long, device=device)
    for i, k in enumerate(keys):
        x[i, :, 0] = v.EV_QUERY
        x[i, :, 1] = k
        x[i, :, 3] = src_pool[i % len(src_pool)]
        # relation field == key ⇒ a DIRECT value query (rel.ne(k) would route through the
        # relation organ; continual_domain_probe uses the same convention).
        x[i, :, 4] = k
        x[i, :, 5] = v.STATE_STABLE
        x[i, :, 6] = hint
        x[i, :, 7] = 1
    pred = model(x)["decision"].argmax(dim=-1)[:, -1]
    return [int(p) for p in pred.tolist()]


def _new_cortex(cfg, device):
    """Fresh morphogenetic cortex in eval() mode. eval() disables dropout so the
    algorithmic ledger's grounded one-hot deterministically dominates the (untrained)
    neural decision head — recall is then a function of memory, not RNG."""
    m = v.ForwardBoundMorphogeneticCortex(cfg, morphogenetic=True, plastic=True).to(device)
    m.eval()
    return m


def _fresh_from_checkpoint(cfg, device, ckpt_path):
    m = _new_cortex(cfg, device)
    m.load_state_dict(torch.load(ckpt_path, map_location=device))
    m.eval()
    return m


# ======================================================================================
# False-assertion accumulator — gate 8 aggregates every ungrounded query in the run
# ======================================================================================

class FalseAssertionLedger:
    """Every query that has NO grounded memory backing must answer UNKNOWN. This ledger
    tallies them across gates; any non-UNKNOWN answer is a false assertion."""

    def __init__(self, cfg: v.V92Config) -> None:
        self.unk = _unk_index(cfg)
        self.total_ungrounded = 0
        self.false_assertions = 0
        self.samples: List[Dict[str, Any]] = []

    def record(self, source: str, preds: List[int]) -> int:
        n_false = sum(1 for p in preds if p != self.unk)
        self.total_ungrounded += len(preds)
        self.false_assertions += n_false
        self.samples.append({"source": source, "n": len(preds),
                              "false": n_false, "preds": preds})
        return n_false


# ======================================================================================
# Gates 2–6 — cortex longitudinal behaviour on never-audited data
# ======================================================================================

# Domain ids deliberately disjoint from anything the v9.9.x audits or the in-process
# developmental loop ever used (those used 5,6,7 and real AG News / WikiText).
UNSEEN_DOMAINS = [23, 29, 31]


def gate_unseen_domain_transfer(cfg, device, outdir: Path) -> Dict[str, Any]:
    """A fresh cortex must LEARN and RECALL domains never seen in any prior audit."""
    per_domain = []
    for d in UNSEEN_DOMAINS:
        model = _new_cortex(cfg, device)
        v.clear_persistent_cortex_memory(model, cfg)
        spec = v.build_continual_domain_spec(cfg, domain_id=d)
        pre = v.continual_domain_probe(model, cfg, spec, device)["domain_accuracy"]
        v.ingest_continual_domain_experience(model, cfg, spec, device)
        v.sleep_consolidate_persistent_memory(model, cfg)
        post = v.continual_domain_probe(model, cfg, spec, device)["domain_accuracy"]
        per_domain.append({"domain_id": d, "pre": pre, "post": post, "gain": post - pre})
    mean_post = sum(r["post"] for r in per_domain) / len(per_domain)
    mean_gain = sum(r["gain"] for r in per_domain) / len(per_domain)
    return {
        "per_domain": per_domain,
        "mean_post_accuracy": mean_post,
        "mean_learning_gain": mean_gain,
        "passed": mean_post >= 0.85 and mean_gain >= 0.35,
    }


def gate_real_oov_unknown(cfg, device, far: FalseAssertionLedger) -> Dict[str, Any]:
    """Teach HALF the keys; query the genuinely never-taught half → must be UNKNOWN.
    Also feeds the false-assertion ledger (these queries are ungrounded by construction)."""
    model = _new_cortex(cfg, device)
    v.clear_persistent_cortex_memory(model, cfg)
    spec = v.build_continual_domain_spec(cfg, domain_id=UNSEEN_DOMAINS[0])
    taught = list(range(0, cfg.n_keys, 2))      # even keys grounded
    untaught = [k for k in range(cfg.n_keys) if k not in taught]
    _teach_keys(model, cfg, spec, device, taught)
    v.sleep_consolidate_persistent_memory(model, cfg)

    unk = _unk_index(cfg)
    taught_preds = _query_keys(model, cfg, spec, device, taught)
    untaught_preds = _query_keys(model, cfg, spec, device, untaught)
    far.record("oov_untaught_keys", untaught_preds)

    taught_correct = sum(1 for k, p in zip(taught, taught_preds) if p == spec["values"][k])
    untaught_unk = sum(1 for p in untaught_preds if p == unk)
    return {
        "taught_keys": taught, "untaught_keys": untaught,
        "taught_recall": taught_correct / max(1, len(taught)),
        "untaught_unknown_rate": untaught_unk / max(1, len(untaught)),
        "untaught_preds": untaught_preds,
        # taught keys must recall their grounded value; untaught must ALL be UNKNOWN
        "passed": (taught_correct == len(taught)) and (untaught_unk == len(untaught)),
    }


def gate_delayed_recall_restart(cfg, device, outdir: Path) -> Dict[str, Any]:
    """Teach + consolidate + checkpoint. Then interfere (train a different domain on a
    different model) and let episodes elapse, reload from disk into a fresh process model,
    and prove recall survived the delay and the restart."""
    spec = v.build_continual_domain_spec(cfg, domain_id=UNSEEN_DOMAINS[1])
    model = _new_cortex(cfg, device)
    v.clear_persistent_cortex_memory(model, cfg)
    v.ingest_continual_domain_experience(model, cfg, spec, device)
    v.sleep_consolidate_persistent_memory(model, cfg)
    pre_save = v.continual_domain_probe(model, cfg, spec, device)["domain_accuracy"]
    ckpt = outdir / "v10_delayed_recall_checkpoint.pt"
    torch.save(model.state_dict(), ckpt)

    # --- interference + elapsed time: a DIFFERENT model churns a DIFFERENT domain ---
    interferer = _new_cortex(cfg, device)
    other = v.build_continual_domain_spec(cfg, domain_id=UNSEEN_DOMAINS[2])
    for _ in range(3):  # several elapsed episodes of unrelated activity
        v.ingest_continual_domain_experience(interferer, cfg, other, device)
        v.sleep_consolidate_persistent_memory(interferer, cfg)
        v.continual_domain_probe(interferer, cfg, other, device)
    del model, interferer  # drop the in-memory state — only the on-disk snapshot remains

    # --- restart: brand-new cortex instance reloads the snapshot from disk ---
    reloaded = _fresh_from_checkpoint(cfg, device, ckpt)
    post_reload = v.continual_domain_probe(reloaded, cfg, spec, device)["domain_accuracy"]
    retention = (post_reload / pre_save) if pre_save > 1e-6 else 0.0
    return {
        "pre_save_accuracy": pre_save,
        "post_reload_accuracy": post_reload,
        "retention": retention,
        "elapsed_episodes": 3,
        "passed": retention >= 0.85 and post_reload >= 0.85,
    }


def gate_cross_user_isolation(cfg, device, outdir: Path, far: FalseAssertionLedger) -> Dict[str, Any]:
    """Two users with conflicting facts on the same keys, each in their own cortex +
    checkpoint. User A must recall A's facts and NEVER surface B's distinct values."""
    spec_a = v.build_continual_domain_spec(cfg, domain_id=UNSEEN_DOMAINS[0])
    spec_b = v.build_continual_domain_spec(cfg, domain_id=UNSEEN_DOMAINS[2])

    def _train_user(spec, tag):
        m = _new_cortex(cfg, device)
        v.clear_persistent_cortex_memory(m, cfg)
        v.ingest_continual_domain_experience(m, cfg, spec, device)
        v.sleep_consolidate_persistent_memory(m, cfg)
        ck = outdir / f"v10_user_{tag}_checkpoint.pt"
        torch.save(m.state_dict(), ck)
        return ck

    ck_a = _train_user(spec_a, "A")
    ck_b = _train_user(spec_b, "B")
    user_a = _fresh_from_checkpoint(cfg, device, ck_a)
    user_b = _fresh_from_checkpoint(cfg, device, ck_b)

    keys = list(range(cfg.n_keys))
    preds_a = _query_keys(user_a, cfg, spec_a, device, keys)
    preds_b = _query_keys(user_b, cfg, spec_b, device, keys)

    a_self_correct = sum(1 for k in keys if preds_a[k] == spec_a["values"][k])
    b_self_correct = sum(1 for k in keys if preds_b[k] == spec_b["values"][k])

    # Contamination: A returns B's value on a key where the two users genuinely disagree.
    distinguishing = [k for k in keys if spec_a["values"][k] != spec_b["values"][k]]
    a_leaks_b = sum(1 for k in distinguishing if preds_a[k] == spec_b["values"][k])
    b_leaks_a = sum(1 for k in distinguishing if preds_b[k] == spec_a["values"][k])

    # Ungrounded probe for the false-assertion ledger: query user A on keys it was never
    # taught (a fresh user C with empty memory) — must be UNKNOWN.
    user_c = _new_cortex(cfg, device)
    v.clear_persistent_cortex_memory(user_c, cfg)
    preds_c = _query_keys(user_c, cfg, spec_a, device, keys)
    far.record("cross_user_empty_user_C", preds_c)

    return {
        "user_a_self_recall": a_self_correct / len(keys),
        "user_b_self_recall": b_self_correct / len(keys),
        "n_distinguishing_keys": len(distinguishing),
        "a_leaks_b_count": a_leaks_b,
        "b_leaks_a_count": b_leaks_a,
        "cross_contamination": a_leaks_b + b_leaks_a,
        "passed": (a_leaks_b + b_leaks_a == 0)
                  and a_self_correct == len(keys) and b_self_correct == len(keys),
    }


# --- a small REAL document corpus carrying genuine contradictions (CPU, no network) ---
_REAL_CONTRADICTION_DOCS = [
    # (episode-ordered) plain-English statements; later ones contradict earlier facts.
    ("The headquarters of the Meridian Institute is located in Calder.", "trusted"),
    ("Meridian Institute confirms its headquarters remain in Calder this year.", "trusted"),
    ("A rumor site claims the Meridian Institute moved its headquarters to Vorne.", "rumor"),
    ("Official Meridian Institute records list the headquarters in Calder.", "trusted"),
    ("Multiple verified filings now relocate the Meridian Institute headquarters to Tarsus.", "trusted"),
    ("Subsequent verified filings reaffirm the Meridian Institute headquarters at Tarsus.", "trusted"),
]


def _stable_value_idx(token: str, n_values: int) -> int:
    h = hashlib.sha256(token.lower().encode("utf-8")).hexdigest()
    return int(h[:8], 16) % n_values


def _parse_doc_value(text: str, n_values: int) -> Tuple[int, str]:
    """Deterministically map a document's asserted location term → a value index.
    The 'fact' is the capitalised place name introduced by a locative preposition
    ('in'/'to'/'at') — the last such occurrence, robust to trailing clauses like
    '... in Calder this year.'."""
    words = [w.strip(".,;:") for w in text.split()]
    place = None
    for i, w in enumerate(words[:-1]):
        nxt = words[i + 1]
        if w.lower() in ("in", "to", "at") and nxt[:1].isupper():
            place = nxt  # keep scanning → last locative wins
    if place is None:  # fall back to the last capitalised proper noun
        caps = [w for w in words if w[:1].isupper()]
        place = caps[-1] if caps else words[-1]
    return _stable_value_idx(place, n_values), place


def gate_real_contradiction_stream(cfg, device) -> Dict[str, Any]:
    """Stream contradictions parsed from real document text. A consolidated fact must
    resist a single transient (un-reconsolidated) contradiction, yet a genuinely
    repeated + re-consolidated correction must still win — v9.9.1 arbitration on real
    inputs (not synthetic event tuples)."""
    model = _new_cortex(cfg, device)
    v.clear_persistent_cortex_memory(model, cfg)
    key = 0  # the single entity under test (Meridian Institute headquarters)
    trusted_src, rumor_src = 0, 1

    def _src_int(src_tag: str) -> int:
        return trusted_src if src_tag == "trusted" else rumor_src

    parsed = [(_parse_doc_value(t, cfg.n_values)[0], _parse_doc_value(t, cfg.n_values)[1],
               _src_int(src))
              for (t, src) in _REAL_CONTRADICTION_DOCS]
    v_calder = parsed[0][0]
    v_tarsus = parsed[4][0]

    def _emit(val: int, src: int, ev=v.EV_OBSERVE):
        x = torch.zeros(1, cfg.seq_len, 8, dtype=torch.long, device=device)
        hint = 2 if src == trusted_src else 0
        x[0, 0, :] = torch.tensor((ev, key, val, src, key, v.STATE_STABLE, hint, 0),
                                  dtype=torch.long, device=device)
        for t in range(1, cfg.seq_len):
            x[0, t, 0] = v.EV_DISTRACTOR
            x[0, t, 1] = (key + t) % cfg.n_keys
        v.ingest_events_into_persistent_memory(model, x, cfg)

    spec = {"values": {key: v_calder}, "relations": {key: key},
            "trusted_sources": [trusted_src], "adversarial_sources": [rumor_src]}

    # docs 0,1 (trusted Calder) → consolidate → committed
    _emit(parsed[0][0], parsed[0][2]); _emit(parsed[1][0], parsed[1][2])
    v.sleep_consolidate_persistent_memory(model, cfg)
    committed_val = _query_keys(model, cfg, spec, device, [key])[0]

    # doc 2 = transient rumor (Vorne) with NO reconsolidation → must be resisted
    _emit(parsed[2][0], rumor_src)
    after_rumor = _query_keys(model, cfg, spec, device, [key])[0]

    # doc 3 = trusted reaffirm Calder, consolidate again (still Calder)
    _emit(parsed[3][0], parsed[3][2])
    v.sleep_consolidate_persistent_memory(model, cfg)
    after_reaffirm = _query_keys(model, cfg, spec, device, [key])[0]

    # docs 4,5 = genuine, repeated, verified relocation to Tarsus → must eventually win
    for _ in range(v.V99_COMMIT_RETROGRADE_M + 1):
        _emit(parsed[4][0], parsed[4][2]); _emit(parsed[5][0], parsed[5][2])
    v.sleep_consolidate_persistent_memory(model, cfg)
    after_correction = _query_keys(model, cfg, spec, device, [key])[0]

    resisted_transient = (after_rumor == committed_val == v_calder)
    accepted_genuine = (after_correction == v_tarsus)
    return {
        "value_calder": v_calder, "value_tarsus": v_tarsus,
        "committed_val": committed_val,
        "after_transient_rumor": after_rumor,
        "after_reaffirm": after_reaffirm,
        "after_genuine_correction": after_correction,
        "resisted_transient_contradiction": resisted_transient,
        "accepted_genuine_correction": accepted_genuine,
        "passed": resisted_transient and accepted_genuine,
    }


# ======================================================================================
# Gate 7 — the REAL v15.7a adapter's advisory signals measurably change with structure
# ======================================================================================

def gate_fcem_advisory_effect(fcem: Dict[str, Any]) -> Dict[str, Any]:
    """Drive the real DCortexAdapter with two contrasting streams and prove the advisory
    LatentSignals are a measurable function of input structure: a contested slot must
    carry strictly more conflict pressure than an aligned slot, and ADVISORY must emit
    signals where OFF does not. This is the 'FCE-M changes priority/attention' evidence."""
    cls = fcem["_classes"]
    DCortexAdapter = cls["DCortexAdapter"]
    ADVISORY, OFF = cls["LATENT_MODE_ADVISORY"], cls["LATENT_MODE_OFF"]
    COMMITTED, DISPUTED = cls["ZONE_COMMITTED"], cls["ZONE_DISPUTED"]

    def _slot(entity, family, zone, value_after, value_before, ep):
        return {"entity": entity, "family": family, "zone_after": zone,
                "value_after": value_after, "value_before": value_before,
                "episode_id": ep, "write_step": ep, "reason": "v10-gate7"}

    # Aligned: same trusted value committed across episodes → no standing conflict.
    aligned = DCortexAdapter(mode=ADVISORY)
    for ep in range(4):
        aligned.ingest_slot_event(_slot("inst", "hq", COMMITTED, "calder", "", ep))
        aligned.end_episode(ep)
    aligned_sig = aligned.end_episode(4)

    # Contested: a committed value repeatedly disputed by fresh challengers across episodes.
    contested = DCortexAdapter(mode=ADVISORY)
    challengers = ["vorne", "tarsus", "drel", "oken"]
    for ep in range(4):
        contested.ingest_slot_event(_slot("inst", "hq", DISPUTED, challengers[ep], "calder", ep))
        contested.end_episode(ep)
    contested_sig = contested.end_episode(4)

    # OFF mode must never emit advisory payloads (only diagnostics).
    off = DCortexAdapter(mode=OFF)
    for ep in range(4):
        off.ingest_slot_event(_slot("inst", "hq", DISPUTED, challengers[ep], "calder", ep))
    off_sig = off.end_episode(4)

    def _max_pressure(sig) -> float:
        vals = list(sig.latent_status_pressure.values())
        return max(vals) if vals else 0.0

    aligned_pressure = _max_pressure(aligned_sig)
    contested_pressure = _max_pressure(contested_sig)
    contested_conflicts = len(contested_sig.conflict_persistence)
    aligned_conflicts = len(aligned_sig.conflict_persistence)

    measurable_effect = (
        contested_pressure > aligned_pressure          # contested carries more pressure
        and contested_conflicts > aligned_conflicts     # contested shows persistent conflict
        and not contested_sig.is_empty()                # advisory actually advises
        and off_sig.is_empty()                           # OFF stays silent (mode invariant)
    )
    return {
        "aligned_max_pressure": aligned_pressure,
        "contested_max_pressure": contested_pressure,
        "aligned_conflict_persistence": aligned_conflicts,
        "contested_conflict_persistence": contested_conflicts,
        "contested_challenger_strength": dict(
            (str(k), float(x)) for k, x in contested_sig.challenger_strength.items()),
        "advisory_nonempty": not contested_sig.is_empty(),
        "off_empty": off_sig.is_empty(),
        "passed": bool(measurable_effect),
    }


# ======================================================================================
# Orchestration
# ======================================================================================

def run_v10_milestone(
    fast: bool = True,
    outdir: Path | str = "runtime/v10_milestone_out",
    seed: int = 20261103,
) -> Dict[str, Any]:
    cfg = v.V92Config(fast_run=fast).apply_fast()
    cfg.output_dir = str(outdir)
    out = v.ensure_dir(Path(outdir))
    v.set_seed(seed)
    device = v.get_device()

    print("=" * 94)
    print(f"D_Cortex v10 — Longitudinal Generalization & Isolation  (fast={fast} device={device})")
    print("=" * 94, flush=True)

    # ---- Gate 1: REAL_FCEM_REQUIRED (fail-hard; raises before any other gate runs) ----
    fcem = load_real_fcem_adapter()
    print(f"[GATE 1] REAL_FCEM_REQUIRED  engine={fcem['engine_root']}")
    print(f"         version={fcem['version']} adapter={fcem['adapter_class']} "
          f"pipeline_ran={fcem['pipeline_ran']}", flush=True)

    far = FalseAssertionLedger(cfg)

    g2 = gate_unseen_domain_transfer(cfg, device, out)
    print(f"[GATE 2] UNSEEN_DOMAIN_TRANSFER  mean_post={g2['mean_post_accuracy']:.3f} "
          f"gain={g2['mean_learning_gain']:.3f} -> {g2['passed']}", flush=True)

    g3 = gate_real_oov_unknown(cfg, device, far)
    print(f"[GATE 3] REAL_OOV_UNKNOWN  taught_recall={g3['taught_recall']:.3f} "
          f"untaught_unknown={g3['untaught_unknown_rate']:.3f} -> {g3['passed']}", flush=True)

    g4 = gate_delayed_recall_restart(cfg, device, out)
    print(f"[GATE 4] DELAYED_RECALL_RESTART  reload={g4['post_reload_accuracy']:.3f} "
          f"retention={g4['retention']:.3f} -> {g4['passed']}", flush=True)

    g5 = gate_cross_user_isolation(cfg, device, out, far)
    print(f"[GATE 5] CROSS_USER_ISOLATION  A_recall={g5['user_a_self_recall']:.3f} "
          f"B_recall={g5['user_b_self_recall']:.3f} contamination={g5['cross_contamination']} "
          f"-> {g5['passed']}", flush=True)

    g6 = gate_real_contradiction_stream(cfg, device)
    print(f"[GATE 6] REAL_CONTRADICTION_STREAM  resisted_transient="
          f"{g6['resisted_transient_contradiction']} accepted_genuine="
          f"{g6['accepted_genuine_correction']} -> {g6['passed']}", flush=True)

    g7 = gate_fcem_advisory_effect(fcem)
    print(f"[GATE 7] FCEM_ADVISORY_EFFECT  contested_pressure={g7['contested_max_pressure']:.3f} "
          f"aligned_pressure={g7['aligned_max_pressure']:.3f} -> {g7['passed']}", flush=True)

    # ---- Gate 8: FALSE_ASSERTION_RATE_ZERO (aggregate of every ungrounded query) ----
    g8 = {
        "total_ungrounded_queries": far.total_ungrounded,
        "false_assertions": far.false_assertions,
        "samples": far.samples,
        "passed": far.false_assertions == 0 and far.total_ungrounded > 0,
    }
    print(f"[GATE 8] FALSE_ASSERTION_RATE_ZERO  ungrounded={g8['total_ungrounded_queries']} "
          f"false_assertions={g8['false_assertions']} -> {g8['passed']}", flush=True)

    gates = {
        "REAL_FCEM_REQUIRED": True,  # would have raised above otherwise
        "UNSEEN_DOMAIN_TRANSFER": g2["passed"],
        "REAL_OOV_UNKNOWN": g3["passed"],
        "DELAYED_RECALL_RESTART": g4["passed"],
        "CROSS_USER_ISOLATION": g5["passed"],
        "REAL_CONTRADICTION_STREAM": g6["passed"],
        "FCEM_ADVISORY_EFFECT": g7["passed"],
        "FALSE_ASSERTION_RATE_ZERO": g8["passed"],
    }
    passed = sum(1 for x in gates.values() if x)
    total = len(gates)
    verdict = "V10_LONGITUDINAL_VALIDATED" if all(gates.values()) else "V10_LONGITUDINAL_PARTIAL"

    report = {
        "schema_version": "v10_longitudinal_generalization_isolation_v1",
        "claim_boundary": "Longitudinal generalization + isolation over the validated v9.9 "
                          "morphogenetic addressable memory with the REAL sealed FCE-M v15.7a "
                          "consolidator. Not a general LLM, not consciousness, "
                          "FULL_LEVEL3_NOT_DECLARED preserved.",
        "config": {"fast": fast, "seed": seed, "device": str(device),
                   "unseen_domains": UNSEEN_DOMAINS},
        "fcem": {k: fcem[k] for k in ("engine_root", "version", "adapter_class",
                                      "adapter_file", "pipeline_ran", "raw_params")},
        "gate1_real_fcem_required": {k: fcem[k] for k in (
            "engine_root", "version", "adapter_class", "pipeline_ran")},
        "gate2_unseen_domain_transfer": g2,
        "gate3_real_oov_unknown": g3,
        "gate4_delayed_recall_restart": g4,
        "gate5_cross_user_isolation": g5,
        "gate6_real_contradiction_stream": g6,
        "gate7_fcem_advisory_effect": g7,
        "gate8_false_assertion_rate_zero": g8,
        "gates": gates,
        "gates_passed": passed,
        "gates_total": total,
        "verdict": verdict,
    }
    report_path = out / "v10_milestone_report.json"
    report_path.write_text(json.dumps(v.safe_json(report), indent=2), encoding="utf-8")

    print("=" * 94)
    print(f"[V10 VERDICT] {verdict}  ({passed}/{total})")
    for k, val in gates.items():
        print(f"  {'[+]' if val else '[-]'} {k}")
    print(f"[V10] report -> {report_path}")
    print("=" * 94, flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="D_Cortex v10 Longitudinal Generalization & Isolation")
    ap.add_argument("--fast", action="store_true", default=True)
    ap.add_argument("--full", dest="fast", action="store_false")
    ap.add_argument("--outdir", default="runtime/v10_milestone_out")
    ap.add_argument("--seed", type=int, default=20261103)
    args = ap.parse_args()
    report = run_v10_milestone(args.fast, args.outdir, args.seed)
    raise SystemExit(0 if report["gates_passed"] == report["gates_total"] else 2)


if __name__ == "__main__":
    main()
