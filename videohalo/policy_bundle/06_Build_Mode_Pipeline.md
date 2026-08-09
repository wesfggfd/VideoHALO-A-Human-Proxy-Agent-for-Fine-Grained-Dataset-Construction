# Build Mode Pipeline

## Purpose

Build mode constructs a paired sample directly from a Gemini-native verified
source fact.

## Phase 0: frozen taxonomy prior

The Taxonomy Planner loads the Fixed-8 leaf-search plan before inspecting the
video. The plan fixes each leaf's fact kind, conflict slot, search question,
construction rule, and hard exclusions. Class-count targets are not evidence
and do not affect constructibility.

## Phase 1: eight-leaf opportunity scan

1. Register the original video and materialize its immutable private GCS object.
   Before any model call, require exact equality across the current local-file
   SHA-256, canonical manifest SHA-256, active GCS object metadata SHA-256,
   lease source URI, and request `gs://` media URI. Record a fingerprint of the actual media
   URI on every media-bearing call; any identity mismatch rejects the video.
2. Leaf Opportunity Scout evaluates every Fixed-8 leaf exactly once from the
   original video at high media resolution.
3. Each row is `constructible`, `not_constructible`, or `uncertain`.
4. A constructible row records a decisive evidence interval and canonical
   anchor; non-constructible and uncertain rows record no evidence claim.

## Phase 2: leaf-conditioned FactBank

1. Leaf Fact Extractor receives only constructible opportunities and rereads
   their evidence intervals from the original video at high media resolution.
2. It emits at most one best atomic fact per constructible leaf.
3. Every fact preserves the planned leaf, fact kind, conflict slot, evidence
   interval, and anchor.
4. Fact Reflection rereads the original video at high media resolution and
   requires support, a non-empty overlapping evidence interval,
   unique grounding, correct leaf boundaries, and a viable one-slot mutation.
5. Only reflected facts enter the FactBank. EntityReference, ActionBinding,
   CausalRelation, ambiguous, or insufficient structures remain ineligible.

## Phase 3: evidence-faithful selection

Selection is based on verified supply, task compatibility, source-fact
uniqueness, video contribution caps, and deterministic diversity. The final
leaf distribution follows constructible evidence; there is no equal-count
target or hard per-leaf quota.

## Phase 4: one-slot counterfactual

The deterministic mutation engine changes exactly one frozen slot:

| leaf | mutation |
|---|---|
| EntityExistence | toggle presence/absence assertion |
| EntityCategory | replace category |
| EntityQuantity | change count |
| AttributeValue | replace observable value |
| StaticRelation | invert/replace static relation |
| ActionPredicate | replace action predicate |
| TemporalRelation | reverse relative order |
| CameraPredicate | replace an observed camera/edit change, or deny it with `no_camera_change` |

## Phase 5: task-specific diverse realization

- Captioning and non-polar VideoQA `answer` copy the complete natural-language
  reflected source fact verbatim; EntityExistence VideoQA adds only the
  question-required explained `Yes,`/`No,` polarity frame.
- `counterfactual_answer` verbalizes the one-slot mutation.
- Video-captioning deterministically selects one of several complete-sentence
  prompts.
- Video-QA deterministically selects one of several leaf-specific question
  templates, including separate null-object action forms.
- The selected `question_template_id` is retained internally for audit.
- The realizer must copy the selected question exactly. Only wording varies;
  the fact, leaf, slot, evidence scope, and canonical anchors are frozen.
- Both answers must match the question family. EntityExistence uses
  self-contained polarity answers; the other seven VideoQA leaves use direct
  non-Yes/No answers. The two answers retain one grammatical frame and differ
  only at the conflict slot.

## Phase 6: structural validation

Jointly backparse both answers with canonical non-target fields frozen and
require:

- the question-answer form contract passes before GraphDiff validation;
- EntityExistence polarity prefixes recover the corresponding boolean slot;

```text
changed_atomic_fact_count = 1
changed_slot_count = 1
supported_contradicted_count = 0
counterfactual_contradicted_count = 1
resolved_leaf = planned_leaf
resolved_slot = planned_slot
unexpected_claim_count = 0
```

## Phase 7: candidate reflection

Candidate Reflection rereads the original video at high media resolution and
verifies the full answer pair against the authoritative supported and
counterfactual structures. It must confirm that the natural answer exactly
matches the verified source fact and its evidence interval, the target leaf
boundary is correct, the counterfactual is contradicted under that same leaf,
and only the target slot differs.

## Phase 8: direct output

The validated internal candidate is immediately projected to the public
nine-field pair record and appended to JSONL. No batch-wide semantic operation
follows.
