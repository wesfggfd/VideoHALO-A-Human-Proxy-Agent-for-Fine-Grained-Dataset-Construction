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
