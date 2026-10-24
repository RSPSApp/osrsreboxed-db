"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Tests for module: docs/drops-json

Copyright (c) 2026, Toby Wisener

###############################################################################
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
###############################################################################
"""

import json
from pathlib import Path

import config
import validator


def _load(file_name: str):
    """Load one of the generated drops dump files."""
    with open(Path(config.DOCS_DROPS_PATH / file_name), "r", encoding="utf-8") as f:
        return json.load(f)


def test_drops_docs_json_exists_and_valid():
    """Ensure the drops dump files are generated into docs."""
    for file_name in ("npc-drops.json", "subtables.json", "unresolved-items.json"):
        assert Path(
            config.DOCS_DROPS_PATH / file_name
        ).exists(), f"docs/drops-json/{file_name} must exist"

    npc_drops = _load("npc-drops.json")
    assert set(npc_drops) == {"meta", "tables", "npcs"}
    assert npc_drops["meta"]["table_count"] == len(npc_drops["tables"])
    assert npc_drops["meta"]["npc_count"] == len(npc_drops["npcs"])
    assert isinstance(_load("unresolved-items.json"), list)


def test_drops_schema_validation():
    """Validate every drop table in npc-drops.json against schema."""
    # Read in the drops schema file
    path_to_schema = Path(config.DATA_SCHEMAS_PATH / "schema-drops.json")
    with open(path_to_schema, "r", encoding="utf-8") as f:
        schema = json.loads(f.read())

    # Validator object with schema attached
    v = validator.MyValidator(schema)

    # Validate each drop table in the dump
    for table_id, table in _load("npc-drops.json")["tables"].items():
        assert v.validate(table), (
            f"Schema validation failed for drop table: {table_id}. "
            f"Errors: {v.errors}"
        )


def test_npcs_reference_known_tables():
    """Every NPC points at drop tables that exist in the same file."""
    npc_drops = _load("npc-drops.json")
    tables = npc_drops["tables"]

    for npc_id, npc in npc_drops["npcs"].items():
        assert npc["npc_id"] == int(npc_id)
        # Explicitly excluded encounter variants retain an empty no-loot mapping.
        assert isinstance(npc["tables"], list)
        for table_id in npc["tables"]:
            assert (
                table_id in tables
            ), f"npc {npc_id} references unknown table {table_id}"


def test_shared_tables_are_exported():
    """Every shared table a drop table rolls into is defined in subtables.json."""
    npc_drops = _load("npc-drops.json")
    subtables = _load("subtables.json")

    for table_id, table in npc_drops["tables"].items():
        for entry in table["entries"]:
            shared_table = entry.get("shared_table")
            # The empty key is a multi-roll herb table, which has no single
            # shared table to point at.
            if shared_table:
                assert (
                    shared_table in subtables
                ), f"drop table {table_id} rolls undefined shared table {shared_table}"


def test_generated_quantities_keep_source_conditions_and_discrete_alternatives():
    dump = _load("npc-drops.json")
    rows = [
        row
        for table in dump["tables"].values()
        for row in table["entries"] + table["tertiary"]
    ]
    alternatives = [row for row in rows if "quantity_alternatives" in row]
    counts = {}
    for row in alternatives:
        assert row["quantity"] == row["quantity_alternatives"][0]["quantity"]
        kind = (
            "unknown"
            if row["quantity_selection"] == "unknown"
            else row["quantity_alternatives"][1]["condition"]["type"]
        )
        counts[kind] = counts.get(kind, 0) + 1
    assert counts == {
        "perfect_kill": 99,
        "bounty_task": 2,
        "preferred_method": 3,
        "unknown": 12,
    }
    assert all("quantity" in row for row in rows if "quantity_raw" in row)


def test_quantity_export_preserves_npc_mappings_and_unrelated_reward_paths():
    dump = _load("npc-drops.json")
    assert len(dump["tables"]) == 1112
    assert len(dump["npcs"]) == 3092
    assert {npc_id for npc_id, npc in dump["npcs"].items() if not npc["tables"]} == {
        "8058",
        "8060",
        "13686",
    }
    for npc_id in ("8059", "8061"):
        assert dump["npcs"][npc_id]["tables"] == ["vorkath"]
    assert dump["npcs"]["13685"]["tables"] == ["amoxliatl"]
    # Preserve this repository's existing export. TSPS's older import has
    # thirty Mimic rows and only one Bandit champion row; importing the complete
    # canonical dump requires its existing reward/eligibility consumer paths.
    assert len(dump["tables"]["the_mimic"]["entries"]) == 1
    assert len(dump["tables"]["the_mimic_2"]["entries"]) == 1
    assert len(dump["tables"]["bandit_champion"]["entries"]) == 3
    occult = next(
        row
        for row in dump["tables"]["thermonuclear_smoke_devil"]["entries"]
        if row.get("item_id") == 12002
    )
    assert [occult["weight"], occult["out_of"]] == [1, 350]


def test_generated_nex_keeps_two_paired_supply_slots():
    nex = _load("npc-drops.json")["tables"]["nex"]
    assert nex["main_max_roll"] == 12
    assert sorted(
        (row["item_id"], bonus["item_id"])
        for row in nex["entries"]
        for bonus in row.get("bonus_drops", [])
    ) == [(385, 2434), (6685, 3024)]


def test_generated_god_wars_variant_accesses_and_coin_remainders():
    dump = _load("npc-drops.json")
    expected = {
        "commander_zilyana": (330, "31.2/127"),
        "general_graardor": (336, "31.7/127"),
        "kril_tsutsaroth": (396, "36.7/127"),
        "kreearra": (480, "43.7/127"),
    }
    for table_id, (weight, published) in expected.items():
        table = dump["tables"][table_id]
        assert table["main_max_roll"] == 1524
        assert [
            (e["shared_table"], e["weight"], e["out_of"])
            for e in table["entries"]
            if e.get("shared_table")
        ] == [("gwdRareDrop", 96, 1524), ("gwdGem", 24, 1524)]
        assert [
            (e["item_id"], e["weight"], e["published_rarity"])
            for e in table["entries"]
            if e.get("weight_basis") == "remainder"
        ] == [(995, weight, published)]
    shared = _load("subtables.json")
    for key in ["gwdRareDrop", "gwdGem", "gwdMegaRare"]:
        assert shared[key]["wiki_page"] == "God Wars Dungeon-variant rare drop table"
        assert (
            sum(int(e["rarity_raw"].split("/")[0]) for e in shared[key]["entries"])
            == 128
        )
