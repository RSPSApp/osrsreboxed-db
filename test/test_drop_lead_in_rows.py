"""Rows under a level-2 drop heading, ahead of its first subheading, are kept."""

import json
from pathlib import Path
from types import SimpleNamespace

from osrsreboxed import items_api

from scripts.drops import drops_tables, drops_wikitext

CORPUS = Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"


def item(item_id, name):
    return SimpleNamespace(
        id=item_id,
        name=name,
        wiki_name=name,
        tradeable_on_ge=True,
        duplicate=False,
        noted=False,
        placeholder=False,
        stacked=None,
    )


ITEMS = drops_tables.ItemIdLookup([item(1, "Bones"), item(2, "Coins")])

LEAD_IN_ROWS = """==Drops==
{{DropsTableHead}}
{{DropsLine|name=Bones|quantity=1|rarity=Always}}
{{DropsLine|name=Coins|quantity=5|rarity=1/4}}
{{DropsTableBottom}}

===Tertiary===
{{DropsTableHead|bucket=no}}
{{DropsLineClue|type=elite|rarity=1/40}}
{{DropsTableBottom}}
"""

PROSE_ONLY_LEAD_IN = """==Drops==
An average kill is worth {{Coins|1234}} and the {{DropLogProject|kills=5}} log.

===Other===
{{DropsTableHead}}
{{DropsLine|name=Coins|quantity=5|rarity=1/4}}
{{DropsTableBottom}}
"""


def parsed_rows(source):
    (table,) = drops_wikitext.parse_all_drop_tables(source)
    return [(drop.name, drop.section, drop.subsection) for drop in table.drops]


def test_rows_before_the_first_subheading_are_not_dropped():
    assert parsed_rows(LEAD_IN_ROWS) == [
        ("Bones", "Guaranteed", ""),
        ("Coins", "Main", ""),
        ("Clue scroll (elite)", "Tertiary", "Tertiary"),
    ]


def test_a_lead_in_without_rows_still_contributes_nothing():
    assert drops_wikitext._split_drop_subsections(PROSE_ONLY_LEAD_IN)[0][0] == "Other"
    assert parsed_rows(PROSE_ONLY_LEAD_IN) == [("Coins", "Main", "Other")]


def test_a_section_with_no_subheading_is_unchanged():
    source = "==Drops==\n{{DropsLine|name=Coins|quantity=5|rarity=1/4}}\n"
    assert drops_wikitext._split_drop_subsections(source) == [("", source)]


def test_cached_maggot_king_take_eggs_keeps_its_main_rows():
    pages = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = drops_tables.ItemIdLookup(items_api.load())
    tables = {
        parsed.table_name: drops_tables.build_table_json(
            drops_tables.build_table_spec("Maggot_King", parsed, items)
        )
        for parsed in drops_wikitext.parse_all_drop_tables(pages["Maggot King"])
    }
    take_eggs = tables["Drops (take-eggs)"]
    # The six eggs carry exact source rates out of 1500.
    assert [
        (row["name"], row["weight"], row["out_of"])
        for row in take_eggs["entries"]
        if row.get("name", "").startswith("Maggot egg")
    ] == [
        ("Maggot egg (base)", 300, 1500),
        ("Maggot egg (sickly)", 150, 1500),
        ("Maggot egg (warm)", 33, 1500),
        ("Maggot egg (pulsating)", 6, 1500),
        ("Maggot egg (wriggling)", 3, 1500),
        ("Maggot egg (writhing)", 1, 1500),
    ]
    assert take_eggs["main_max_roll"] == 1500
    # The supply pair drops together, and the Wiki gives it, and "Nothing",
    # only the words Uncommon and Common: those rates are flagged, not source.
    supply = next(row for row in take_eggs["entries"] if row.get("item_id") == 33628)
    assert [bonus["item_id"] for bonus in supply["bonus_drops"]] == [33627]
    assert supply["assumed_rarity"] is True
    nothing = next(row for row in take_eggs["entries"] if row.get("nothing"))
    assert nothing["separate_roll"] is True
    assert [row["item_id"] for row in take_eggs["tertiary"]] == [12113]
    # Open-stomach's table is covered by its own supplies-bundle test below.
    assert "Drops (open-stomach)" in tables


SUPPLIES_PROSE = """==Drops==
===Supplies===
''These supplies are dropped together.''
{{DropsTableHead}}
{{DropsLine|name=Bones|quantity=2-4|rarity=41/159}}
{{DropsLine|name=Coins|quantity=1|rarity=41/159}}
{{DropsTableBottom}}
"""


def bundle_refs(source):
    (table,) = drops_wikitext.parse_all_drop_tables(source)
    return [drop.bundle_ref for drop in table.drops]


def test_a_two_row_subsection_that_says_it_drops_together_is_one_slot():
    assert bundle_refs(SUPPLIES_PROSE) == ["section:Supplies"] * 2
    (table,) = drops_wikitext.parse_all_drop_tables(SUPPLIES_PROSE)
    spec = drops_tables.build_table_spec("Test", table, ITEMS)
    entries = drops_tables.build_table_json(spec)["entries"]
    assert [(e["item_id"], e["weight"], e["out_of"]) for e in entries] == [(1, 41, 159)]
    assert entries[0]["bonus_drops"][0]["item_id"] == 2


def test_prose_bundling_needs_exactly_two_rows_and_no_negation():
    three = SUPPLIES_PROSE.replace(
        "{{DropsTableBottom}}", "{{DropsLine|name=Bones|quantity=1|rarity=1/9}}\n{{DropsTableBottom}}"
    )
    assert bundle_refs(three) == [""] * 3
    negated = SUPPLIES_PROSE.replace("are dropped", "are not dropped")
    assert bundle_refs(negated) == [""] * 2


def test_cached_maggot_king_open_stomach_supplies_roll_as_one_slot():
    pages = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = drops_tables.ItemIdLookup(items_api.load())
    tables = {
        parsed.table_name: drops_tables.build_table_json(
            drops_tables.build_table_spec("Maggot_King", parsed, items)
        )
        for parsed in drops_wikitext.parse_all_drop_tables(pages["Maggot King"])
    }
    stomach = tables["Drops (open-stomach)"]
    # The Wiki's rows sum to 159 with the supplies as one 41/159 slot.
    assert stomach["main_max_roll"] == 159
    supply = next(r for r in stomach["entries"] if r.get("item_id") == 33628)
    assert (supply["weight"], supply["out_of"]) == (41, 159)
    assert [b["item_id"] for b in supply["bonus_drops"]] == [33627]
    assert not any(r.get("item_id") == 33627 for r in stomach["entries"])
