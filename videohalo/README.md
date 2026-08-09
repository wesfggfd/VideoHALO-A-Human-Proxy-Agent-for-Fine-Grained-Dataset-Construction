# VideoHALO 3.7 Fixed-8 runtime

VideoHALO has one semantic operation:

1. `build`: discover source facts, apply one high-thinking fact reflection,
   construct a one-slot counterfactual, apply one high-thinking pair
   reflection, then append the
   exact nine-field pair record directly to JSONL.

There is no freeze, review-package, human-audit, private-reference, agreement,
human-gold, or unlock stage in the 3.7 runtime. `EntityReference`,
`ActionBinding`, and `CausalRelation` are never remapped into retained leaves.

```text
python -m videohalo policy-validate
python -m videohalo register --input videos.jsonl
python -m videohalo build --input candidates.jsonl --profile probe_build --output public_probe_items.jsonl
python -m videohalo validate --input public_probe_items.jsonl
```

`build --input` supports either raw source-video JSONL records
(`video_id`, `source_path`, `task_type`) for the full Gemini-native workflow,
or internal preverified candidate envelopes for deterministic resume/migration.

The frozen normative package is embedded in `policy_bundle`.
