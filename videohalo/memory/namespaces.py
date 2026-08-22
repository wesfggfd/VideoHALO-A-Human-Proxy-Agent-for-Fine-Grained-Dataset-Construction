"""Stable non-filesystem identifiers used in persisted state."""

SYSTEM_COGNITIVE_MEMORY_LAYER = "system_cognitive_memory"
CATEGORY_MEMORY_LAYER = "category_memory"


def core_memory_uri(asset_id: str, version: str) -> str:
    return "memory://%s/%s/%s" % (
        SYSTEM_COGNITIVE_MEMORY_LAYER,
        asset_id,
        version,
    )


def category_memory_uri(category: str, asset_id: str, version: str) -> str:
    return "memory://%s/%s/%s/%s" % (
        CATEGORY_MEMORY_LAYER,
        category,
        asset_id,
        version,
    )


def media_uri(video_id: str, stream_or_variant: str) -> str:
    return "media://%s/%s" % (video_id, stream_or_variant)


def artifact_uri(dataset_id: str, artifact_type: str, sha256: str) -> str:
    return "artifact://%s/%s/%s" % (dataset_id, artifact_type, sha256)
