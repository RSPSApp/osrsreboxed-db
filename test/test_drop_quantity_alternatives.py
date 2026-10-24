"""Wiki quantity alternatives export as executable ranges, never as digits."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.drops import drops_tables, drops_wikitext
from scripts.drops.update import generate

CORPUS = Path(__file__).parents[1] / "data/monsters/monsters-wiki-page-text.json"


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


def export_quantity(raw):
    lookup = drops_tables.ItemIdLookup([fake_item(995, "Coins")])
    source = (
        "{{Infobox Monster|id=123}}\n==Drops==\n===100%===\n"
        "{{DropsTableHead}}\n"
        "{{DropsLine|name=Coins|quantity=" + raw + "|rarity=Always}}\n"
        "{{DropsTableBottom}}"
    )
    parsed = drops_wikitext.parse_all_drop_tables(source)[0]
    return drops_tables.build_table_json(
        drops_tables.build_table_spec("Test", parsed, lookup)
    )["entries"][0]


# Template:DropsLine/doc defines commas as separate quantities, never thousands:
# https://oldschool.runescape.wiki/w/Template:DropsLine/doc
@pytest.mark.parametrize(
    "raw, cleaned, alternatives, noted",
    [
        ("1,3", "1,3", [[1, 1], [3, 3]], False),
        ("303,455", "303,455", [[303, 303], [455, 455]], False),
        ("200,300", "200,300", [[200, 200], [300, 300]], False),
        ("3-7,5-10", "3-7,5-10", [[3, 7], [5, 10]], False),
        ("8;10;12", "8;10;12", [[8, 8], [10, 10], [12, 12]], False),
        ("280; 420", "280; 420", [[280, 280], [420, 420]], False),
        ("1,3;5-7", "1,3;5-7", [[1, 1], [3, 3], [5, 7]], False),
        ("200,300 (noted)", "200,300", [[200, 200], [300, 300]], True),
        ("1,<!-- editor note -->3", "1,3", [[1, 1], [3, 3]], False),
    ],
)
def test_quantity_alternatives_export_first_listed_and_every_alternative(
    raw, cleaned, alternatives, noted
):
    entry = export_quantity(raw)
    assert entry["item_id"] == 995
    assert entry["quantity"] == alternatives[0]
    assert entry["quantity_raw"] == cleaned
    assert entry["quantity_alternatives"] == [
        {"quantity": alternative} for alternative in alternatives
    ]
    assert entry["quantity_selection"] == "unknown"
    assert entry.get("noted", False) is noted


def test_thousands_separator_stays_raw_without_alternatives():
    entry = export_quantity("1,000")
    assert "quantity" not in entry
    assert entry["quantity_raw"] == "1,000"
    assert "quantity_alternatives" not in entry
    assert "quantity_selection" not in entry


@pytest.mark.parametrize(
    "raw, expected, noted",
    [
        ("1000", [1000, 1000], False),
        ("3-5", [3, 5], False),
        ("3 – 5", [3, 5], False),
        ("100-200 (noted)", [100, 200], True),
        ("1<!-- Hydra editor note -->", [1, 1], False),
        ("100-299<!-- separate 500 drop -->", [100, 299], False),
    ],
)
def test_plain_quantities_ranges_and_noted_comments_remain_numeric(
    raw, expected, noted
):
    entry = export_quantity(raw)
    assert entry["quantity"] == expected
    assert "quantity_raw" not in entry
    assert "quantity_alternatives" not in entry
    assert entry.get("noted", False) is noted


def test_cached_ent_logs_export_both_noted_alternatives():
    pages = json.loads(CORPUS.read_text(encoding="utf-8"))
    lookup = drops_tables.ItemIdLookup([fake_item(1511, "Logs")])
    table = next(
        table
        for table in drops_wikitext.parse_all_drop_tables(pages["Ent"])
        if any(drop.name == "Logs" for drop in table.drops)
    )
    exported = drops_tables.build_table_json(
        drops_tables.build_table_spec("Ent", table, lookup)
    )
    logs = next(entry for entry in exported["entries"] if entry.get("name") == "Logs")
    assert logs["quantity"] == [1, 1]
    assert logs["quantity_alternatives"] == [{"quantity": [1, 1]}, {"quantity": [2, 2]}]
    assert logs["quantity_selection"] == "unknown"
    assert logs["quantity_raw"] == "1,2"
    assert logs["noted"] is True


def test_repeated_generation_is_byte_identical(tmp_path):
    generate(tmp_path / "a", limit=150)
    generate(tmp_path / "b", limit=150)
    names = sorted(path.name for path in (tmp_path / "a").iterdir())
    assert names == sorted(path.name for path in (tmp_path / "b").iterdir())
    assert "npc-drops.json" in names
    for name in names:
        assert (tmp_path / "a" / name).read_bytes() == (
            tmp_path / "b" / name
        ).read_bytes(), name
