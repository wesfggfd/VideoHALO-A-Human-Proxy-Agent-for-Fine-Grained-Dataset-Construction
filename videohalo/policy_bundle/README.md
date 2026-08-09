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
