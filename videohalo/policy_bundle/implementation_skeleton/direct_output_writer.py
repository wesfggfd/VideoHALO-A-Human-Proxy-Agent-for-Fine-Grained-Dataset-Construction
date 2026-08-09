import json
from pathlib import Path

def existing_pair_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                ids.add(json.loads(line)["pair_id"])
    return ids

def append_pair_jsonl(path: Path, record: dict) -> None:
    if record["pair_id"] in existing_pair_ids(path):
        raise ValueError(f"Duplicate pair_id: {record['pair_id']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
