"""Export NPC status immunities directly from the canonical monster builder.

This contract is independent of combat stats: consumers can refresh status rules
without replacing a combat-stat snapshot from a different source revision.
"""

import argparse
import json
from pathlib import Path

import config
from builders.monsters.builder import Builder


def build_status_immunities(builder=None):
    builder = builder or Builder()
    result = {}
    for monster_id in sorted(builder._get_entity_id_list(), key=int):
        monster = builder._build_entity(monster_id)
        valid, _ = monster.preprocessing()
        if not valid:
            continue
        monster.populate_monster()
        row = monster.monster_dict
        result[str(row["id"])] = {
            "name": row["name"],
            "immune_poison": row["immune_poison"],
            "immune_venom": row["immune_venom"],
        }
    return {"schema_version": 1, "npcs": result}


def export_status_immunities(output):
    data = build_status_immunities()
    with Path(output).open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(data, indent=2) + "\n")
    return len(data["npcs"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=config.DOCS_PATH / "npc-status-immunities.json"
    )
    args = parser.parse_args()
    print(f"Exported {export_status_immunities(args.output)} NPC status records.")
