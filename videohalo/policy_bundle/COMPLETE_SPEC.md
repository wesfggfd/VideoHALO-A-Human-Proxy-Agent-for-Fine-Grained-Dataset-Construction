# VideoHALO 3.7 Fixed-8 Technical Documentation

> 中文定位：本版本将 VideoHALO 收敛为 **6 个父类、8 个互斥叶标签**的高质量数据集构建系统。系统仅保留构建模式。

## Normative scope

VideoHALO 3.7 contains one runtime mode:

1. **Build mode** (`probe_build` or `evalbench_build`): construct a supported answer and a single-slot counterfactual answer from a Gemini-native verified source fact, then directly append one JSON object to `public_probe_items.jsonl`.

## Fixed-8 taxonomy

| Parent | Leaf | Conflict slot |
|---|---|---|
| Entity | EntityExistence | `existence` |
| Entity | EntityCategory | `category` |
| Entity | EntityQuantity | `count` |
| Attribute | AttributeValue | `attribute_value` |
| Relation | StaticRelation | `relation_predicate` |
| Action | ActionPredicate | `predicate` |
| Event | TemporalRelation | `order` |
| Camera | CameraPredicate | `camera_predicate` |

The build output contract intentionally matches the uploaded `public_probe_items` format:

```json
{
  "schema_version": "videohalo_probe_pair_sample_fixed8_3.6.1",
  "pair_id": "pair_captioning_0066_fact_05",
  "media": {
    "canonical_media_uri": "media://captioning_0066/original",
    "evidence_policy_id": "gemini_native_original_video_v1",
    "registered_modalities": [
      "visual", "speech_audio", "non_speech_audio",
      "on_screen_text", "camera_editing", "container_metadata"
    ],
    "video_id": "captioning_0066"
  },
  "task_type": "video_captioning",
  "question": "State one directly observable fact from the video in one sentence.",
  "answer": "The news presenter is speaking.",
  "counterfactual_answer": "The news presenter is sleeping.",
  "leaf_label": "ActionPredicate",
  "conflict_slot": "predicate"
}
```

## Removed from runtime

- Human review packets
- Two-expert audit
- IAA computation
- Batch freeze and unlock
- Human Gold
- Machine private reference manifests
- Review difference sidecars
- Post-review filtering, relabeling, balancing, or supplementation

Internal FactGraphs and validator traces may still be stored for debugging and reproducibility, but they are not part of the published dataset record.

## Start here

- `01_VHal_Fixed8_Atomic_Fact_Taxonomy.md`
- `05_LangGraph_Engineering_Architecture.md`
- `06_Build_Mode_Pipeline.md`
- `08_Direct_Output_Data_Contracts.md`
- `11_Implementation_Migration_From_3.6.md`

---

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
immediately after one high-thinking Candidate Reflection and single-error
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

---

# VHal Fixed-8 Atomic-Fact Taxonomy

**Taxonomy version:** `VHal-Fixed8-3.7`  
**Parent categories:** 6  
**Mutually exclusive leaves:** 8

## 1. Classification unit

The unit is a normalized atomic fact. A sentence may contain multiple facts, but every contradicted in-scope fact has exactly one leaf. The taxonomy identifies the typed fact slot that conflicts with the original Gemini-native video.

```text
response → atomic facts → grounding → evidence adequacy
→ fact kind → conflict slot → deterministic leaf
```

## 2. Evidence and status

The semantic authority is the original full-modal video supplied to Gemini Enterprise through an immutable private Google Cloud Storage URI. Build mode only uses facts that are natively decidable.

Facts that are insufficiently grounded or outside Fixed-8 are rejected from
construction. They are operational rejection states, not leaves.

## 3. Entity

### 3.1 EntityExistence

**Fact kind:** `entity_existence`  
**Signature:** `Exists(entity_or_scene, time_scope)`  
**Conflict slot:** `existence`

Use when an answer invents an entity or explicitly denies an entity that is present. Omission alone is not a contradiction unless the answer makes an exhaustive claim.

Boundary:

- present cat described as dog → EntityCategory;
- no animal exists but answer says a dog exists → EntityExistence.

### 3.2 EntityCategory

**Fact kind:** `entity_category`  
**Signature:** `Category(entity_id, category, time_scope)`  
**Conflict slot:** `category`

Use when a uniquely grounded entity exists but its normalized category is wrong. Person gender, age appearance, clothing, and color are attributes, not entity categories.

### 3.3 EntityQuantity

**Fact kind:** `entity_quantity`  
**Signature:** `Count(entity_set, time_scope, number)`  
**Conflict slot:** `count`

Use for the number of distinct visible entity tracks in a fixed time scope. Event repetition count and action-participant-role disputes are outside this leaf.

## 4. Attribute

### 4.1 AttributeValue

**Fact kind:** `attribute_value`  
**Signature:** `Attribute(entity_or_scene_id, key, value, time_scope)`  
**Conflict slot:** `attribute_value`

Use for directly observable unary properties: color, material, shape, size, clothing, demographic appearance, stable posture, visible state, display content, or readable on-screen text.

Hard boundary:

```text
door is open → AttributeValue
door opens    → ActionPredicate
```

Unobservable intention, personality, moral evaluation, and subjective atmosphere are not construction targets.

## 5. Relation

### 5.1 StaticRelation

**Fact kind:** `static_relation`  
**Signature:** `StaticRelation(subject_id, relation, object_id, time_scope)`  
**Conflict slot:** `relation_predicate`

Use for a static spatial relation between grounded entities: left, right, above, below, in front, behind, inside, outside, on, under, beside, near, far, contact, support, overlap, or facing.

Snapshot rule: if cross-frame motion is necessary to establish the claim, it is not StaticRelation.

## 6. Action

### 6.1 ActionPredicate

**Fact kind:** `action_predicate`  
**Signature:** `EventPredicate(event_id, predicate, interval)`  
**Conflict slot:** `predicate`

Use for a wrong dynamic event or process: speaking versus sleeping, walking versus running, opening versus closing, lifting versus dropping, entering versus leaving, and other natively decidable action contrasts.

The Fixed-8 scope does not include a separate role-binding leaf. A claim whose
sole error is who performed an otherwise supported action is not constructed.

## 7. Event

### 7.1 TemporalRelation

**Fact kind:** `temporal_relation`  
**Signature:** `TemporalRelation(event_a, order, event_b)`  
**Conflict slot:** `order`

Use when both component events are supported but their relative temporal order is wrong. The core operators are `before`, `after`, and a clearly decidable simultaneous-versus-sequential contrast, all normalized to conflict slot `order`.

Causal claims are outside Fixed-8 and are not remapped to TemporalRelation.

## 8. Camera

### 8.1 CameraPredicate

**Fact kind:** `camera_predicate`  
**Signature:** `CameraPredicate(camera_event, predicate, interval)`  
**Conflict slot:** `camera_predicate`

Use only for a real, temporally bounded camera or editing change that is
directly observable in the original video: pan left/right, tilt up/down, zoom
in/out, cut, focus change, framing change, or viewpoint change. The supported
source fact must identify the actual change and its evidence interval.

A CameraPredicate counterfactual may either assert a different incompatible
camera/edit change or deny the observed change with `no_camera_change`.
`stationary` is not an eligible supported source fact because the construction
target is an actual change, not the absence of one.

Hard boundaries:

- one actor or object moving, changing image position, or changing apparent
  size is not sufficient camera evidence; require global-frame, parallax,
  optical, focus, framing, viewpoint, or edit evidence;
- actor or object motion is ActionPredicate;
- a static spatial arrangement is StaticRelation;
- a unary visual property is AttributeValue;
- an entity appearing or disappearing through scene action is
  EntityExistence; appearance/disappearance caused by a shot cut is an editing
  event here;
- relative order between grounded events is TemporalRelation;
- a semantic scene change alone is not a camera or editing operation.

CameraPredicate errors therefore either fabricate a camera/edit change that
does not match the original video or deny a camera/edit change that the
original video actually contains.

## 9. Deterministic resolver

| fact kind | leaf | conflict slot |
|---|---|---|
| entity_existence | EntityExistence | existence |
| entity_category | EntityCategory | category |
| entity_quantity | EntityQuantity | count |
| attribute_value | AttributeValue | attribute_value |
| static_relation | StaticRelation | relation_predicate |
| action_predicate | ActionPredicate | predicate |
| temporal_relation | TemporalRelation | order |
| camera_predicate | CameraPredicate | camera_predicate |

## 10. Explicit Fixed-8 exclusions

The following are not construction targets and are not silently coerced into another leaf:

- entity reference or cross-shot coreference;
- action-role binding;
- causal relation;
- subjective intent or atmosphere;
- facts that remain natively undecidable after the bounded Gemini retry.

This explicit scope preserves the empirically validated category boundaries.

---

# VideoHALO Core System Prompt 3.7 Fixed-8

You are a VideoHALO surrogate expert. Use only the original full-modal video supplied to Gemini Enterprise through its immutable private Google Cloud Storage URI and the frozen Fixed-8 taxonomy.

## Evidence rules

1. File names, prompts, target labels, mutation metadata, previous model judgments, and model confidence are not evidence.
2. No external ASR, OCR, object tracker, sound classifier, dense-frame packet, or human review is available.
3. If the original video is not decisive after one focused native retry, return `insufficient`.
4. Do not force an adequately observed but non-Fixed-8 conflict into an existing leaf; reject it from construction.
5. Every build role that makes an original-video evidence decision must inspect
   the original video at high media resolution. A low-resolution pass is not
   sufficient evidence for opportunity, fact, or final-pair acceptance.

## Fixed-8 leaves

- EntityExistence — `existence`
- EntityCategory — `category`
- EntityQuantity — `count`
- AttributeValue — `attribute_value`
- StaticRelation — `relation_predicate`
- ActionPredicate — `predicate`
- TemporalRelation — `order`
- CameraPredicate — `camera_predicate`

## Build-mode contract

Before extracting a source fact, load the frozen taxonomy-first leaf-search
plan as prior memory. Scan all eight leaves independently and return one
opportunity decision for each leaf: `constructible`, `not_constructible`, or
`uncertain`. A constructible opportunity requires a decisive original-video
interval, a stable atomic anchor, and a viable one-slot counterfactual.

Extract facts only from constructible opportunities and keep at most one best
fact per leaf per video. Never begin with a salience-first fact list and assign
leaves afterwards. Dataset distribution is descriptive: no desired count may
change a leaf definition, create evidence, relabel a fact, or force a sample.

For every accepted pair:

- `answer` is fully supported by the same original-video interval. Captioning
  and non-polar VideoQA copy the complete natural-language source fact accepted
  by high-thinking Fact Reflection verbatim. EntityExistence VideoQA may only
  add the question-required `Yes,` or `No,` polarity frame while preserving the
  exact supported existence proposition;
- `counterfactual_answer` is contradicted;
- exactly one atomic fact changes;
- exactly one typed slot changes;
- the resolved leaf equals the planned leaf;
- all non-target facts remain supported;
- output only the direct pair schema.

The question is selected before realization from the frozen task-specific
template bank. Captioning and VideoQA both use multiple deterministic
templates. Template variation may change wording only; it must not change the
source fact, target leaf, conflict slot, time scope, or canonical anchors.

The positive and counterfactual answers must both match the selected question
family. EntityExistence VideoQA uses explained, self-contained Yes/No
sentences with polarity matching each respective normalized fact. All other
VideoQA leaves use direct complete-sentence answers and must not begin with
Yes/No. Captioning uses complete observation sentences. Both sides of a pair
must use the same grammatical frame while differing only in the frozen target
slot.

### CameraPredicate boundary

CameraPredicate is reserved for a real, temporally bounded camera or editing
change in the original video: pan, tilt, zoom, cut, focus change, framing
change, or viewpoint change. An accepted source fact must positively identify
that observed change. `stationary` is not an eligible supported source fact.
The counterfactual may assert a different incompatible change or use
`no_camera_change` to deny the observed change.

Do not infer camera motion merely because one actor or object moves, changes
image position, or changes apparent size. Require global-frame, parallax,
optical, focus, framing, viewpoint, or edit evidence. Object motion is
ActionPredicate; static object arrangement is StaticRelation; unary appearance
is AttributeValue; event order is TemporalRelation; semantic scene change alone
is not CameraPredicate.

Do not expose private chain-of-thought. Return compact evidence summaries only.

---

# Multimodal Video Registration

VideoHALO 3.7 retains Gemini-native minimal registration while using the
Enterprise ADC and private-GCS production boundary.

## Canonical local registration

For each source video:

```text
resolve source → SHA-256 → MIME/container check → ffprobe stream census
→ short decode smoke test → canonical timeline → VideoManifest
```

The manifest preserves video, speech audio, non-speech audio, on-screen text capability, camera/editing capability, and container metadata. Registration does not semantically transcribe or interpret the media.

## Provider materialization

The original compatible file is uploaded once to a private Google Cloud
Storage bucket in the same approved project. The immutable `gs://` URI is
reused by the Taxonomy Planner, Fact Extractor, Fact Reflection, and Candidate
Reflection. Object identity is bound to the local SHA-256, object metadata,
generation, and canonical manifest. Temporary Gemini Files API uploads are not
part of the production runtime.

## Authentication and access

Gemini inference uses Application Default Credentials and IAM. API-key
environment variables are rejected by the production runtime. The runner uses
the global Enterprise endpoint and a least-privilege principal with model-use
and bucket-scoped object permissions only. GCS objects remain private and are
never converted to public HTTP URLs.

## Bounded native retry

One focused retry may narrow the time interval or raise native media resolution for a fine visual detail. If the fact remains undecidable, it is excluded from construction.

## No external semantic tools

The baseline forbids external ASR, OCR, speaker diarization, sound-event detection, object tracking, dense-frame extraction, slow motion, and contact sheets.

---

# Memory System Design

## Working memory

Each LangGraph thread stores per-video or per-item intermediate state:

- VideoManifest and provider lease;
- proposed and verified facts;
- eligibility records;
- planned mutation;
- realized answer pair;
- backparse and GraphDiff;
- reflection reports;
- direct-output record;
- retry counters and error codes.

A checkpointer persists this state for recovery. Working memory expires according to run policy and is never injected into unrelated samples.

## Long-term memory

Long-term memory is read-only, versioned policy:

- Fixed-8 taxonomy;
- resolver mapping;
- mutation operators;
- system prompt;
- evidence policy;
- output schemas;
- model-role contracts.

No human audit history or sample-specific judgment is stored as long-term memory.

## Audit traces

Engineering traces may be retained for debugging, but the published pair output contains only the direct nine-field contract. Audit traces are not a hidden scoring reference and are not required by downstream users.

---

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

---

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

---

# Direct Output Data Contracts

## 1. Build-mode pair record

The normative build output exactly follows the uploaded `public_probe_items` shape. One JSONL line is one supported–counterfactual pair.

Required top-level fields:

```text
schema_version
pair_id
media
task_type
question
answer
counterfactual_answer
leaf_label
conflict_slot
```

### Meaning

- `answer`: fully supported statement.
- `counterfactual_answer`: the same fact pattern with one contradicted slot.
- `leaf_label`: the counterfactual’s Fixed-8 leaf.
- `conflict_slot`: the exact normalized slot for that leaf.

For VideoQA, answer form is part of the contract: EntityExistence requires
explained Yes/No sentences whose polarity matches each side's normalized fact;
all other leaves require direct complete-sentence answers without a Yes/No
prefix. Captioning requires complete observation sentences. The supported and
counterfactual answers must use the same question-compatible grammatical frame.

### Fixed mapping

```text
EntityExistence  → existence
EntityCategory   → category
EntityQuantity   → count
AttributeValue   → attribute_value
StaticRelation   → relation_predicate
ActionPredicate  → predicate
TemporalRelation → order
CameraPredicate  → camera_predicate
```

### Compatibility

The schema identifier remains:

```text
videohalo_probe_pair_sample_fixed8_3.6.1
```

This is intentional so the new implementation can append records compatible with the existing JSONL file.

## 2. Internal artifacts

FactGraphs, reflection reports, mutation plans, and GraphDiff are implementation artifacts. They are not embedded in the public pair record and are not required for model evaluation.

---

# Dataset Planning and Faithful Relative Allocation

VideoHALO builds only from verified facts found in source videos after the
Taxonomy Planner has scanned all eight leaves. It does not force equal counts
across leaves or Task x Leaf cells.

## Constraints

- one source fact is used once;
- one video contributes at most one pair to the same leaf;
- profile-defined per-video pair caps apply;
- near-duplicate videos are separated where possible;
- task, source, and question-template diversity are preserved;
- insufficient or out-of-scope facts never fill a quota.

## Selection priority

The planner selects only real, independently verified supply and applies a
deterministic tie-break under the per-video cap. Leaf counts are an observed
output, not an optimization requirement. A real verified claim from a clearly
underrepresented leaf may be selected first, but no target may alter taxonomy
boundaries, opportunity decisions, FactBank contents, mutation semantics, or
verifier judgments. `probe_build` uses a smaller total-pair target;
`evalbench_build` uses a larger one.

---

# Deployment, Testing, and Operations

## Required tests

1. Schema tests for pair outputs.
2. Resolver tests for all eight leaf/slot mappings.
3. Negative tests proving removed fact kinds cannot enter build output.
4. Mutation property tests: one fact, one slot, one contradiction.
5. High-thinking fact and candidate reflection tests.
6. JSONL append idempotency and duplicate-pair rejection.
7. Private-GCS object identity, idempotent reuse, and generation tests.
8. ADC/IAM/project failure circuit-breaker and secret-redaction tests.
9. Smooth cross-worker request pacing tests.

## CLI

```text
videohalo register --input videos.jsonl
videohalo build --profile probe_build --output public_probe_items.jsonl
videohalo build --profile evalbench_build --output public_evalbench_pairs.jsonl
videohalo validate --input public_probe_items.jsonl
```

## Observability

Record API latency, retries, token usage, candidate rejection reasons, per-leaf yield, and direct-output append status. Do not record hidden reasoning text as dataset content.

## Production compliance guardrails

- Use only a Google-approved, billing-enabled project; never switch projects to
  circumvent a suspension or enforcement action.
- Use ADC/IAM and private GCS. Reject API-key variables in production.
- Run one text preflight and one video smoke before enabling multiple workers.
- Smooth requests across workers. Do not send second-level traffic spikes.
- Retry only transient 429/5xx capacity failures with bounded exponential
  backoff.
- Any 401 or project/auth/billing/IAM 403 opens a process-wide circuit and
  stops uploads, inference, retries, and automatic resume.
- Redact API keys and bearer tokens before writing events, errors, or status.
- Preserve Google safety filters. Safety-blocked or policy-ineligible media is
  skipped rather than retried or routed around the filter.

---

# Implementation Migration from 3.6

## Delete

```text
graphs/review_packaging.py
graphs/human_audit_unlock.py
services/review_metrics.py
services/machine_human_alignment.py
schemas/expert_*_review*.json
schemas/human_audit_report.schema.json
schemas/review_difference_record.schema.json
schemas/batch_unlock_record.schema.json
examples/sample_*review*.json
examples/sample_human_audit_report.json
examples/sample_batch_unlock_record.json
```

## Replace in the batch orchestrator

Remove:

```text
freeze_machine_candidate_batch
package_blind_review_automatic
human audit refs
batch unlock refs
private machine-reference manifest
```

Add:

```text
project_fixed8_pair_record
append_pair_jsonl_atomic
validate_pair_id_uniqueness
```

## Update taxonomy code

The resolver dictionary must contain exactly eight entries. Removed fact kinds must raise `Fixed8OutOfScopeError` rather than being remapped.

## Update public field filtering

`leaf_label` and `conflict_slot` are now intentional public fields. The old leakage policy that treated target leaf as private does not apply to the direct pair dataset contract.

## Preserve

- native stream registration;
- immutable private-GCS object reuse through Enterprise ADC;
- high-thinking Fact Reflection;
- one-slot mutation;
- backparse and GraphDiff;
- high-thinking Candidate Reflection;
- working memory and read-only policy memory;
