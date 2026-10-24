"""Source-stated ordered rewards; effective item odds are not executable rolls."""

import re
from dataclasses import replace
from fractions import Fraction
from functools import reduce
from math import gcd


def parse_reward_policy(source):
    """Recognize the complete structural contract, without a page/NPC allowlist."""
    if not all(
        text in source.lower()
        for text in ("tradeable unique drop table", "vestige", "supply drop table")
    ):
        if "vestige" in source.lower() and "if unsuccessful, roll" in source.lower():
            raise ValueError("Incomplete source-stated ordered reward overview")
        return None
    unique = re.findall(
        r"^\* Roll (\d+)/(\d+) for the tradeable unique drop table", source, re.M
    )
    conditional = re.findall(
        r"^\*\* If unsuccessful, roll (\d+)/(\d+) for (.+?)\.\s*$", source, re.M
    )
    if len(unique) != 1 or len(conditional) != 4:
        raise ValueError("Incomplete source-stated ordered reward overview")
    stages = []
    for numerator, denominator, target in conditional:
        link = re.search(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", target)
        stages.append(
            {
                "weight": int(numerator),
                "out_of": int(denominator),
                "name": link.group(1) if link else None,
            }
        )
    if [stage["name"] is None for stage in stages] != [False, False, False, True]:
        raise ValueError("Unsupported source ordered reward targets")
    if not all(
        word in stages[i]["name"].lower()
        for i, word in enumerate(("orb", "tablet", "quartz"))
    ):
        raise ValueError("Unsupported source ordered secondary reward order")
    if "supply drop table" not in conditional[-1][2].lower():
        raise ValueError("Missing final supply access")
    if not re.search(r"These supplies are all dropped together", source, re.I):
        raise ValueError("Source does not establish one supply bundle")
    if not re.search(r"3/8 chance[^\n]*vestige", source, re.I) or not re.search(
        r"3/8 chance for (?:a )?(?:\[\[)?chromium ingot(?:\]\])?", source, re.I
    ):
        raise ValueError("Unsupported conditional unique distribution")
    if not re.search(r"1/8 chance[^\n]*Virtus[^\n]*1/3", source, re.I):
        raise ValueError("Unsupported Virtus selection")
    if not all(
        re.search(pattern, source, re.I)
        for pattern in (
            r"first roll[^\n]*gold ring",
            r"second[^\n]*two gold rings",
            r"third[^\n]*vestige[^\n]*reset",
        )
    ):
        raise ValueError("Source does not establish cyclic vestige progress")
    if not re.search(r"Afterwards, the item will no longer be dropped", source, re.I):
        raise ValueError("Source does not establish first-only tablet")
    clue = re.findall(r"^\* Once[^\n]*and (\d+)/(\d+) for a clue scroll", source, re.M)
    if len(clue) != 1:
        raise ValueError("Missing independent clue access")
    return {
        "unique": {"weight": int(unique[0][0]), "out_of": int(unique[0][1])},
        "secondary": stages,
        "clue": {"weight": int(clue[0][0]), "out_of": int(clue[0][1])},
        "quartz_endpoint_verified": bool(
            re.search(r"1/200 to 1/50[^\n]*300 kill count", source, re.I)
        ),
    }


def _rate(row):
    if row.assumed_rarity or not re.fullmatch(
        r"\d+(?:\.\d+)?/\d+(?:\.\d+)?", row.rarity_raw
    ):
        raise ValueError("Unsupported source reward rate: " + row.name)
    numerator, denominator = row.rarity_raw.split("/")
    rate = Fraction(numerator) / Fraction(denominator)
    if not 0 < rate <= 1:
        raise ValueError("Invalid source reward rate: " + row.name)
    return rate


def build_reward_chain(policy, rows, items, entry_json, bonus_json):
    """Move source-owned rows into exact stages, retaining all item metadata."""
    unique = [row for row in rows if row.subsection == "Uniques"]
    secondary = [row for row in rows if row.subsection == "Secondary uniques"]
    supplies = [row for row in rows if row.subsection == "Supplies"]
    if (len(unique), len(secondary), len(supplies)) != (6, 3, 3):
        raise ValueError("Unresolved or unsupported source reward rows")
    vestiges = [row for row in unique if "vestige" in row.name.lower()]
    if len(vestiges) != 1:
        raise ValueError("Ambiguous source vestige outcome")
    vestige = vestiges[0]
    gold_ring = items.resolve("Gold ring")
    if gold_ring is None:
        raise ValueError("Unresolved source progress reward Gold ring")
    access = Fraction(policy["unique"]["weight"], policy["unique"]["out_of"])
    conditional = [_rate(row) / access * (3 if row is vestige else 1) for row in unique]
    if sum(conditional, Fraction(0)) != 1 or sorted(conditional) != sorted(
        [Fraction(3, 8), Fraction(3, 8), Fraction(1, 8)] + [Fraction(1, 24)] * 3
    ):
        raise ValueError("Published item rates disagree with conditional source pool")
    denominator = reduce(
        lambda a, b: a * b // gcd(a, b), [rate.denominator for rate in conditional], 1
    )
    outcomes = []
    for row, rate in zip(unique, conditional):
        rewritten = replace(
            row,
            weight=rate.numerator * (denominator // rate.denominator),
            out_of=denominator,
            published_rarity=row.rarity_raw,
        )
        exported = entry_json(rewritten, out_of=denominator)
        if row is vestige:
            exported["progression"] = {
                "type": "cyclic_hits",
                "state_key": "vestige:" + str(row.item_id),
                "hits": 3,
                "intermediate_item_id": gold_ring,
                "intermediate_quantities": [1, 2],
            }
        outcomes.append(exported)
    stages = [
        {
            "key": "tradeable_uniques",
            **policy["unique"],
            "main_max_roll": denominator,
            "entries": outcomes,
        }
    ]
    for key, source in zip(("orb", "tablet", "quartz"), policy["secondary"]):
        matched = [
            row for row in secondary if row.name.casefold() == source["name"].casefold()
        ]
        if len(matched) != 1:
            raise ValueError("Unresolved source secondary reward: " + source["name"])
        row = matched[0]
        exported = entry_json(
            replace(row, weight=1, out_of=1, published_rarity=row.rarity_raw), out_of=1
        )
        stage = {
            "key": key,
            "weight": source["weight"],
            "out_of": source["out_of"],
            "main_max_roll": 1,
            "entries": [exported],
        }
        if key in ("tablet", "quartz"):
            state_key = "first:" + str(row.item_id)
            stage["record_first_received"] = {"state_key": state_key}
            stage["source_scaling"] = {
                "status": "unresolved",
                "execution": "documented_base_only",
                "before_first_received": True,
            }
            if key == "tablet":
                stage["eligibility"] = {
                    "type": "until_first_received",
                    "state_key": state_key,
                }
            elif policy["quartz_endpoint_verified"]:
                stage["source_scaling"]["execution"] = "documented_base_and_endpoint"
                stage["source_scaling"]["known_endpoint"] = {
                    "kill_count": 300,
                    "weight": 1,
                    "out_of": 50,
                }
                stage["source_scaling"]["after_first_received"] = {
                    "weight": 1,
                    "out_of": 200,
                }
        stages.append(stage)
    supply_source = policy["secondary"][3]
    supply = entry_json(
        replace(
            supplies[0], weight=1, out_of=1, published_rarity=supplies[0].rarity_raw
        ),
        out_of=1,
    )
    supply["bonus_drops"] = [bonus_json(row) for row in supplies[1:]]
    stages.append(
        {
            "key": "supplies",
            "weight": supply_source["weight"],
            "out_of": supply_source["out_of"],
            "main_max_roll": 1,
            "entries": [supply],
        }
    )
    selected = {id(row) for row in unique + secondary + supplies}
    return {
        "type": "ordered_exclusive",
        "state_domain": "forgotten_four",
        "stages": stages,
    }, [row for row in rows if id(row) not in selected]


def build_clue_group(policy, rows, entry_json):
    clues = [
        row
        for row in rows
        if row.clue_scroll_box and row.name.startswith("Clue scroll (")
    ]
    expected = Fraction(policy["clue"]["weight"], policy["clue"]["out_of"])
    if len(clues) != 4 or sum((_rate(row) for row in clues), Fraction(0)) != expected:
        raise ValueError("Clue outcomes disagree with independent source access")
    group = {
        "type": "exclusive",
        "source_access": policy["clue"],
        "entries": [entry_json(row, out_of=row.out_of) for row in clues],
    }
    return [group], [row for row in rows if row not in clues]
