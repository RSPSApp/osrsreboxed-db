"""Drops the wiki footnotes as "dropped together" export as one slot with bonus drops."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from osrsreboxed import items_api
from scripts.drops import drops_tables
from scripts.drops import drops_wikitext as drops

CORPUS = Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"


@pytest.fixture(scope="module")
def pages():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_items():
    return drops_tables.ItemIdLookup(items_api.load())


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


ITEMS = drops_tables.ItemIdLookup(
    [fake_item(1, "Shark"), fake_item(2, "Prayer potion(4)"), fake_item(3, "Coins")]
)


def export(rows, heading="Consumables", items=ITEMS):
    source = (
        "{{Infobox Monster|id=1}}\n==Drops==\n==="
        + heading
        + "===\n{{DropsTableHead}}\n"
        + "\n".join(rows)
        + "\n{{DropsTableBottom}}"
    )
    parsed = drops.parse_all_drop_tables(source)[0]
    return drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", parsed, items)
    )


def line(name, quantity, rarity, raritynotes):
    return (
        f"{{{{DropsLine|name={name}|quantity={quantity}|rarity={rarity}"
        f"|raritynotes={raritynotes}}}}}"
    )


TOGETHER = "Sharks and Prayer potions are dropped together"
COINS = line("Coins", "100", "10/127", "")


def assert_pair(exported, first_id, partner_id, partner_quantity):
    entries = exported["entries"]
    first = next(entry for entry in entries if entry.get("item_id") == first_id)
    assert first["bonus_drops"] == [
        {
            "item_id": partner_id,
            "name": "Prayer potion(4)",
            "quantity": partner_quantity,
        }
    ]
    assert all(entry.get("item_id") != partner_id for entry in entries)
    return first


# --- footnote syntaxes ---------------------------------------------------------


def test_quoted_definition_and_self_closing_reference_bundle():
    exported = export(
        [
            line(
                "Shark", "10", "6/127", f'<ref group="d" name="sups1">{TOGETHER}</ref>'
            ),
            line("Prayer potion(4)", "3", "6/127", '<ref group="d" name="sups1"/>'),
            COINS,
        ]
    )
    first = assert_pair(exported, 1, 2, [3, 3])
    assert first["weight"] == 6 and first["out_of"] == 127
    assert TOGETHER in first["notes"]
    assert len(exported["entries"]) == 2


def test_repeated_body_on_both_rows_bundles():
    body = f'<ref group="d" name="potiondrop">{TOGETHER}.</ref>'
    exported = export(
        [
            line("Shark", "3", "8/127", body),
            line("Prayer potion(4)", "3", "8/127", body),
        ]
    )
    assert_pair(exported, 1, 2, [3, 3])


def test_unquoted_attributes_bundle():
    exported = export(
        [
            line(
                "Shark", "1", "1/128", f"<ref group=d name=minerals>{TOGETHER}.</ref>"
            ),
            line("Prayer potion(4)", "1", "1/128", "<ref group=d name=minerals />"),
        ]
    )
    assert_pair(exported, 1, 2, [1, 1])


def test_refn_definition_and_refn_reference_bundle():
    exported = export(
        [
            line(
                "Shark",
                "2-4",
                "Uncommon",
                "{{Refn|group=d|name=supply|The two drop together.}}",
            ),
            line("Prayer potion(4)", "1", "Uncommon", "{{Refn|group=d|name=supply}}"),
        ]
    )
    assert_pair(exported, 1, 2, [1, 1])


def test_refn_definition_and_namedref_reference_bundle_beside_other_refs():
    exported = export(
        [
            line(
                "Shark",
                "1",
                "18/118",
                f"{{{{Refn|{TOGETHER}.|group=d|name=pyrocalc}}}}"
                "{{Refn|Only dropped on Fossil Island.|group=d|name=island}}",
            ),
            line(
                "Prayer potion(4)",
                "1",
                "18/118",
                "{{NamedRef|pyrocalc|group=d}}{{NamedRef|island|group=d}}",
            ),
        ]
    )
    assert_pair(exported, 1, 2, [1, 1])


def test_ungrouped_named_reference_on_the_row_is_ignored():
    exported = export(
        [
            line(
                "Shark",
                "3",
                "6/127",
                f'<ref group="d" name="pots1">{TOGETHER}</ref>{{{{NamedRef|potions rate}}}}',
            ),
            line(
                "Prayer potion(4)",
                "3",
                "6/127",
                '<ref group="d" name="pots1"/>{{NamedRef|potions rate}}',
            ),
        ]
    )
    assert_pair(exported, 1, 2, [3, 3])


# --- what does not bundle -------------------------------------------------------


def unbundled(exported):
    assert all("bonus_drops" not in entry for entry in exported["entries"])
    return [entry.get("item_id") for entry in exported["entries"]]


def test_non_adjacent_rows_do_not_bundle():
    exported = export(
        [
            line("Shark", "10", "6/127", f'<ref group="d" name="s">{TOGETHER}</ref>'),
            COINS,
            line("Prayer potion(4)", "3", "6/127", '<ref group="d" name="s"/>'),
        ]
    )
    assert unbundled(exported) == [1, 3, 2]


def test_different_rates_do_not_bundle():
    exported = export(
        [
            line("Shark", "10", "6/127", f'<ref group="d" name="s">{TOGETHER}</ref>'),
            line("Prayer potion(4)", "3", "8/127", '<ref group="d" name="s"/>'),
        ]
    )
    assert unbundled(exported) == [1, 2]


def test_three_rows_sharing_the_note_stay_separate_slots():
    exported = export(
        [
            line(
                "Shark",
                "5-14",
                "2/18",
                f"{{{{refn|group=d|name=secondary|{TOGETHER}.}}}}",
            ),
            line("Prayer potion(4)", "3-11", "2/18", "{{NamedRef|group=d|secondary}}"),
            line("Coins", "3-6", "2/18", "{{NamedRef|group=d|secondary}}"),
        ]
    )
    assert unbundled(exported) == [1, 2, 3]


@pytest.mark.parametrize(
    "body",
    [
        "Players will receive sharks together with a prayer potion.",
        "6 sharks are dropped alongside 4 prayer potions.",
    ],
)
def test_other_phrasings_do_not_bundle(body):
    exported = export(
        [
            line("Shark", "10", "6/127", f'<ref group="d" name="s">{body}</ref>'),
            line("Prayer potion(4)", "3", "6/127", '<ref group="d" name="s"/>'),
        ]
    )
    assert unbundled(exported) == [1, 2]


def test_other_reference_groups_do_not_bundle():
    exported = export(
        [
            line("Shark", "10", "6/127", f'<ref group="e" name="s">{TOGETHER}</ref>'),
            line("Prayer potion(4)", "3", "6/127", '<ref group="e" name="s"/>'),
        ]
    )
    assert unbundled(exported) == [1, 2]


def test_unresolved_partner_leaves_the_first_row_plain():
    exported = export(
        [
            line("Shark", "10", "6/127", f'<ref group="d" name="s">{TOGETHER}</ref>'),
            line("Unknown potion", "3", "6/127", '<ref group="d" name="s"/>'),
        ]
    )
    assert unbundled(exported) == [1]
    assert exported["unresolved_items"] == ["Unknown potion"]


@pytest.mark.parametrize("unknown_position", [0, 1, 2])
def test_unresolved_row_does_not_turn_a_three_row_source_run_into_a_pair(
    unknown_position,
):
    ref = f'<ref group="d" name="s">{TOGETHER}</ref>'
    rows = [
        line("Shark", "10", "6/127", ref),
        line("Prayer potion(4)", "3", "6/127", ref),
    ]
    rows.insert(unknown_position, line("Unknown potion", "3", "6/127", ref))
    assert unbundled(export(rows)) == [1, 2]


def test_unresolved_unrelated_row_preserves_source_separation():
    ref = f'<ref group="d" name="s">{TOGETHER}</ref>'
    assert unbundled(
        export(
            [
                line("Shark", "10", "6/127", ref),
                line("Unknown potion", "3", "6/127", ""),
                line("Prayer potion(4)", "3", "6/127", ref),
            ]
        )
    ) == [1, 2]


def test_pair_with_extra_partner_eligibility_stays_separate():
    ref = f'<ref group="d" name="s">{TOGETHER}</ref>'
    note = "{{Refn|group=d|Only dropped after completing [[Dragon Slayer I]].}}"
    assert unbundled(
        export(
            [
                line("Shark", "10", "6/127", ref),
                line("Prayer potion(4)", "3", "6/127", ref + note),
            ]
        )
    ) == [1, 2]


def test_partner_with_quantity_alternatives_keeps_its_quantity_contract():
    ref = f'<ref group="d" name="s">{TOGETHER}</ref>'
    exported = export(
        [
            line("Shark", "10", "6/127", ref),
            line("Prayer potion(4)", "3,5", "6/127", ref),
        ]
    )
    assert unbundled(exported) == [1, 2]
    assert len(exported["entries"][1]["quantity_alternatives"]) == 2


# --- the cached corpus ----------------------------------------------------------


def corpus_table(pages, real_items, title, table_id):
    tables = {}
    for parsed in drops.parse_all_drop_tables(pages[title]):
        exported = drops_tables.build_table_json(
            drops_tables.build_table_spec(title.replace(" ", "_"), parsed, real_items)
        )
        tables[exported["table_id"]] = exported
    assert table_id in tables, sorted(tables)
    return tables[table_id]


def pairs(exported):
    return sorted(
        (entry["item_id"], bonus["item_id"])
        for entry in exported["entries"]
        for bonus in entry.get("bonus_drops", [])
    )


def used_slots(exported):
    """Pool slots in use: weighted item rows plus shared-table accesses."""
    return sum(
        entry.get("weight", 0)
        for entry in exported["entries"]
        if (
            entry.get("out_of") == exported["main_max_roll"]
            or entry.get("shared_table")
        )
        and not entry.get("always")
        and not entry.get("separate_roll")
        and not entry.get("pre_roll")
    )


@pytest.mark.parametrize(
    "title, table_id, expected_pairs, max_roll, used",
    [
        ("Nex", "nex", [(385, 2434), (6685, 3024)], 12, 12),
        (
            "Commander Zilyana",
            "commander_zilyana",
            [(163, 3042), (6687, 3024)],
            1524,
            1524,
        ),
        # Exact normalization keeps uniques and source coin fractions in one
        # exclusive pool: 1524 integer subslots represent the 127-slot source.
        ("K'ril Tsutsaroth", "kril_tsutsaroth", [(145, 157), (3026, 189)], 1524, 1524),
        ("Kree'arra", "kreearra", [(169, 163)], 1524, 1524),
        ("General Graardor", "general_graardor", [], 1524, 1524),
        ("Ammonite Crab", "ammonite_crab", [(21543, 21545)], 128, 128),
        ("Chaos Fanatic", "chaos_fanatic", [(1035, 1033)], 133, 133),
        # The footnoted pair is in the take-eggs variant, whose rows the parser
        # currently loses; the open-stomach rows carry no footnote, so the
        # source rule leaves them as separate slots.
        ("Maggot King", "maggot_king", [], 200, 200),
        ("Ancient Zygomite", "ancient_zygomite", [(21545, 21543)], 118, 89),
        ("Scavenger beast", "scavenger_beast", [], 18, 18),
    ],
)
def test_cached_tables_bundle_their_pairs_and_keep_their_pools(
    pages, real_items, title, table_id, expected_pairs, max_roll, used
):
    exported = corpus_table(pages, real_items, title, table_id)
    assert pairs(exported) == expected_pairs
    assert exported["main_max_roll"] == max_roll
    assert used_slots(exported) == used
    partners = {partner for _, partner in expected_pairs}
    assert all(entry.get("item_id") not in partners for entry in exported["entries"])


def test_cached_nex_pairs_keep_their_quantities_and_shared_note(pages, real_items):
    nex = corpus_table(pages, real_items, "Nex", "nex")
    shark = next(entry for entry in nex["entries"] if entry["item_id"] == 385)
    assert shark["quantity"] == [10, 10]
    assert shark["bonus_drops"] == [
        {"item_id": 2434, "name": "Prayer potion(4)", "quantity": [3, 3]}
    ]
    assert "Sharks and Prayer potions are dropped together" in shark["notes"]
    brew = next(entry for entry in nex["entries"] if entry["item_id"] == 6685)
    assert brew["quantity"] == [1, 10]
    assert brew["bonus_drops"] == [
        {"item_id": 3024, "name": "Super restore(4)", "quantity": [1, 5]}
    ]
    assert len([entry for entry in nex["entries"] if entry.get("out_of") == 12]) == 12


def test_cached_scavenger_beast_keeps_three_secondary_slots(pages, real_items):
    beast = corpus_table(pages, real_items, "Scavenger beast", "scavenger_beast")
    secondary = [
        entry
        for entry in beast["entries"]
        if entry.get("item_id") in (29994, 29996, 29998) or entry.get("weight") == 2
    ]
    assert len([entry for entry in beast["entries"] if entry.get("weight") == 2]) >= 3
    assert all("bonus_drops" not in entry for entry in secondary)
