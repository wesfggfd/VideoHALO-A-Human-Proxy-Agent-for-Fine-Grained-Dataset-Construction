# VideoHALO 3.8 Fixed-8 runtime

VideoHALO has one semantic operation, `build`, implemented by four public
LangGraph stages and six canonical agents:

1. `hallucination_category_retrieval` — `<planner_agent>`;
2. `fact_extraction_and_reflection` — `<extraction_agent>` and
   `<reflection_agent>`;
3. `generation_and_verification_of_adversarial_pairs` —
   `<generation_agent>` and `<verification_agent>`; and
4. `comprehensive_reliability_validation` — `<monitor_agent>`.

Each stage consumes the previous stage's versioned structured output. Every
agent contributes to `system_cognitive_memory` and `category_memory`. The
memory and stage envelopes are internal audit artifacts; an accepted sample is
still projected directly to the exact nine-field JSONL contract.

There is no freeze, review-package, human-audit, private-reference, agreement,
human-gold, or unlock stage in the 3.8 runtime. `EntityReference`,
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
