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
