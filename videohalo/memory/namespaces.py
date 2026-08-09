"""Stable non-filesystem identifiers used in persisted state."""


def core_memory_uri(asset_id: str, version: str) -> str:
    return "memory://core/%s/%s" % (asset_id, version)


def media_uri(video_id: str, stream_or_variant: str) -> str:
    return "media://%s/%s" % (video_id, stream_or_variant)


def artifact_uri(dataset_id: str, artifact_type: str, sha256: str) -> str:
    return "artifact://%s/%s/%s" % (dataset_id, artifact_type, sha256)
