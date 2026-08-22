# Changelog: VideoHALO 3.7 -> 3.8 Agent Architecture

VideoHALO 3.8 standardizes the construction runtime around exactly six agents,
two shared memory layers, and four structured-output subtasks.

- Canonical agents: `planner_agent`, `extraction_agent`, `reflection_agent`,
  `generation_agent`, `verification_agent`, and `monitor_agent`.
- Memory layers: `system_cognitive_memory` and `category_memory`.
- Public LangGraph stages: `hallucination_category_retrieval`,
  `fact_extraction_and_reflection`,
  `generation_and_verification_of_adversarial_pairs`, and
  `comprehensive_reliability_validation`.
- Internal report fields now use `reflection_*`, `monitor_*`, and `agent_role`.
- The orchestration module is now `four_stage_orchestrator.py`.

The frozen `VHal-Fixed8-3.7` taxonomy, one-fact/one-slot semantics, and public
`videohalo_probe_pair_sample_fixed8_3.6.1` nine-field output contract are
unchanged.
