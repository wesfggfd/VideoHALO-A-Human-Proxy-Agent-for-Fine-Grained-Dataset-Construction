from concurrent.futures import ThreadPoolExecutor

from videohalo.stores.artifacts import LocalArtifactStore


def test_concurrent_identical_artifact_write_is_idempotent(tmp_path):
    store = LocalArtifactStore(tmp_path, "three_worker_dataset")
    value = {
        "schema_version": "test",
        "leaves": ["EntityExistence", "CameraPredicate"],
    }

    with ThreadPoolExecutor(max_workers=3) as executor:
        references = list(
            executor.map(
                lambda _: store.put_json("leaf_search_plan", value),
                range(30),
            )
        )

    assert len({reference.sha256 for reference in references}) == 1
    assert store.read_json(references[0]) == value
    files = list(
        (tmp_path / "three_worker_dataset" / "leaf_search_plan").glob("*")
    )
    assert [path.suffix for path in files] == [".json"]
