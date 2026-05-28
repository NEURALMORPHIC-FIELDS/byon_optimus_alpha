#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""D_Cortex v10.0 - Full-Organism Developmental Training Loop.

Where v9.x audits proved single capabilities, v10.0 chains them into a multi-epoch
cognitive development cycle and measures longitudinal behaviour:

    read/assimilate -> verify -> consolidate (sleep) -> restart/reload -> QA
                    -> contradiction -> controlled forgetting -> source/unknown

It is built ENTIRELY on the validated v9.9 primitives (no new science is invented):
``ForwardBoundMorphogeneticCortex``, ``ingest_continual_domain_experience``,
``continual_domain_probe``, ``sleep_consolidate_persistent_memory``,
``persistent_memory_export/import``, ``clear_persistent_cortex_memory``.

Metrics (dev-sheet §11.2): semantic QA accuracy, reload retention, cross-session
stability, memory/key damage under ablation, sleep consolidation gain, contradiction
boundary, controlled-forgetting drop, adversarial-source false-assertion rate.

Run:
    python -m dcortex.v10_developmental_loop --sessions 3 --fast
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import torch

from dcortex import v99_source as v


def _mean(xs: List[float]) -> float:
    xs = [x for x in xs if x is not None]
    return float(sum(xs) / len(xs)) if xs else 0.0


def _fresh_from_checkpoint(cfg, device, ckpt_path):
    """Build a fresh cortex and load a full state_dict checkpoint from disk - the
    faithful 'process restart + checkpoint reload' the v9.5 persistence audit uses
    (registered persistent buffers travel with the state_dict). Used per sub-test so
    earlier mutations never leak between phases."""
    m = v.ForwardBoundMorphogeneticCortex(cfg, morphogenetic=True, plastic=True).to(device)
    m.load_state_dict(torch.load(ckpt_path, map_location=device))
    return m


def run_v10_developmental_loop(
    sessions: int = 3,
    fast: bool = True,
    outdir: Path | str = "runtime/v10_out",
    seed: int = 20261103,
) -> Dict[str, Any]:
    cfg = v.V92Config(fast_run=fast).apply_fast()
    cfg.output_dir = str(outdir)
    out = v.ensure_dir(Path(outdir))
    v.set_seed(seed)
    device = v.get_device()

    print("=" * 94)
    print(f"D_Cortex v10.0 Developmental Loop - sessions={sessions} fast={fast} device={device}")
    print("=" * 94, flush=True)

    model = v.ForwardBoundMorphogeneticCortex(cfg, morphogenetic=True, plastic=True).to(device)

    # distinct domains, one per developmental session (course-like curricula)
    domain_ids = [5 + i for i in range(sessions)]
    specs = {d: v.build_continual_domain_spec(cfg, domain_id=d) for d in domain_ids}

    # Each session assimilates one domain, consolidates (sleep), and EXPORTS its own
    # memory snapshot. Per-session snapshots let us measure true persistence without
    # cross-domain interference on the shared 8-key address space (a real capacity
    # limit we measure separately rather than conflate with the reload mechanism).
    session_records: List[Dict[str, Any]] = []
    session_ckpts: List[Path] = []
    for i, d in enumerate(domain_ids):
        spec = specs[d]
        v.clear_persistent_cortex_memory(model, cfg)  # isolate each session's assimilation
        pre = v.continual_domain_probe(model, cfg, spec, device)
        v.ingest_continual_domain_experience(model, cfg, spec, device)
        post = v.continual_domain_probe(model, cfg, spec, device)
        sleep = v.sleep_consolidate_persistent_memory(model, cfg)
        post_sleep = v.continual_domain_probe(model, cfg, spec, device)
        ckpt = out / f"v10_session{i}_dom{d}_checkpoint.pt"
        torch.save(model.state_dict(), ckpt)  # persist full state -> simulate restart
        session_ckpts.append(ckpt)
        rec = {
            "session": i, "domain_id": d,
            "pre_accuracy": pre["domain_accuracy"],
            "post_accuracy": post["domain_accuracy"],
            "post_sleep_accuracy": post_sleep["domain_accuracy"],
            "learning_gain": post["domain_accuracy"] - pre["domain_accuracy"],
            "sleep_gain": post_sleep["domain_accuracy"] - post["domain_accuracy"],
            "z_active_reduction": sleep.get("z_active_reduction", 0.0),
        }
        session_records.append(rec)
        print(f"[SESSION {i} dom={d}] pre={rec['pre_accuracy']:.3f} post={rec['post_accuracy']:.3f} "
              f"sleep={rec['post_sleep_accuracy']:.3f} gain={rec['learning_gain']:.3f}", flush=True)

    # ---- per-session restart: fresh model + reload THAT session's snapshot ----
    reload_probes: List[Dict[str, Any]] = []
    for i, d in enumerate(domain_ids):
        spec = specs[d]
        reloaded = _fresh_from_checkpoint(cfg, device, session_ckpts[i])
        value_p = v.continual_domain_probe(reloaded, cfg, spec, device)
        relation_p = v.continual_domain_probe(reloaded, cfg, spec, device, relation_query=True)
        disabled_p = v.continual_domain_probe(reloaded, cfg, spec, device, disable_persistent_memory=True)
        scrambled_p = v.continual_domain_probe(reloaded, cfg, spec, device, scramble_key=True)
        adversarial_p = v.continual_domain_probe(reloaded, cfg, spec, device, adversarial_source=True)
        post_sleep_acc = session_records[i]["post_sleep_accuracy"]
        reload_probes.append({
            "session": i, "domain_id": d,
            "reload_accuracy": value_p["domain_accuracy"],
            "reload_relation_accuracy": relation_p["domain_accuracy"],
            "reload_source_recall": value_p["source_recall"],
            "memory_damage": value_p["domain_accuracy"] - disabled_p["domain_accuracy"],
            "key_damage": value_p["domain_accuracy"] - scrambled_p["domain_accuracy"],
            "adversarial_false_assertion": adversarial_p["domain_accuracy"],
            "reload_retention": (value_p["domain_accuracy"] / post_sleep_acc) if post_sleep_acc > 1e-6 else 0.0,
        })
        print(f"[RELOAD  {i} dom={d}] reload={reload_probes[i]['reload_accuracy']:.3f} "
              f"retention={reload_probes[i]['reload_retention']:.3f} "
              f"mem_damage={reload_probes[i]['memory_damage']:.3f} key_damage={reload_probes[i]['key_damage']:.3f} "
              f"adv_false={reload_probes[i]['adversarial_false_assertion']:.3f}", flush=True)

    # ---- contradiction after consolidation: from a CLEAN reload of session 0 ----
    contra_model = _fresh_from_checkpoint(cfg, device, session_ckpts[0])
    base_spec = specs[domain_ids[0]]
    contra_spec = {**base_spec,
                   "values": {k: int((vv + 1) % cfg.n_values) for k, vv in base_spec["values"].items()},
                   "trusted_sources": base_spec["adversarial_sources"],
                   "adversarial_sources": base_spec["trusted_sources"]}
    before_contra = v.continual_domain_probe(contra_model, cfg, base_spec, device)["domain_accuracy"]
    v.ingest_continual_domain_experience(contra_model, cfg, contra_spec, device)
    after_contra = v.continual_domain_probe(contra_model, cfg, base_spec, device)["domain_accuracy"]
    contradiction = {
        "original_accuracy_before_contradiction": before_contra,
        "original_accuracy_after_contradiction": after_contra,
        "contradiction_boundary_retention": (after_contra / before_contra) if before_contra > 1e-6 else 0.0,
    }
    print(f"[CONTRA] before={before_contra:.3f} after={after_contra:.3f} "
          f"retention={contradiction['contradiction_boundary_retention']:.3f}", flush=True)

    # ---- controlled forgetting: from a CLEAN reload of the last session ----
    forget_model = _fresh_from_checkpoint(cfg, device, session_ckpts[-1])
    forget_before = v.continual_domain_probe(forget_model, cfg, specs[domain_ids[-1]], device)["domain_accuracy"]
    v.clear_persistent_cortex_memory(forget_model, cfg)
    forget_after = v.continual_domain_probe(forget_model, cfg, specs[domain_ids[-1]], device)["domain_accuracy"]
    forgetting = {
        "accuracy_before_clear": forget_before,
        "accuracy_after_clear": forget_after,
        "controlled_forgetting_drop": forget_before - forget_after,
    }
    print(f"[FORGET] before={forget_before:.3f} after={forget_after:.3f} drop={forgetting['controlled_forgetting_drop']:.3f}", flush=True)

    # ---- aggregate metrics + verdict ----
    metrics = {
        "mean_learning_gain": _mean([r["learning_gain"] for r in session_records]),
        "mean_sleep_gain": _mean([r["sleep_gain"] for r in session_records]),
        "mean_reload_accuracy": _mean([r["reload_accuracy"] for r in reload_probes]),
        "mean_reload_retention": _mean([r["reload_retention"] for r in reload_probes]),
        "cross_session_stability": _mean([r["reload_accuracy"] for r in reload_probes])
        / max(1e-6, _mean([r["post_sleep_accuracy"] for r in session_records])),
        "mean_memory_damage": _mean([r["memory_damage"] for r in reload_probes]),
        "mean_key_damage": _mean([r["key_damage"] for r in reload_probes]),
        "mean_relation_reload_accuracy": _mean([r["reload_relation_accuracy"] for r in reload_probes]),
        "mean_source_recall": _mean([r["reload_source_recall"] for r in reload_probes]),
        # The adversarial-source probe keeps the CORRECT value as target: high accuracy
        # means the consolidated trusted answer survives an adversarial query channel
        # (resilience to source-spoofing), which is the desired behaviour.
        "adversarial_resilience": _mean([r["adversarial_false_assertion"] for r in reload_probes]),
        "contradiction_boundary_retention": contradiction["contradiction_boundary_retention"],
        "controlled_forgetting_drop": forgetting["controlled_forgetting_drop"],
    }
    criteria = {
        "learning_occurs": metrics["mean_learning_gain"] >= 0.20,
        "reload_retained": metrics["mean_reload_retention"] >= 0.85,
        "cross_session_stable": metrics["cross_session_stability"] >= 0.85,
        "memory_is_causal": metrics["mean_memory_damage"] >= 0.20,
        "addressing_is_causal": metrics["mean_key_damage"] >= 0.15,
        "controlled_forgetting_works": metrics["controlled_forgetting_drop"] >= 0.20,
        "adversarial_source_resilient": metrics["adversarial_resilience"] >= 0.60,
        # v9.9.1: a consolidated value must resist a transient re-ingested contradiction
        # (cortex-level arbitration; genuine consolidated correction still updates).
        "contradiction_resisted": metrics["contradiction_boundary_retention"] >= 0.60,
    }
    passed = int(sum(1 for x in criteria.values() if x))
    total = len(criteria)
    verdict = "V10_DEVELOPMENTAL_LOOP_VALIDATED_WEAK" if all(criteria.values()) \
        else "V10_DEVELOPMENTAL_LOOP_PARTIAL"

    report = {
        "schema_version": "v10.0_full_organism_developmental_loop_v1",
        "claim_boundary": "Longitudinal developmental loop over the validated v9.9 morphogenetic "
                          "addressable memory; not a general LLM, not consciousness.",
        "config": {"sessions": sessions, "fast": fast, "seed": seed, "device": str(device)},
        "session_records": session_records,
        "reload_probes": reload_probes,
        "contradiction": contradiction,
        "forgetting": forgetting,
        "metrics": metrics,
        "criteria": criteria,
        "criteria_passed": passed,
        "criteria_total": total,
        "verdict": verdict,
    }
    report_path = out / "v10_developmental_loop_report.json"
    report_path.write_text(json.dumps(v.safe_json(report), indent=2), encoding="utf-8")
    print("=" * 94)
    print(f"[V10 VERDICT] {verdict} ({passed}/{total})")
    for k, val in criteria.items():
        print(f"  {'[+]' if val else '[-]'} {k}")
    print(f"[V10] report -> {report_path}")
    print("=" * 94, flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="D_Cortex v10.0 developmental training loop")
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--fast", action="store_true", default=True)
    ap.add_argument("--full", dest="fast", action="store_false")
    ap.add_argument("--outdir", default="runtime/v10_out")
    ap.add_argument("--seed", type=int, default=20261103)
    args = ap.parse_args()
    report = run_v10_developmental_loop(args.sessions, args.fast, args.outdir, args.seed)
    raise SystemExit(0 if report["criteria_passed"] == report["criteria_total"] else 2)


if __name__ == "__main__":
    main()
