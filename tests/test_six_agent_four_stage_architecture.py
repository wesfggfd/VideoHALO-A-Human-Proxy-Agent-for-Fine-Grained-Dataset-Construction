from videohalo.agents import AGENT_ROLES
from videohalo.contracts.stage_outputs import (
    COMPREHENSIVE_RELIABILITY_VALIDATION,
    FACT_EXTRACTION_AND_REFLECTION,
    GENERATION_AND_VERIFICATION,
    HALLUCINATION_CATEGORY_RETRIEVAL,
    STAGE_PRODUCERS,
    make_stage_output,
)
from videohalo.memory import (
    CATEGORY_MEMORY,
    MEMORY_LAYERS,
    SYSTEM_COGNITIVE_MEMORY,
    DualLayerMemory,
)


def test_exact_six_agent_contract():
    assert AGENT_ROLES == (
        "planner_agent",
        "extraction_agent",
        "reflection_agent",
        "generation_agent",
        "verification_agent",
        "monitor_agent",
    )
    assert STAGE_PRODUCERS == {
        HALLUCINATION_CATEGORY_RETRIEVAL: ("planner_agent",),
        FACT_EXTRACTION_AND_REFLECTION: (
            "extraction_agent",
            "reflection_agent",
        ),
        GENERATION_AND_VERIFICATION: (
            "generation_agent",
            "verification_agent",
        ),
        COMPREHENSIVE_RELIABILITY_VALIDATION: ("monitor_agent",),
    }


def test_every_agent_contributes_to_both_memory_layers():
    memory = DualLayerMemory()
    for role in AGENT_ROLES:
        memory.contribute(
            agent_role=role,
            stage="test_stage",
            video_id="video_001",
            categories=("AttributeValue",),
            content={"accepted": True},
        )
    snapshot = memory.snapshot(
        ("AttributeValue",), video_id="video_001", limit=16
    )
    assert MEMORY_LAYERS == (SYSTEM_COGNITIVE_MEMORY, CATEGORY_MEMORY)
    assert {
        item["agent_role"]
        for item in snapshot[SYSTEM_COGNITIVE_MEMORY]
    } == set(AGENT_ROLES)
    assert {
        item["agent_role"]
        for item in snapshot[CATEGORY_MEMORY]["AttributeValue"]
    } == set(AGENT_ROLES)


def test_structured_stage_outputs_form_a_four_stage_chain():
    outputs = []
    for stage in STAGE_PRODUCERS:
        output = make_stage_output(
            stage=stage,
            video_id="video_001",
            payload={"ok": True},
            upstream=outputs[-1:],
            memory_snapshot={
                SYSTEM_COGNITIVE_MEMORY: [],
                CATEGORY_MEMORY: {},
            },
        )
        outputs.append(output)
    assert [item["stage"] for item in outputs] == list(STAGE_PRODUCERS)
    assert outputs[0]["upstream_stages"] == []
    assert outputs[-1]["upstream_stages"] == [
        GENERATION_AND_VERIFICATION
    ]
