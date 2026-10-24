"""Primary-source DT2 loot is an ordered replacement chain, not independent odds."""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from osrsreboxed import items_api
from scripts.drops import drops_tables, drops_wikitext


@pytest.fixture(scope="module")
def corpus():
    root = Path(__file__).parents[1]
    pages = json.loads(
        (root / "data/monsters/monsters-wiki-page-text.json").read_text(encoding="utf8")
    )
    return pages, drops_tables.ItemIdLookup(items_api.load())


def exported(corpus, title):
    pages, items = corpus
    table = drops_wikitext.parse_all_drop_tables(pages[title])[0]
    return drops_tables.build_table_json(
        drops_tables.build_table_spec(title, table, items)
    )


@pytest.mark.parametrize(
    "title,unique,orb",
    [
        ("Duke Sucellus", 90, 48),
        ("The Leviathan", 96, 53),
        ("The Whisperer", 64, 34),
        ("Vardorvis", 136, 80),
    ],
)
def test_source_chain_has_conditional_order_and_one_exact_unique_pool(
    corpus, title, unique, orb
):
    table = exported(corpus, title)
    chain = table["reward_chain"]
    assert chain["type"] == "ordered_exclusive"
    assert [
        (stage["key"], stage["weight"], stage["out_of"]) for stage in chain["stages"]
    ] == [
        ("tradeable_uniques", 1, unique),
        ("orb", 1, orb),
        ("tablet", 1, 25),
        ("quartz", 1, 200),
        ("supplies", 1, 5),
    ]
    pool = chain["stages"][0]
    assert pool["main_max_roll"] == 24
    assert sorted(row["weight"] for row in pool["entries"]) == [1, 1, 1, 3, 9, 9]
    assert sum(row["weight"] for row in pool["entries"]) == 24
    for row in pool["entries"]:
        assert row["out_of"] == 24
        assert "separate_roll" not in row
        published = Fraction(row["published_rarity"])
        expected = Fraction(row["weight"], 24 * unique)
        assert published * (3 if "progression" in row else 1) == expected
    assert all(
        row.get("section") not in {"Uniques", "Secondary uniques", "Supplies"}
        for row in table["entries"]
    )


@pytest.mark.parametrize(
    "title", ["Duke Sucellus", "The Leviathan", "The Whisperer", "Vardorvis"]
)
def test_source_chain_preserves_progress_first_receipt_supply_and_clue_contract(
    corpus, title
):
    table = exported(corpus, title)
    stages = table["reward_chain"]["stages"]
    vestige = next(row for row in stages[0]["entries"] if "progression" in row)
    assert vestige["progression"]["hits"] == 3
    assert vestige["progression"]["intermediate_item_id"] == 1635
    assert vestige["progression"]["intermediate_quantities"] == [1, 2]
    assert stages[2]["eligibility"]["type"] == "until_first_received"
    assert stages[2]["source_scaling"]["status"] == "unresolved"
    assert stages[3]["source_scaling"]["status"] == "unresolved"
    supply = stages[4]["entries"]
    assert len(supply) == 1 and len(supply[0]["bonus_drops"]) == 2
    assert all("Clue scroll" not in row["name"] for row in table["tertiary"])
    group = table["tertiary_groups"][0]
    assert group["source_access"] == {"weight": 1, "out_of": 40}
    assert len(group["entries"]) == 4
    assert {row["out_of"] for row in group["entries"]} == {160}
    assert sum(
        Fraction(row["weight"], row["out_of"]) for row in group["entries"]
    ) == Fraction(1, 40)


@pytest.mark.parametrize(
    "old,new",
    [
        ("3/8 chance for a [[chromium ingot]]", "2/8 chance for a [[chromium ingot]]"),
        ("These supplies are all dropped together", "Supplies may drop"),
        ("If unsuccessful, roll 1/25", "If unsuccessful, roll unknown"),
    ],
)
def test_partial_source_contract_fails_closed(corpus, old, new):
    from scripts.drops.reward_chain import parse_reward_policy

    source = corpus[0]["Duke Sucellus"]
    assert old in source
    with pytest.raises(ValueError):
        parse_reward_policy(source.replace(old, new))


def test_unrelated_source_has_no_reward_policy(corpus):
    from scripts.drops.reward_chain import parse_reward_policy

    assert parse_reward_policy(corpus[0]["Abyssal demon"]) is None


def test_chain_schema_validates_all_four_corpus_tables(corpus):
    import validator

    schema = json.loads(
        (Path(__file__).parents[1] / "data/schemas/schema-drops.json").read_text(
            encoding="utf8"
        )
    )
    v = validator.MyValidator(schema)
    for title in ["Duke Sucellus", "The Leviathan", "The Whisperer", "Vardorvis"]:
        assert v.validate(exported(corpus, title)), v.errors


@pytest.mark.parametrize(
    "title", ["Duke Sucellus", "The Leviathan", "The Whisperer", "Vardorvis"]
)
def test_failed_chain_always_selects_conditional_resource_pool(corpus, title):
    table = exported(corpus, title)
    assert table["main_max_roll"] == sum(row["weight"] for row in table["entries"])
    assert all(row["weight_basis"] == "conditional_pool" for row in table["entries"])
    assert all(row["published_rarity"] for row in table["entries"])


@pytest.mark.parametrize(
    "title", ["Duke Sucellus", "The Leviathan", "The Whisperer", "Vardorvis"]
)
def test_quartz_executes_documented_endpoint_without_inventing_curve(corpus, title):
    stage = exported(corpus, title)["reward_chain"]["stages"][3]
    assert stage["source_scaling"]["execution"] == "documented_base_and_endpoint"
    assert stage["source_scaling"]["known_endpoint"] == {
        "kill_count": 300,
        "weight": 1,
        "out_of": 50,
    }


@pytest.mark.parametrize(
    "old,new",
    [
        ("tradeable unique drop table", "tradable unique drop table"),
        ("supply drop table", "supply reward table"),
    ],
)
def test_partial_overview_sentinels_do_not_silently_restore_flat_loot(corpus, old, new):
    from scripts.drops.reward_chain import parse_reward_policy

    with pytest.raises(ValueError):
        parse_reward_policy(corpus[0]["Duke Sucellus"].replace(old, new))
