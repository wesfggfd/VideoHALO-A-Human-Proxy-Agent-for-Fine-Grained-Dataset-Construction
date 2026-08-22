from langgraph.graph import END, START, StateGraph

STAGES = (
    "hallucination_category_retrieval",
    "fact_extraction_and_reflection",
    "generation_and_verification_of_adversarial_pairs",
    "comprehensive_reliability_validation",
)


def build_dataset_construction_graph(stage_functions: dict):
    """Compose four structured-output stages supplied by the runtime."""
    if set(stage_functions) != set(STAGES):
        raise ValueError("All four VideoHALO stage functions are required")
    graph = StateGraph(dict)
    for stage in STAGES:
        graph.add_node(stage, stage_functions[stage])
    graph.add_edge(START, STAGES[0])
    for left, right in zip(STAGES, STAGES[1:]):
        graph.add_edge(left, right)
    graph.add_edge(STAGES[-1], END)
    return graph
