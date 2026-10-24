"""Quantity alternatives carry only the conditions the source states."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.drops import drops_tables
from scripts.drops import drops_wikitext as drops

CORPUS = Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"
PERFECT_KILL_STATEMENT = (
    "In addition, defeating the boss perfectly will earn 50% more loot from the "
    "standard drop table."
)
PERFECT_KILL = {"type": "perfect_kill"}
CHASM = {"type": "preferred_method", "location": "Chasm of Fire"}


@pytest.fixture(scope="module")
def pages():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def fake_item(item_id, name):
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


def export(source):
    lookup = drops_tables.ItemIdLookup([fake_item(995, "Coins")])
    parsed = drops.parse_all_drop_tables(source)[0]
    return drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", parsed, lookup)
    )


def page(rows, prose="", heading="Resources"):
    lines = "\n".join(rows)
    return (
        "{{Infobox Monster|id=1}}\n"
        + prose
        + "\n==Drops==\n==="
        + heading
        + "===\n{{DropsTableHead}}\n"
        + lines
        + "\n{{DropsTableBottom}}"
    )


def coins(quantity, rarity="1/100", **fields):
    extra = "".join(f"|{key}={value}" for key, value in fields.items())
    return f"{{{{DropsLine|name=Coins|quantity={quantity}|rarity={rarity}{extra}}}}}"


# --- perfect kill ---------------------------------------------------------


def test_perfect_kill_page_types_the_second_alternative_of_main_rows():
    entry = export(page([coins("120,180 (noted)")], PERFECT_KILL_STATEMENT))["entries"][
        0
    ]
    assert entry["quantity"] == [120, 120]
    assert entry["noted"] is True
    assert entry["quantity_alternatives"] == [
        {"quantity": [120, 120]},
        {"quantity": [180, 180], "condition": PERFECT_KILL},
    ]
    assert entry["quantity_selection"] == "conditional"


def test_perfect_kill_does_not_reach_tertiary_rows():
    exported = export(
        page([coins("1,2", rarity="1/50")], PERFECT_KILL_STATEMENT, heading="Tertiary")
    )
    entry = exported["tertiary"][0]
    assert entry["quantity_alternatives"] == [
        {"quantity": [1, 1]},
        {"quantity": [2, 2]},
    ]
    assert entry["quantity_selection"] == "unknown"


def test_alternatives_without_the_statement_stay_unknown():
    entry = export(page([coins("120,180")]))["entries"][0]
    assert "condition" not in entry["quantity_alternatives"][1]
    assert entry["quantity_selection"] == "unknown"


@pytest.mark.parametrize("quantity", ["100,150,200", "180,120", "10-20,15-18"])
def test_perfect_kill_requires_exactly_two_non_decreasing_alternatives(quantity):
    entry = export(page([coins(quantity)], PERFECT_KILL_STATEMENT))["entries"][0]
    assert all("condition" not in alt for alt in entry["quantity_alternatives"])
    assert entry["quantity_selection"] == "unknown"


def test_cached_desert_treasure_bosses_tag_every_alternative_row(pages):
    expected = {
        "Vardorvis": 25,
        "The Leviathan": 25,
        "The Whisperer": 25,
        "Duke Sucellus": 24,
    }
    for title, count in expected.items():
        rows = [
            drop
            for table in drops.parse_all_drop_tables(pages[title])
            for drop in table.drops
            if drops.parse_quantity_alternatives(drop.quantity)
        ]
        assert len(rows) == count, title
        assert all(drop.quantity_condition == PERFECT_KILL for drop in rows), title


# --- bounty task ----------------------------------------------------------


def test_bounty_quantity_note_types_the_second_alternative():
    note = "{{Refn|group=d|The quantity is increased to 5-10 while on a narwhal bounty task.}}"
    entry = export(page([coins("3-7,5-10", rarity="1/75", quantitynotes=note)]))[
        "entries"
    ][0]
    assert entry["quantity_alternatives"] == [
        {"quantity": [3, 7]},
        {
            "quantity": [5, 10],
            "condition": {"type": "bounty_task", "monster": "narwhal"},
        },
    ]
    assert entry["quantity_selection"] == "conditional"


def test_bounty_sentence_in_rarity_notes_does_not_type_a_quantity():
    note = "{{Refn|group=d|The quantity is increased to 5-10 while on a narwhal bounty task.}}"
    entry = export(page([coins("3-7,5-10", rarity="1/75", raritynotes=note)]))[
        "entries"
    ][0]
    assert all("condition" not in alt for alt in entry["quantity_alternatives"])
    assert entry["quantity_selection"] == "unknown"


def test_quantity_condition_does_not_invent_quest_eligibility_from_activity_notes():
    # The old generic note classifier mistakes activity completion for a quest.
    # Reading quantity notes to select an amount must not introduce such a gate.
    note = "{{Refn|group=d|Only dropped upon completing delve level 3 and deeper.}}"
    entry = export(page([coins("1,2", quantitynotes=note)]))["entries"][0]
    assert entry["quantity_selection"] == "unknown"
    assert "notes" not in entry


@pytest.mark.parametrize("title, monster", [("Narwhal", "narwhal"), ("Orca", "orca")])
def test_cached_bounty_nails_carry_their_monster(pages, title, monster):
    nails = [
        drop
        for table in drops.parse_all_drop_tables(pages[title])
        for drop in table.drops
        if drop.name == "Dragon nails"
    ]
    assert len(nails) == 1
    assert nails[0].quantity_condition == {"type": "bounty_task", "monster": monster}


# --- Chasm of Fire preferred method ----------------------------------------


def test_chasm_preferred_method_note_types_the_second_ashes_alternative():
    note = (
        "{{refn|group=d|name=100%|A second set of ashes is dropped when the demon is "
        "killed with preferred method in the [[Chasm of Fire]].}}"
    )
    entry = export(page([coins("1;2", rarity="Always", raritynotes=note)]))["entries"][
        0
    ]
    assert entry["always"] is True
    assert entry["quantity"] == [1, 1]
    assert entry["quantity_alternatives"] == [
        {"quantity": [1, 1]},
        {"quantity": [2, 2], "condition": CHASM},
    ]
    assert entry["quantity_selection"] == "conditional"


@pytest.mark.parametrize("title", ["Lesser demon", "Greater demon", "Black demon"])
def test_cached_demon_ashes_carry_the_chasm_condition_once(pages, title):
    rows = [
        drop
        for table in drops.parse_all_drop_tables(pages[title])
        for drop in table.drops
        if drops.parse_quantity_alternatives(drop.quantity)
    ]
    assert len(rows) == 1, title
    assert rows[0].section == drops.SECTION_GUARANTEED
    assert rows[0].quantity_condition == CHASM


# --- unknown rows and corpus totals -----------------------------------------


@pytest.mark.parametrize(
    "title, name",
    [
        ("Drake", "Shark lure"),
        ("Skeleton", "Air rune"),
        ("Crystalline Bat", "Raw paddlefish"),
    ],
)
def test_cached_rows_without_a_source_rule_stay_unconditioned(pages, title, name):
    rows = [
        drop
        for table in drops.parse_all_drop_tables(pages[title])
        for drop in table.drops
        if drop.name == name and drops.parse_quantity_alternatives(drop.quantity)
    ]
    assert len(rows) == 1
    assert rows[0].quantity_condition is None


def test_corpus_has_104_conditional_and_12_unknown_alternative_rows(pages):
    conditional = unknown = 0
    for wikitext in pages.values():
        for table in drops.parse_all_drop_tables(wikitext):
            for drop in table.drops:
                if not drops.parse_quantity_alternatives(drop.quantity):
                    continue
                if drop.quantity_condition:
                    conditional += 1
                else:
                    unknown += 1
    assert (conditional, unknown) == (104, 12)
