"""Test that SKILL.md references all exist and are reachable."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_skill_reference_paths_exist():
    src = read("SKILL.md")
    paths = sorted(set(re.findall(r"`(references/[A-Za-z0-9_./*-]+)`", src)))

    assert paths, "SKILL.md should route through references/"
    for path in paths:
        if "*" in path:
            matches = sorted(ROOT.glob(path))
            assert matches, f"SKILL.md glob has no matches: {path}"
            assert all(m.is_file() for m in matches), f"SKILL.md glob matched non-files: {path}"
        else:
            assert (ROOT / path).is_file(), f"SKILL.md references missing file: {path}"


def test_failure_map_uses_repo_relative_links():
    src = read("evals/failure-map.md")
    forbidden = ["/Users/", "file://", "D:/", "/D:/"]
    for pattern in forbidden:
        assert pattern not in src, f"failure-map.md should not contain: {pattern}"


def test_rubric_schema_exists_and_valid():
    import json
    schema_path = ROOT / "evals" / "rubric.schema.json"
    assert schema_path.exists(), "rubric.schema.json must exist"
    schema = json.loads(schema_path.read_text())
    assert "properties" in schema
    assert "scores" in schema["properties"]


def test_governance_cases_csv_exists():
    csv_path = ROOT / "evals" / "governance-cases.csv"
    assert csv_path.exists(), "governance-cases.csv must exist"
    lines = csv_path.read_text().strip().splitlines()
    assert len(lines) >= 2, "CSV must have header + at least 1 case"


def test_contract_checks_importable():
    import sys
    sys.path.insert(0, str(ROOT / "evals"))
    from contract_checks import validate_claim_json, find_conflicts
    assert callable(validate_claim_json)
    assert callable(find_conflicts)
