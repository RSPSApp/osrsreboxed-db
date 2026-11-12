"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Tests for module: scripts/drops

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

import pytest

from scripts.drops import drops_tables, drops_wikitext, update


def test_cyclops_floor_headings_split_the_published_drop_versions():
    text = update.load_monster_wikitext()["Cyclops"]
    top, basement = drops_wikitext.parse_all_drop_tables(text)
    assert top.npc_ids == [2463, 2464, 2465, 2466, 2467, 2468]
    assert basement.npc_ids == [2137, 2138, 2139, 2140, 2141, 2142]
    assert sum(drop.name == "Big bones" for drop in top.drops) == 1
    assert sum(drop.name == "Big bones" for drop in basement.drops) == 1
    assert "Dragon defender" not in {drop.name for drop in top.drops}
    assert "Dragon defender" in {drop.name for drop in basement.drops}


def test_source_date_epoch_keeps_full_exports_identical_across_build_days(
    tmp_path, monkeypatch
):
    import json
    from datetime import date

    class BuildDate:
        current = date(2026, 11, 1)

        @classmethod
        def today(cls):
            return cls.current

    monkeypatch.setattr(drops_tables, "date", BuildDate)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1793491200")
    dump = drops_tables.NpcDropsAggregator()
    first, second = tmp_path / "first", tmp_path / "second"
    dump.write(first, {}, 0)
    BuildDate.current = date(2026, 11, 2)
    dump.write(second, {}, 0)
    for filename in ("npc-drops.json", "subtables.json", "unresolved-items.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    assert (
        json.loads((second / "npc-drops.json").read_text())["meta"]["generated"]
        == "2026-11-01"
    )

    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    dump.write(second, {}, 0)
    assert (
        json.loads((second / "npc-drops.json").read_text())["meta"]["generated"]
        == "2026-11-02"
    )


def test_uniform_main_roll_counts_survive_export_without_repeating_tertiaries():
    source = """
{{Infobox Monster|id=7388}}
==Drops==
===100%===
{{DropsLine|name=Bones|quantity=1|rarity=Always}}
===Other===
{{DropsLine|name=Coins|quantity=8|rarity=24/128|rolls=3}}
{{DropsLine|name=Nothing|rarity=102/128|rolls=3}}
{{GemDropTable|2/128|rolls=3}}
===Tertiary===
{{DropsLine|name=Draconic visage|quantity=1|rarity=1/500}}
"""
    parsed = drops_wikitext.parse_all_drop_tables(source)[0]
    table = drops_tables.build_table_json(
        drops_tables.build_table_spec("Crushing hand", parsed, ITEMS)
    )
    assert table["rolls"] == 3
    assert table["main_max_roll"] == 128
    assert (
        next(row for row in table["entries"] if row.get("shared_table"))["weight"] == 2
    )
    assert next(row for row in table["entries"] if row.get("always"))["quantity"] == [
        1,
        1,
    ]
    assert table["tertiary"][0]["out_of"] == 500

    # A table-wide count must not repeat rows whose source says they roll once.
    mixed = drops_wikitext.parse_all_drop_tables(source.replace("|rolls=3", "", 1))[0]
    assert "rolls" not in drops_tables.build_table_json(
        drops_tables.build_table_spec("Mixed", mixed, ITEMS)
    )


class FakeItem:
    """Stand-in for an osrsreboxed item, so the tests need no item database."""

    def __init__(self, item_id, name, wiki_name=None, tradeable_on_ge=True):
        self.id = item_id
        self.name = name
        self.wiki_name = wiki_name or name
        self.tradeable_on_ge = tradeable_on_ge
        self.duplicate = False
        self.noted = False
        self.placeholder = False
        self.stacked = None


ITEMS = drops_tables.ItemIdLookup(
    [
        FakeItem(526, "Bones"),
        FakeItem(995, "Coins"),
        FakeItem(617, "Coins", "Coins (Shilo Village)", tradeable_on_ge=False),
        FakeItem(1163, "Rune full helm"),
        FakeItem(11286, "Draconic visage"),
        FakeItem(5072, "Bird nest", "Bird nest (egg) (Blue egg)"),
    ]
)


def test_pre_roll_keeps_its_own_denominator_after_pool_finalization():
    source = """{{Infobox Monster|id=1}}
==Drops==
===Pre-roll===
{{DropsLine|name=Rune full helm|quantity=1|rarity=1/350}}
===Other===
{{DropsLine|name=Coins|quantity=100|rarity=1/100}}
"""
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", table, ITEMS)
    )
    row = next(row for row in exported["entries"] if row.get("pre_roll"))
    assert [row["weight"], row["out_of"]] == [1, 350]
    assert row["rarity"] == 0.0028571
    assert exported["main_max_roll"] == 100


def test_unresolved_pre_roll_does_not_receive_an_invented_denominator():
    source = """{{Infobox Monster|id=1}}
==Drops==
===Pre-roll===
{{DropsLine|name=Rune full helm|quantity=1|rarity=Unpublished}}
===Other===
{{DropsLine|name=Coins|quantity=100|rarity=1/100}}
"""
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", table, ITEMS)
    )
    assert not any(row.get("pre_roll") for row in exported["entries"])


def test_cached_thermy_occult_pre_roll_exports_its_source_rate():
    import json
    from pathlib import Path

    pages = json.loads(
        (
            Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
        ).read_text(encoding="utf-8")
    )
    items = drops_tables.ItemIdLookup([FakeItem(12002, "Occult necklace")])
    table = drops_wikitext.parse_all_drop_tables(pages["Thermonuclear smoke devil"])[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Thermonuclear_smoke_devil", table, items)
    )
    row = next(row for row in exported["entries"] if row.get("item_id") == 12002)
    assert row["pre_roll"] is True
    assert [row["weight"], row["out_of"]] == [1, 350]


def test_explicit_postquest_table_keeps_the_quest_npc_as_an_empty_mapping():
    source = """{{Infobox Monster|id1=1|version1=Post-quest|id2=2|version2=Quest}}
==Drops==
===Other===
{{DropsTableHead|dropversion=Post-quest}}
{{DropsLine|name=Coins|quantity=100|rarity=1/100}}
{{DropsTableBottom}}
"""
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    assert table.npc_ids == [1]
    spec = drops_tables.build_table_spec("Test", table, ITEMS)
    dump = drops_tables.NpcDropsAggregator()
    dump.add(spec)
    assert dump.npcs[1]["tables"] == ["test"]
    assert dump.npcs[2]["tables"] == []


def test_cached_postquest_mapping_follows_source_versions_and_cache_ids():
    import json
    from pathlib import Path
    from osrsreboxed import items_api

    root = Path(__file__).parents[1]
    pages = json.loads(
        (root / "data/monsters/monsters-wiki-page-text.json").read_text(
            encoding="utf-8"
        )
    )
    cache = json.loads(
        (root / "data/monsters/monsters-cache-data.json").read_text(encoding="utf-8")
    )
    assert [
        (cache[str(i)]["name"], cache[str(i)]["combatLevel"]) for i in [13685, 13686]
    ] == [("Amoxliatl", 263), ("Amoxliatl", 226)]
    items = drops_tables.ItemIdLookup(items_api.load())
    dump = drops_tables.NpcDropsAggregator()
    for title in ["Amoxliatl", "Vorkath"]:
        for table in drops_wikitext.parse_all_drop_tables(pages[title]):
            dump.add(drops_tables.build_table_spec(title, table, items))
    assert dump.npcs[13685]["tables"] == ["amoxliatl"]
    for npc_id in [13686, 8058, 8060]:
        assert dump.npcs[npc_id]["tables"] == []
    for npc_id in [8059, 8061]:
        assert dump.npcs[npc_id]["tables"] == ["vorkath"]


def test_regular_variants_still_inherit_tables_without_uniform_postquest_headers():
    import json
    from pathlib import Path

    pages = json.loads(
        (
            Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
        ).read_text(encoding="utf-8")
    )
    for title, expected in [
        ("Crocodile", {11582}),
        ("Moss giant", {2090, 2091, 2092, 2093, 7262, 14422}),
    ]:
        actual = {
            npc_id
            for table in drops_wikitext.parse_all_drop_tables(pages[title])
            for npc_id in table.npc_ids
        }
        assert expected <= actual


@pytest.mark.parametrize(
    "rate,expected",
    [
        ("1/181.1", [10, 1811]),
        ("1/360.72", [100, 36072]),
        ("1/1800.72", [100, 180072]),
        ("0.5/100", [5, 1000]),
        ("4/540", [4, 540]),
        ("0/350", [0, 350]),
        ("350/350", [350, 350]),
    ],
)
def test_pre_roll_exports_exact_source_ratio_without_reducing_pool_slots(
    rate, expected
):
    source = (
        "{{Infobox Monster|id=1}}\n==Drops==\n===Pre-roll===\n"
        "{{DropsLine|name=Rune full helm|quantity=1|rarity=" + rate + "}}"
    )
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", table, ITEMS)
    )
    row = exported["entries"][0]
    assert [row["weight"], row["out_of"]] == expected
    assert row["pre_roll"] is True


@pytest.mark.parametrize("rate", ["1/0", "351/350"])
def test_invalid_pre_roll_probability_stays_raw_and_unexecutable(rate):
    source = (
        "{{Infobox Monster|id=1}}\n==Drops==\n===Pre-roll===\n"
        "{{DropsLine|name=Rune full helm|quantity=1|rarity=" + rate + "}}"
    )
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    row = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", table, ITEMS)
    )["entries"][0]
    assert row["rarity_raw"] == rate
    assert "out_of" not in row
    assert "rarity" not in row


WIKITEXT = """
{{Infobox Monster
|id1 = 123,124
|version1 = Normal
}}

==Drops==
===100%===
{{DropsLine|name=Bones|quantity=1|rarity=Always}}

===Weapons and armour===
{{DropsLine|name=Rune full helm|quantity=1|rarity=3/128}}
{{DropsLine|name=Coins|quantity=100-200|rarity=1/128}}
{{DropsLine|name=Nothing|rarity=123/128}}
{{RareDropTable|1/128}}
{{DropsLine|name=Bird nest (egg)#Blue egg|quantity=1|rarity=Common}}

===Tertiary===
{{DropsLine|name=Draconic visage|quantity=1|rarity=1/{{#expr:5000/(1)}}
|raritynotes=Only dropped in [[Wilderness|the Wilderness]].}}

==Other==
"""


def _table():
    tables = drops_wikitext.parse_all_drop_tables(WIKITEXT)
    assert len(tables) == 1
    return drops_tables.build_table_json(
        drops_tables.build_table_spec("Test_monster", tables[0], ITEMS)
    )


def test_npc_ids_come_from_the_infobox():
    """Both IDs on the infobox roll the page's single drop table."""
    tables = drops_wikitext.parse_all_drop_tables(WIKITEXT)
    assert tables[0].npc_ids == [123, 124]


def test_table_identity():
    """Table naming follows the wiki page, not the npc."""
    table = _table()
    assert table["table_id"] == "test_monster"
    assert table["table_name"] == "Test monster Drops"
    assert table["wiki_page"] == "Test monster"
    assert table["label"] == "Drops"


def test_guaranteed_drop_has_no_rate():
    """A 100% drop is exported as always, with no weight or roll."""
    entry = _table()["entries"][0]
    assert entry["item_id"] == 526
    assert entry["always"] is True
    assert "weight" not in entry and "out_of" not in entry


def test_main_table_weights_share_one_denominator():
    """Every main table drop is weighted against the same pool."""
    table = _table()
    assert table["main_max_roll"] == 128
    entries = [e for e in table["entries"] if e.get("out_of") == 128]
    assert [e.get("name") for e in entries] == [
        "Rune full helm",
        "Coins",
        None,  # the Nothing roll
        None,  # the rare drop table access
    ]
    assert entries[0]["weight"] == 3
    assert entries[0]["rarity"] == 0.0234375
    assert entries[1]["quantity"] == [100, 200]
    assert entries[2]["nothing"] is True
    assert entries[3]["shared_table"] == "rareDrop"


def test_item_ids_prefer_the_wiki_name():
    """ "Coins" is four items; the one the wiki links to wins."""
    coins = [e for e in _table()["entries"] if e.get("name") == "Coins"][0]
    assert coins["item_id"] == 995


def test_version_anchors_resolve_to_the_right_item():
    """``Bird nest (egg)#Blue egg`` is the blue egg item, not the base nest."""
    nest = [
        e for e in _table()["entries"] if e.get("name", "").startswith("Bird nest")
    ][0]
    assert nest["item_id"] == 5072
    # A word rarity is a convention, not wiki data, so it is flagged.
    assert nest["assumed_rarity"] is True
    # Its 1/8 rate is not the table pool, so it rolls separately.
    assert nest["separate_roll"] is True
    assert nest["out_of"] == 8


def test_tertiary_rate_is_evaluated_and_annotated():
    """Wiki arithmetic resolves to a rate, and footnotes travel with the drop."""
    tertiary = _table()["tertiary"][0]
    assert tertiary["item_id"] == 11286
    assert tertiary["out_of"] == 5000
    assert tertiary["notes"] == ["Only dropped in the Wilderness."]


def test_expression_evaluation_rejects_non_arithmetic():
    """The expression evaluator only ever evaluates arithmetic."""
    assert drops_wikitext.evaluate_expression("2000/(1999/2000) round 1") == "2001"
    assert drops_wikitext.evaluate_expression("__import__('os')") is None


def test_shared_table_accesses_are_not_double_counted():
    """A table that rolls the seed table drops its individually listed seeds."""
    wikitext = """{{Infobox Monster\n|id1 = 1\n}}\n==Drops==\n"""
    wikitext += "===Seeds===\n{{GeneralSeedDropTableInfo|18/128}}\n"
    wikitext += "{{DropsLine|name=Coins|quantity=1|rarity=1/128}}\n"
    table = drops_wikitext.parse_all_drop_tables(wikitext)[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test_monster", table, ITEMS)
    )
    assert [e.get("shared_table") for e in exported["entries"]] == ["seed"]


def test_cached_variant_pages_keep_npc_ids_separate():
    import json
    from pathlib import Path

    pages = json.loads(
        (
            Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
        ).read_text()
    )
    expected = {
        "Rogue": {"Level 15 drops": {526}, "Level 135 drops": {6603}},
        "Giant rat": {
            "Level 3 and 6 drops": set(range(2856, 2865)),
            "Level 26 drops": {2510, 2511, 2512},
        },
        "Skeleton": {
            "Drops (Plain)": {
                71,
                72,
                73,
                75,
                76,
                78,
                79,
                80,
                81,
                83,
                14426,
                14427,
                14428,
            },
            "Drops (Unarmed)": {70, 74},
            "Drops (Armed)": {77, 82},
        },
        "Rat": {
            "Drops (Regular)": {2854, 2855},
            "Drops (Stronghold of Security)": {2492, 2513},
        },
    }
    for page, mappings in expected.items():
        actual = {
            table.table_name: set(table.npc_ids)
            for table in drops_wikitext.parse_all_drop_tables(pages[page])
        }
        assert actual == mappings, page


def test_variant_matching_uses_whole_words_and_numbers():
    assert not drops_wikitext._heading_matches_drop_version("Unarmed", "Armed")
    assert not drops_wikitext._heading_matches_drop_version("Level 135", "Level 13")


def test_non_guaranteed_rarity_under_guaranteed_heading():
    source = WIKITEXT.replace("rarity=Always", "rarity=Varies")
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    result = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", table, ITEMS)
    )
    assert not any(entry.get("item_id") == 526 for entry in result["entries"])
    bones = next(entry for entry in result["tertiary"] if entry["item_id"] == 526)
    assert bones["out_of"] == 128
    assert not bones.get("always")


def test_named_exceptions_and_level_ranges():
    import json
    from pathlib import Path

    pages = json.loads(
        (
            Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
        ).read_text()
    )
    for page in (
        "Highwayman",
        "Hobgoblin",
        "Tortoise",
        "Possessed pickaxe",
        "Lesser demon",
        "Zombie (Tarn's Lair)",
    ):
        tables = drops_wikitext.parse_all_drop_tables(pages[page])
        seen = set()
        for table in tables:
            assert table.npc_ids, (page, table.table_name)
            assert not seen.intersection(table.npc_ids), page
            seen.update(table.npc_ids)
    lesser = drops_wikitext.parse_all_drop_tables(pages["Lesser demon"])
    assert set(lesser[1].npc_ids) == {7865, 7866, 7867}
    zombies = drops_wikitext.parse_all_drop_tables(pages["Zombie (Tarn's Lair)"])
    assert zombies[0].npc_ids == list(range(6449, 6454))
    assert zombies[1].npc_ids == list(range(6454, 6460))


def test_noted_drops_are_flagged():
    """A wiki quantity ending in ``(noted)`` keeps its range and exports ``noted``."""
    page = """
{{Infobox Monster
|id1 = 125
}}

==Drops==
===Other===
{{DropsLine|name=Coins|quantity=100-200 (noted)|rarity=1/2}}
{{DropsLine|name=Bones|quantity=5|rarity=1/2}}
"""
    tables = drops_wikitext.parse_all_drop_tables(page)
    table = drops_tables.build_table_json(
        drops_tables.build_table_spec("Noted_monster", tables[0], ITEMS)
    )
    coins, bones = table["entries"]
    assert coins["quantity"] == [100, 200]
    assert coins["noted"] is True
    assert "quantity_raw" not in coins
    assert "noted" not in bones


def test_drop_source_loader_excludes_obsolete_titles_not_shared_npc_ids(
    tmp_path, monkeypatch
):
    import json
    import config
    from scripts.drops.update import load_monster_wikitext

    # An incremental cache can retain the pre-rename page before the current one.
    # Separate current encounters must survive even when they share NPC IDs.
    pages = {
        "Shellbane Gryphon": WIKITEXT,
        "Shellbane gryphon": WIKITEXT,
        "Shellbane gryphon (Troubled Tortugans)": WIKITEXT,
    }
    current = {title: "2026-08-24T15:07:44Z" for title in list(pages)[1:]}
    (tmp_path / "monsters-wiki-page-text.json").write_text(json.dumps(pages))
    (tmp_path / "monsters-wiki-page-titles.json").write_text(json.dumps(current))
    monkeypatch.setattr(config, "DATA_MONSTERS_PATH", tmp_path)
    assert load_monster_wikitext() == {title: pages[title] for title in current}


def test_drop_source_loader_requires_nonempty_current_listing(tmp_path, monkeypatch):
    import json
    import pytest
    import config
    from scripts.drops.update import load_monster_wikitext

    (tmp_path / "monsters-wiki-page-text.json").write_text(
        json.dumps({"Old": WIKITEXT})
    )
    monkeypatch.setattr(config, "DATA_MONSTERS_PATH", tmp_path)
    with pytest.raises(SystemExit, match="monsters-wiki-page-titles.json"):
        load_monster_wikitext()
    (tmp_path / "monsters-wiki-page-titles.json").write_text("{}")
    with pytest.raises(SystemExit, match="empty"):
        load_monster_wikitext()


def test_cached_goblin_energy_potions_roll_in_the_main_pool():
    """The goblin page was cached mid-edit, with its energy potions as "Common":
    three independent 1/8 rolls, so a third of kills dropped one or more
    (RSPSApp/tsps#1706). The current page has them in the 128 pool."""
    import json
    from pathlib import Path

    pages = json.loads(
        (
            Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
        ).read_text(encoding="utf-8")
    )
    items = drops_tables.ItemIdLookup(
        [
            FakeItem(3008, "Energy potion(4)"),
            FakeItem(3010, "Energy potion(3)"),
            FakeItem(3012, "Energy potion(2)"),
            FakeItem(3014, "Energy potion(1)"),
        ]
    )
    expected = {
        "Drop table 1": {3010: (3, 128), 3008: (3, 128)},
        "Drop table 2": {3012: (13, 128)},
    }
    tables = drops_wikitext.parse_all_drop_tables(pages["Goblin"])
    for table in tables:
        spec = drops_tables.build_table_spec("Goblin", table, items)
        exported = drops_tables.build_table_json(spec)
        potions = {
            row["item_id"]: (row["weight"], row["out_of"])
            for row in exported["entries"]
            if row.get("item_id") in (3008, 3010, 3012, 3014)
        }
        assert potions == expected[table.table_name]
        assert not any(
            row.get("separate_roll")
            for row in exported["entries"]
            if row.get("item_id") in potions
        )
        assert drops_tables.stacked_assumed_rolls(spec.separate_rolls) == []


def test_several_word_rarity_rows_in_one_section_are_flagged():
    source = """{{Infobox Monster|id=1}}
==Drops==
===Other===
{{DropsLine|name=Coins|quantity=100|rarity=100/128}}
{{DropsLine|name=Coins|quantity=5|rarity=20/128}}
{{DropsLine|name=Draconic visage|quantity=1|rarity=1/128}}
{{DropsLine|name=Bones|quantity=1|rarity=Common}}
{{DropsLine|name=Rune full helm|quantity=1|rarity=Common}}
"""
    table = drops_wikitext.parse_all_drop_tables(source)[0]
    spec = drops_tables.build_table_spec("Test", table, ITEMS)
    stacked = drops_tables.stacked_assumed_rolls(spec.separate_rolls)
    assert [[entry.name for entry in roll.entries] for roll in stacked] == [
        ["Bones", "Rune full helm"]
    ]


def _cached_page_tables(page, items=None):
    import json
    from pathlib import Path

    pages = json.loads(
        (
            Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
        ).read_text(encoding="utf-8")
    )
    return [
        drops_tables.build_table_json(
            drops_tables.build_table_spec(page, table, items or ITEMS)
        )
        for table in drops_wikitext.parse_all_drop_tables(pages[page])
    ]


def test_cached_lizardmen_roll_the_uncommon_seed_table():
    """{{UncommonSeedDropLines}} was dropped without a warning, so a lizardman
    killed six times dropping only bones was likely (RSPSApp/tsps#1952). The
    Wiki's level 53, level 62 and brute tables roll it at 15/87, 15/78, 15/67."""
    accesses = {
        (table["label"], row["weight"], row["out_of"])
        for page in ("Lizardman", "Lizardman brute")
        for table in _cached_page_tables(page)
        for row in table["entries"]
        if row.get("shared_table") == "uncommonSeed"
    }
    assert accesses == {
        ("Level 53 drops", 15, 87),
        ("Level 62 drops", 15, 78),
        ("Drops", 15, 67),
    }


def test_uncommon_seed_table_lines_are_a_shared_access_not_rows():
    wikitext = """{{Infobox Monster\n|id1 = 1\n}}\n==Drops==\n"""
    wikitext += "===Seeds===\n{{UncommonSeedDropTableInfo|35/128}}\n"
    wikitext += "{{UncommonSeedDropLines|35/128|f2p=yes}}\n"
    table = drops_wikitext.parse_all_drop_tables(wikitext)[0]
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Test_monster", table, ITEMS)
    )
    assert [
        (e.get("shared_table"), e.get("weight"), e.get("out_of"))
        for e in exported["entries"]
    ] == [("uncommonSeed", 35, 128)]


def test_uncommon_seed_table_is_exported_from_the_drop_table_page():
    from scripts.drops.update import load_shared_table_wikitext

    shared = drops_tables.export_shared_subtables(load_shared_table_wikitext(), ITEMS)
    seeds = shared["uncommonSeed"]
    assert seeds["wiki_label"] == "uncommon seed drop table"
    assert seeds["entries"][0]["rarity_raw"] == "137/1048"


def test_members_world_rate_replaces_the_free_to_play_rate():
    """The dump describes members worlds: "Drop rate is decreased to 8/128 in
    [[members]] worlds" with altrarity=8/128 rolls 8/128. The moss giant's
    table, its seed roll restored, now fills exactly 128 slots."""
    line = drops_wikitext._parse_drop_line(
        {
            "name": "Coins",
            "quantity": "2",
            "rarity": "11/128",
            "altrarity": "8/128",
            "raritynotes": '<ref group="d">Drop rate is decreased to 8/128 in [[members]] worlds.</ref>',
        },
        "Main",
        "Coins",
        {},
    )
    assert line.rarity == "8/128"
    skeleton = drops_wikitext._parse_drop_line(
        {
            "name": "Coins",
            "quantity": "2",
            "rarity": "29/128",
            "altrarity": "24/128",
            "raritynotes": "<ref group=d>The drop rate decreases to 24/128 on a [[members]] world.</ref>",
        },
        "Main",
        "Coins",
        {},
    )
    assert skeleton.rarity == "24/128"
    unrelated = drops_wikitext._parse_drop_line(
        {
            "name": "Coins",
            "quantity": "2",
            "rarity": "11/128",
            "altrarity": "Never",
            "raritynotes": "<ref group=d>Not dropped in the Forgotten Cemetery.</ref>",
        },
        "Main",
        "Coins",
        {},
    )
    assert unrelated.rarity == "11/128"
    from osrsreboxed import items_api

    (moss_giant,) = [
        t
        for t in _cached_page_tables(
            "Moss giant", drops_tables.ItemIdLookup(items_api.load())
        )
        if t["label"] == "Drops"
    ]
    assert moss_giant["main_max_roll"] == 128
    assert sum(
        e["weight"]
        for e in moss_giant["entries"]
        if "weight" in e and not e.get("separate_roll")
    ) == 128


def test_cached_manta_ray_keeps_its_other_seed_pools():
    """The manta ray's Seeds section has {{UncommonSeedDropLines}} beside its own
    rare and tree-herb seed rows. The uncommon access must not swallow those rows:
    Yew, Magic and Redwood tree seeds come only from them (RSPSApp/tsps#1982)."""
    from osrsreboxed import items_api

    (manta,) = _cached_page_tables(
        "Manta ray (monster)", drops_tables.ItemIdLookup(items_api.load())
    )
    names = {row.get("name") for row in manta["entries"]}
    assert {"Yew seed", "Magic seed", "Redwood tree seed"} <= names
    assert [
        (row["weight"], row["out_of"])
        for row in manta["entries"]
        if row.get("shared_table") == "uncommonSeed"
    ] == [(30, 99)]
    seeds = [row for row in manta["entries"] if row.get("section") == "Seeds" and row.get("item_id")]
    assert len(seeds) == 28


def test_explicit_named_location_notes_apply_to_every_referencing_row():
    """HTML refs, Refn and NamedRef preserve conditions without repeating an item name."""
    text = """
{{Infobox Monster|id=123}}
==Drops==
===Other===
{{DropsLine|name=Trading sticks|quantity=1|rarity=1/128|raritynotes=<ref group="d" name="karamja">Only dropped by Hobgoblins on [[Karamja]], in place of the regular coin drops.</ref>}}
{{DropsLine|name=Trading sticks|quantity=5|rarity=12/128|raritynotes=<ref group="d" name="karamja"/>}}
{{DropsLine|name=Iron med helm|quantity=1|rarity=5/128|raritynotes={{Refn|group=d|name=giant|Only dropped by giants on the Giants' Plateau.}}}}
{{DropsLine|name=Steel scimitar|quantity=1|rarity=2/128|raritynotes={{Refn|group=d|name=giant}}}}
{{DropsLine|name=Pyrophosphite|quantity=1|rarity=18/118|raritynotes={{Refn|Only dropped by ancient zygomites on Fossil Island.|group=d|name=island}}}}
{{DropsLine|name=Volcanic ash|quantity=2|rarity=16/590|raritynotes={{NamedRef|island|group=d}}}}
{{DropsLine|name=Coins|quantity=1|rarity=1/128}}
"""
    rows = drops_wikitext.parse_all_drop_tables(text)[0].drops
    assert len(rows) == 7
    for first, reference in ((0, 1), (2, 3), (4, 5)):
        assert rows[first].notes
        assert rows[reference].notes == rows[first].notes
    assert rows[-1].notes == []


def test_cached_zalcano_death_runes_keep_current_source_range():
    from scripts.drops import update

    pages = update.load_monster_wikitext()
    items = drops_tables.ItemIdLookup([FakeItem(560, "Death rune")])
    parsed = drops_wikitext.parse_all_drop_tables(pages["Zalcano"])[0]
    table = drops_tables.build_table_json(
        drops_tables.build_table_spec("Zalcano", parsed, items)
    )
    row = next(row for row in table["entries"] if row.get("item_id") == 560)
    assert row["quantity"] == [201, 1046]
    assert row["weight"] == 1
    assert row["out_of"] == table["main_max_roll"] == 36
