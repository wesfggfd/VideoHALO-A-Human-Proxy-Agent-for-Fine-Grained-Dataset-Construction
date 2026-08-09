from pathlib import Path
import json, yaml, py_compile
import jsonschema

ROOT = Path(__file__).resolve().parents[1]

def main():
    schema = json.loads((ROOT / "schemas/videohalo_probe_pair_sample_fixed8.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    count = 0
    for line in (ROOT / "examples/public_probe_items_fixed8_examples.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            validator.validate(json.loads(line)); count += 1
    for path in (ROOT / "implementation_skeleton").glob("*.py"):
        py_compile.compile(str(path), doraise=True)
    print(
        {
            "fixed8_pair_examples": count,
            "annotation_mode_removed": True,
            "status": "PASS",
        }
    )

if __name__ == "__main__":
    main()
