import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]


def test_slayer_tasks_dump():
    dump = json.loads((ROOT / "docs/slayer-tasks.json").read_text())
    schema = json.loads((ROOT / "data/schemas/schema-slayer-tasks.json").read_text())
    dialogues = json.loads((ROOT / "docs/npc-dialogue-index.json").read_text())
    jsonschema.validate(dump, schema)
    assert len(dump) >= 10
    assert {entry["name"] for entry in dump.values()} >= {
        "Turael", "Spria", "Krystilia", "Konar quo Maten", "Mortimer"
    }
    assert all(entry["dialogue"] == entry["name"] for entry in dump.values())
    assert all(
        any(item["page"] == f"Transcript:{entry['dialogue']}" for item in dialogues[npc_id])
        for npc_id, entry in dump.items()
    )
    assert all(task["npc_names"] for entry in dump.values() for task in entry["tasks"])
    assert any("locations" in task for task in dump["8623"]["tasks"])
