from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / ".codex"
    / "skills"
    / "acceleration-workflow"
    / "scripts"
    / "coordination_store.py"
)


def load_coordination_store_module():
    spec = importlib.util.spec_from_file_location("coordination_store", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_lane_registry_and_queue_include_qa_lane() -> None:
    coordination_store = load_coordination_store_module()
    plan_text = """
## 3. Lane Registry

| Lane | Branch | Coverage | Status | Owner Scope | Review Boundary |
| --- | --- | --- | --- | --- | --- |
| AL01 | `feat/al-run-core-events` | R3.1, E3.1 | claimed | Run truth | Run truth |
| QA | `test/al-regression-hardening` | V6.1, V6.4, L6.1 | planned | Regression harness | QA |

## 4. Shared Ownership

irrelevant

## 7. Lane Queues

| Lane | Queue |
| --- | --- |
| AL01 | R3.1 -> E3.1 |
| QA | V6.1 -> V6.4 -> L6.1 |
"""

    registry = coordination_store.parse_lane_registry(plan_text)
    queues = coordination_store.parse_lane_queues(plan_text)

    assert registry["QA"] == {
        "branch": "test/al-regression-hardening",
        "tasks": ["V6.1", "V6.4", "L6.1"],
    }
    assert queues["QA"] == ["V6.1", "V6.4", "L6.1"]
