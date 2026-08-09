from datetime import datetime, timedelta, timezone

import pytest

from videohalo.media.lease_registry import ProviderLeaseRegistry
from videohalo.stores.jsonl import append_pair_jsonl, read_jsonl


def test_jsonl_append_and_duplicate_pair_rejection(tmp_path, candidate):
    from videohalo.graphs.pair_construction import project_direct_record

    path = tmp_path / "pairs.jsonl"
    record = project_direct_record(candidate)
    append_pair_jsonl(path, record)
    assert read_jsonl(path) == [record]
    with pytest.raises(ValueError, match="Duplicate pair_id"):
        append_pair_jsonl(path, record)
    assert read_jsonl(path) == [record]


def test_provider_lease_expiry_requires_reupload(tmp_path):
    registry = ProviderLeaseRegistry(tmp_path / "leases.sqlite")
    now = datetime.now(timezone.utc)
    active = {
        "state": "active",
        "expires_at": (now + timedelta(hours=5)).isoformat(),
    }
    expiring = {
        "state": "active",
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
    }
    expired = {
        "state": "expired",
        "expires_at": (now - timedelta(minutes=1)).isoformat(),
    }
    assert registry.reusable(active, now=now)
    assert not registry.reusable(expiring, now=now)
    assert not registry.reusable(expired, now=now)
