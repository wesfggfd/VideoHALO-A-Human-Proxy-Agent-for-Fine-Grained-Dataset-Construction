# Changelog: VideoHALO 3.6 → 3.7 Fixed-8

## 3.7.5 production transport hardening

- Replaced Gemini Developer Files API/API-key transport with Gemini Enterprise
  ADC/IAM and immutable private GCS URIs.
- Added process-wide 401/403 provider circuit breaking, credential redaction,
  and smooth cross-worker request pacing.
- Preserved the Fixed-8 taxonomy, system semantics, one-slot mutation rules,
  direct public pair schema, and existing locked dataset items.

## Taxonomy

The runtime taxonomy is replaced by eight mutually exclusive leaves:

- retained: EntityExistence, EntityCategory, EntityQuantity, AttributeValue, StaticRelation, ActionPredicate, TemporalRelation, CameraPredicate;
- removed from the scoring taxonomy: EntityReference, ActionBinding, CausalRelation.

Removed structures are **not silently remapped**. They are ineligible for
construction.

## Workflow

The following 3.6 operations are deleted:

- freeze Machine Candidate Batch;
- package Phase A/Phase B human review;
- calculate human agreement;
- produce audit and difference reports;
- unlock a batch after review;
- keep a private machine-reference manifest tied to review records.

The replacement endpoint is direct, schema-validated JSONL emission
immediately after one high-thinking `<monitor_agent>` validation and single-error
validation. Fact and candidate A/B committees and the standalone Annotation
mode were subsequently removed in core memory 3.7.3.

## Output

Build mode now writes the exact pair-level shape used by `public_probe_items`:

```text
schema_version, pair_id, media, task_type, question,
answer, counterfactual_answer, leaf_label, conflict_slot
```

The data contract version remains `videohalo_probe_pair_sample_fixed8_3.6.1` for compatibility with the existing dataset file.

## Modes retained

- `probe_build`
- `evalbench_build`
