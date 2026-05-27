# Memory-service engine patch plan - true in-engine snapshot / atomic-swap

**Status: DEFERRED (honest).** Track A of Cycle 8 was *optional*. The canonical memory-service
lives in the **sealed, gitignored** checkout at
`external/byon_optimus/byon-orchestrator/memory-service/server.py` (FastAPI + FAISS `IndexFlatIP`
+ FCE-M). Per the Cycle-8 rule "do not modify sealed external/ memory-service blindly", a true
in-engine snapshot/atomic-swap is **not implemented in this cycle** and is **not claimed**.

What exists instead (shipped, tested): an **engine read/write coordination lock**
(`gateway/engine_consistency.py`) that every writer and reader shares - a writer marks a write
batch (`begin_write`/`commit_write`), a reader **waits (bounded, explicit timeout)** for commit
before reading, so no reader observes a partial FAISS/metadata state. It exposes
`read_consistency_mode=in_engine_rw_lock`, `snapshot_version` (write-batch counter),
`last_write_batch_id`, `last_consistent_read_ts`. The Cycle-5 snapshot+retry remains as a
fallback. This is coordination at the shared access boundary, **not** an in-engine FAISS swap.

## Exact changes needed to implement true in-engine snapshot/atomic-swap

In `memory-service/server.py` (the sealed engine), behind a feature flag
`MEMORY_SERVICE_ENGINE_SNAPSHOT=true` so the default behaviour is unchanged:

1. **Index/metadata pair as one swappable object.** Wrap the live `faiss.IndexFlatIP` and its
   parallel metadata list/dict in a small `IndexState` object `{index, metadata, version}`. All
   reads go through `state = self._stable` (a single attribute read - atomic in CPython).

2. **Write to staging, swap atomically.** A `store` / `store_batch` builds a *copy* (or a delta
   applied to a clone) into `staging = IndexState(clone(index), clone(metadata), version+1)`,
   then publishes with a single assignment `self._stable = staging` under a short write lock. FAISS
   `IndexFlatIP` supports `reconstruct_n` + rebuild, or maintain an append log and rebuild the
   clone; for the ~12k-vector scale here a full clone per batch is acceptable.

3. **Readers use the previous snapshot during a batch.** `search` captures `s = self._stable` once
   and queries `s.index` / `s.metadata` - so an in-flight batch building `staging` never affects a
   reader; the reader sees the previous consistent snapshot until the swap.

4. **Expose the signal.** Add an action `consistency_status` → `{read_consistency_mode:
   "in_engine_snapshot", snapshot_version, last_write_batch_id, building: bool}` and include it in
   `/health`. `gateway/consistent_client.py` would prefer this when present and report
   `read_consistency_mode=in_engine_snapshot`.

5. **Persistence alignment.** Persist `index` and `metadata` together (same `version`) so a restart
   never loads a FAISS index whose metadata is one batch ahead/behind (the source of the observed
   transient `vault_facts_in_memory=0`).

## Tests to add when implemented (Cycle-8 Track A names)
- `in_engine_snapshot_read_during_write_consistent`
- `atomic_swap_preserves_metadata_alignment`
- `reader_uses_previous_snapshot_during_batch`
- `status_reports_snapshot_version`
- `boundary_wrapper_still_fallback`

## How to version the sealed engine safely
Either (a) vendor a copy under `gateway/vendor/memory_service/` with an idempotent patcher (the
pattern `orchestration/integrate.py` already uses to inject the D_Cortex actions), or (b) open a
documented patch branch on `byon_optimus` and pin its SHA. Until that decision is made by the
maintainer, the boundary coordination lock above is the consistency mechanism, and this document
is the exact recipe to upgrade it - **no in-engine snapshot is claimed to exist.**
