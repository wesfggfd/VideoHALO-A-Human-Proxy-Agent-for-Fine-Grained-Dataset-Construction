# LangGraph Engineering Architecture

## 1. Runtime modes

```text
probe_build     → direct Fixed-8 pair JSONL
evalbench_build → direct Fixed-8 pair JSONL
```

Probe and EvalBench profiles share one BuildGraph and differ only in selection policy, target scale, and source-video pool.

## 2. BuildGraph

```text
START
→ load_fixed8_policy
→ canonical_media_registration
→ private_gcs_materialization
→ taxonomy_first_plan
→ eight_leaf_opportunity_scan
→ leaf_conditioned_fact_extraction
→ fact_reflection
→ fixed8_eligibility_scan
→ faithful_relative_selection
→ one_slot_mutation
→ answer_pair_realization
→ backparse_both_answers
→ graph_diff
→ single_error_validation
→ candidate_reflection
→ direct_pair_projection
→ append_public_probe_jsonl
→ END
```

There is no batch freeze, review packaging, human audit, private reference, or unlock graph.

## 3. Deterministic routing

Build failures route to bounded machine-only actions:

- `retry_native_focus`
- `rewrite_surface`
- `remutate`
- `repropose_fact`
- `reject_candidate`

## 4. State and persistence

Use TypedDict/Pydantic state, a LangGraph checkpointer, idempotent artifact writes, and deterministic IDs derived from `video_id + source_fact_id + mutation_version`. Direct JSONL append must be atomic and deduplicate `pair_id`.

## 5. High-thinking reflection

One high-thinking Fact Reflection validates each extracted fact. One
high-thinking Candidate Reflection validates each final pair. No A/B committee
or secondary judging graph remains in the construction runtime.
