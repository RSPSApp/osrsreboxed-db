"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Turns parsed OSRS Wiki drop lines into the npc drops JSON dump.

Resolves each drop's item ID against the project's own item database, works out
the weight and roll denominator of every table, and aggregates the result into
the three exported files:

    npc-drops.json      meta, drop tables, and the npcs that roll them
    subtables.json      shared tables (rare drop table, gem table, herbs, seeds)
    unresolved-items.json   drop names that matched no item in the database

Item and npc IDs come from the databases already in this repository, so no
game cache or third-party dump is needed.

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
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import groupby
from math import gcd
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts.drops import drops_wikitext as wikitext
from scripts.drops.drops_wikitext import (
    SECTION_GUARANTEED,
    SECTION_MAIN,
    SECTION_TERTIARY,
    ParsedDrop,
    ParsedDropTable,
)

logger = logging.getLogger(__name__)

# The wiki page holding the shared drop tables, and the page holding the God
# Wars bosses' variant rare drop, gem and mega-rare tables.
SHARED_TABLE_PAGE = "Drop table"
GWD_SHARED_TABLE_PAGE = "God Wars Dungeon-variant rare drop table"
SHARED_TABLE_PAGES = [SHARED_TABLE_PAGE, GWD_SHARED_TABLE_PAGE]

# Shared tables, keyed by the name monster tables reference them with, mapped to
# the level-2 heading their drop lines live under on SHARED_TABLE_PAGE.
SHARED_TABLE_SECTIONS = [
    ("rareDrop", "Rare drop table", "rare drop table"),
    ("gem", "Gem drop table", "gem drop table"),
    ("megaRare", "Mega-rare drop table", "mega-rare drop table"),
    ("herb", "Herb drop table", "herb drop table"),
    ("usefulHerb", "Useful herb drop table", "useful herb drop table"),
    ("combatHerb", "Combat herb drop table", "combat herb drop table"),
    ("seed", "General seed drop table", "general seed drop table"),
    ("rareSeed", "Rare seed drop table", "rare seed drop table"),
    # Referenced from the gem table; monsters never roll it directly.
    ("talisman", "Talisman drop table", "talisman drop table"),
    (
        "gwdRareDrop",
        "God Wars Dungeon-variant Rare Drop Table",
        "God Wars Dungeon-variant rare drop table",
    ),
    (
        "gwdGem",
        "God Wars Dungeon-variant Gem Drop Table",
        "God Wars Dungeon-variant gem drop table",
    ),
    (
        "gwdMegaRare",
        "God Wars Dungeon-variant Mega-rare Drop Table",
        "God Wars Dungeon-variant mega-rare drop table",
    ),
]

# Shared tables that live on a page other than SHARED_TABLE_PAGE.
SHARED_TABLE_SOURCE_PAGES = {
    "gwdRareDrop": GWD_SHARED_TABLE_PAGE,
    "gwdGem": GWD_SHARED_TABLE_PAGE,
    "gwdMegaRare": GWD_SHARED_TABLE_PAGE,
}

# Shared tables reference each other by display name (the rare drop table rolls
# the gem table on 20/128). Those rows are refs, not items.
NESTED_TABLE_REFS = {
    "rare drop table": "rareDrop",
    "gem drop table": "gem",
    "mega-rare drop table": "megaRare",
    "megarare drop table": "megaRare",
    "herb drop table": "herb",
    "seed drop table": "seed",
    "general seed drop table": "seed",
    "rare seed drop table": "rareSeed",
    "talisman": "talisman",
    "talisman drop table": "talisman",
    "god wars dungeon-variant gem drop table": "gwdGem",
    "god wars dungeon-variant mega-rare drop table": "gwdMegaRare",
}

PRE_ROLL_SUBSECTION = "Pre-roll"

# A coin footnote saying the published rate also counts coins rolled from the
# shared gem and rare drop tables (the God Wars bosses). Those tables roll their
# own coins here, so the main table's coins are the slots left over.
COIN_REMAINDER_NOTE = re.compile(
    r"Coins come from rolls on [^.<]*\bGDT and RDT\b", re.I
)


@dataclass
class ResolvedEntry:
    """A drop line with its item ID and rate resolved."""

    item_id: Optional[int]
    name: str
    quantity: str
    weight: Optional[int] = None
    out_of: Optional[int] = None
    roll_denominator: Optional[int] = None
    subsection: str = ""
    rarity_raw: str = ""
    assumed_rarity: bool = False
    # "remainder" when the weight is what the pool leaves, with the source's own
    # rate kept in published_rarity.
    weight_basis: str = ""
    published_rarity: str = ""
    is_nothing: bool = False
    is_noted: bool = False
    clue_scroll_box: bool = False
    brimstone_combat_roll: bool = False
    brimstone_konar_bonus: bool = False
    notes: List[str] = field(default_factory=list)
    quantity_condition: Optional[Dict[str, str]] = None
    bundle_ref: str = ""
    bundle_eligibility: List[str] = field(default_factory=list)
    bonus_drops: List["ResolvedEntry"] = field(default_factory=list)


@dataclass
class SeparateRoll:
    """Main-table drops rolled on their own denominator rather than the table pool."""

    subsection: str
    access_numerator: int
    access_denominator: int
    entries: List[ResolvedEntry]


@dataclass
class DropTableSpec:
    """A single resolved drop table, ready for export."""

    table_id: str
    label: str
    table_name: str
    wiki_page: str
    npc_ids: List[int]
    excluded_npc_ids: List[int] = field(default_factory=list)
    guaranteed: List[ResolvedEntry] = field(default_factory=list)
    pre_roll: List[ResolvedEntry] = field(default_factory=list)
    pre_roll_separate: List[SeparateRoll] = field(default_factory=list)
    main: List[ResolvedEntry] = field(default_factory=list)
    main_max_roll: Optional[int] = None
    separate_rolls: List[SeparateRoll] = field(default_factory=list)
    subtable_accesses: List[wikitext.ParsedSubtableAccess] = field(default_factory=list)
    tertiary: List[ResolvedEntry] = field(default_factory=list)
    unresolved_items: List[str] = field(default_factory=list)
    reward_chain: Optional[Dict] = None
    tertiary_groups: List[Dict] = field(default_factory=list)

    def has_drop_content(self) -> bool:
        """True when the table resolved to anything worth exporting."""
        return bool(
            self.guaranteed
            or self.main
            or self.pre_roll
            or self.pre_roll_separate
            or self.separate_rolls
            or self.subtable_accesses
            or self.tertiary
            or self.reward_chain
        )


# ---------------------------------------------------------------------------
# Item ID lookup
# ---------------------------------------------------------------------------


class ItemIdLookup:
    """Resolves wiki drop names to item IDs using the project's item database."""

    def __init__(self, items):
        """
        :param items: Iterable of osrsreboxed item objects.
        """
        # Wiki names are checked first: several items share a plain name
        # ("Coins" is 617, 995, 6964 and 8890) but their wiki names do not.
        self.by_wiki_name: Dict[str, int] = {}
        self.by_name: Dict[str, int] = {}
        # Where several items share a name, prefer the one players actually
        # trade ("Ensouled abyssal head (Item)" over "… (Drop)"), then the
        # lowest ID, which is the first of a numbered family such as the 138
        # elite clue scroll steps.
        for item in sorted(
            items, key=lambda entry: (not entry.tradeable_on_ge, entry.id)
        ):
            if item.duplicate or item.noted or item.placeholder or item.stacked:
                continue
            if item.wiki_name:
                self.by_wiki_name.setdefault(self._normalize(item.wiki_name), item.id)
            if item.name:
                self.by_name.setdefault(self._normalize(item.name), item.id)
        self.unresolved: Dict[str, int] = {}

    @staticmethod
    def _normalize(name: str) -> str:
        return re.sub(r"\s+", " ", name.strip().lower())

    def resolve(self, wiki_name: str) -> Optional[int]:
        """Look up the item ID for a wiki drop name.

        Wiki drop names carry qualifiers the item database writes differently,
        e.g. the version anchor in ``Bird nest (egg)#Blue egg``, so a few
        progressively looser forms are tried before giving up.

        :param wiki_name: The drop name as written on the wiki.
        :return: The item ID, or None when nothing matches.
        """
        for candidate in self._candidates(self._normalize(wiki_name)):
            item_id = self.by_wiki_name.get(candidate, self.by_name.get(candidate))
            if item_id is not None:
                return item_id
        self.unresolved[wiki_name] = self.unresolved.get(wiki_name, 0) + 1
        return None

    @staticmethod
    def _candidates(name: str):
        yield name
        # Anchors point at one version of a versioned item page:
        # "Bird nest (egg)#Blue egg" is wiki name "Bird nest (egg) (Blue egg)".
        if "#" in name:
            base, _, anchor = name.partition("#")
            base, anchor = base.strip(), anchor.strip()
            if base and anchor:
                yield f"{base} ({anchor})"
            if base:
                yield base
                name = base
        # Wiki disambiguators the item database does not carry.
        without_qualifier = re.sub(r"\s*\([^)]*\)$", "", name).strip()
        if without_qualifier and without_qualifier != name:
            yield without_qualifier
        if name.endswith("s"):
            yield name[:-1]


# ---------------------------------------------------------------------------
# Table naming
# ---------------------------------------------------------------------------


def display_wiki_page_name(wiki_page: str) -> str:
    """Turn an underscored wiki page key back into its display title."""
    return " ".join(part for part in wiki_page.split("_") if part)


def _wiki_page_base(wiki_page: str) -> str:
    parts = [re.sub(r"[^A-Za-z0-9]", "", part) for part in wiki_page.split("_") if part]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    head = parts[0][:1].lower() + parts[0][1:]
    return head + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _table_name_suffix(table_name: str) -> Optional[str]:
    if table_name.lower() == "drops":
        return None
    match = re.search(r"(\d+)", table_name)
    return match.group(1) if match else None


def _drop_variant_suffix(drop_variant: str) -> Optional[str]:
    if not drop_variant.strip():
        return None
    normalized = drop_variant.lower()
    if "wilderness" in normalized:
        return "Wilderness"
    if "catacombs" in normalized and "standard" not in normalized:
        return "Catacombs"
    parts = [
        re.sub(r"[^A-Za-z0-9]", "", part)
        for part in re.split(r"[\s,]+", drop_variant)
        if part and part.lower() != "and"
    ]
    suffix = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return suffix or None


def _camel_to_snake(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def _table_id(wiki_page: str, table_name: str, drop_variant: str) -> str:
    suffix = _table_name_suffix(table_name) or _drop_variant_suffix(drop_variant)
    var_name = _wiki_page_base(wiki_page) + "DropTable" + (suffix or "")
    if var_name.endswith("DropTable"):
        var_name = var_name[: -len("DropTable")]
    return _camel_to_snake(var_name)


def _table_identifier(wiki_page: str, table_name: str, drop_variant: str) -> str:
    display_name = display_wiki_page_name(wiki_page)
    if drop_variant.strip():
        return f"{display_name} {drop_variant}"
    if table_name.lower() == "drops":
        return f"{display_name} Drops"
    return f"{display_name} {table_name}"


# ---------------------------------------------------------------------------
# Rate resolution
# ---------------------------------------------------------------------------


def _resolve_entry(drop: ParsedDrop, items: ItemIdLookup) -> Optional[ResolvedEntry]:
    """Resolve one parsed drop line into an export entry, or None to skip it."""
    if drop.is_nothing:
        if drop.section != SECTION_MAIN:
            return None
        rate = wikitext.parse_main_rarity(drop.rarity)
        if rate is None:
            return None
        weight, roll_denominator = rate
        return ResolvedEntry(
            item_id=None,
            name=drop.name,
            quantity="1",
            weight=weight,
            roll_denominator=roll_denominator,
            subsection=drop.subsection,
            is_nothing=True,
        )

    if not wikitext.has_known_drop_rate(drop.rarity):
        return None

    item_id = items.resolve(drop.name)
    if item_id is None:
        return None

    entry = ResolvedEntry(
        item_id=item_id,
        name=drop.name,
        quantity=drop.quantity,
        subsection=drop.subsection,
        rarity_raw=drop.rarity,
        assumed_rarity=drop.assumed_rarity,
        is_noted=drop.is_noted,
        clue_scroll_box=drop.clue_scroll_box,
        notes=list(drop.notes),
        quantity_condition=drop.quantity_condition,
        bundle_ref=drop.bundle_ref,
        bundle_eligibility=list(drop.bundle_eligibility),
    )

    if drop.section == SECTION_GUARANTEED:
        return entry
    if drop.section == SECTION_MAIN:
        rate = wikitext.parse_main_rarity(drop.rarity)
        if rate is None:
            return None
        entry.weight, entry.roll_denominator = rate
        return entry

    # Tertiary
    if wikitext.is_brimstone_rarity(drop.rarity):
        entry.brimstone_combat_roll = True
        entry.brimstone_konar_bonus = wikitext.has_brimstone_konar_bonus(drop.rarity)
        return entry
    rate = wikitext.parse_tertiary_rarity(drop.rarity)
    if rate is None:
        return None
    entry.weight, entry.out_of = rate
    return entry


def _bundle_dropped_together(main: List[ResolvedEntry]) -> List[ResolvedEntry]:
    """Merge adjacent main-table rows the wiki footnotes as dropped together.

    Exactly two adjacent rows in one subsection, sharing the footnote and the
    same rate, become one slot: the second row moves into the first row's
    ``bonus_drops``. Any other shape (a lone row whose partner did not resolve,
    rows at different rates, three or more rows) is left as separate slots,
    because the source then does not establish one slot.
    """
    bundled: List[ResolvedEntry] = []
    index = 0
    while index < len(main):
        entry = main[index]
        run = [entry]
        if entry.bundle_ref:
            while index + len(run) < len(main):
                candidate = main[index + len(run)]
                if (
                    candidate.bundle_ref != entry.bundle_ref
                    or candidate.subsection != entry.subsection
                ):
                    break
                run.append(candidate)
        first, partners = run[0], run[1:]
        if (
            len(partners) == 1
            and not first.is_nothing
            and not partners[0].is_nothing
            and (first.weight, first.roll_denominator)
            == (partners[0].weight, partners[0].roll_denominator)
            and first.bundle_eligibility == partners[0].bundle_eligibility
            and first.quantity_condition == partners[0].quantity_condition
            and wikitext.parse_quantity_alternatives(partners[0].quantity) is None
            and _parse_quantity(partners[0].quantity) is not None
        ):
            first.bonus_drops.append(partners[0])
            bundled.append(first)
        else:
            if len(partners) > 1:
                logger.warning(
                    "Footnote %r joins %d rows; left as separate slots",
                    entry.bundle_ref,
                    len(run),
                )
            bundled.extend(run)
        index += len(run)
    return bundled


def _finalize_main_rolls(
    main: List[ResolvedEntry], subtable_accesses: List[wikitext.ParsedSubtableAccess]
) -> Tuple[List[ResolvedEntry], Optional[int], List[SeparateRoll]]:
    """Split main-table drops into the shared pool and their own separate rolls.

    Drops are written against whatever denominator the wiki used, so the most
    populated denominator becomes the table's pool and everything else becomes
    an independent roll.

    :param main: Resolved main-table entries.
    :param subtable_accesses: Shared table accesses on the same table.
    :return: A (pool entries, pool denominator, separate rolls) tuple.
    """
    if not main:
        return [], (subtable_accesses[0].denominator if subtable_accesses else None), []

    default_denominator = subtable_accesses[0].denominator if subtable_accesses else 128
    by_denominator: Dict[int, List[ResolvedEntry]] = {}
    for entry in main:
        denominator = entry.roll_denominator or default_denominator
        by_denominator.setdefault(denominator, []).append(entry)

    primary = max(
        by_denominator.items(),
        key=lambda item: (
            len(item[1]),
            sum(entry.weight or 0 for entry in item[1]),
            -item[0],
        ),
    )[0]

    separate_rolls = []
    for denominator, entries in by_denominator.items():
        if denominator == primary:
            continue
        by_subsection: Dict[str, Dict[int, List[ResolvedEntry]]] = {}
        for entry in entries:
            subsection = entry.subsection or "Other"
            by_subsection.setdefault(subsection, {}).setdefault(
                entry.weight or 1, []
            ).append(entry)
        for subsection, by_weight in by_subsection.items():
            for weight, weight_entries in by_weight.items():
                separate_rolls.append(
                    SeparateRoll(subsection, weight, denominator, weight_entries)
                )

    return by_denominator[primary], primary, separate_rolls


def _exclusive_source_pool(
    pool: List[ResolvedEntry],
    subtable_accesses: List[wikitext.ParsedSubtableAccess],
    source: str,
    unresolved: List[str],
) -> Tuple[List[ResolvedEntry], int, List[wikitext.ParsedSubtableAccess]]:
    """Flatten one source-stated exclusive loot pool without rounding its rates.

    GWDRDT replaces normal loot; uniques with different denominators still
    occupy that same pool. Its inclusive coin row is the residual after all
    other exact outcomes, not after discarding uniques into independent rolls.
    """
    if unresolved:
        raise ValueError(
            f"{source}: unresolved exclusive-pool rows: {', '.join(unresolved)}"
        )
    footnoted = [
        entry
        for entry in pool
        if entry.name == "Coins"
        and any(COIN_REMAINDER_NOTE.search(note) for note in entry.notes)
    ]
    if len(footnoted) != 1:
        raise ValueError(f"{source}: expected one source-stated inclusive coin row")
    coins = footnoted[0]

    def exact_rate(entry: ResolvedEntry) -> Fraction:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", entry.rarity_raw)
        if not match or entry.assumed_rarity or Fraction(match.group(2)) == 0:
            raise ValueError(
                f"{source}: unsupported source rate for {entry.name}: {entry.rarity_raw}"
            )
        rate = Fraction(match.group(1)) / Fraction(match.group(2))
        if not 0 <= rate <= 1:
            raise ValueError(
                f"{source}: invalid source rate for {entry.name}: {entry.rarity_raw}"
            )
        return rate

    rates = [exact_rate(entry) if entry is not coins else None for entry in pool]
    access_rates = [Fraction(a.numerator, a.denominator) for a in subtable_accesses]
    remainder = (
        1
        - sum((rate for rate in rates if rate is not None), Fraction(0))
        - sum(access_rates, Fraction(0))
    )
    if not 0 < remainder <= exact_rate(coins):
        raise ValueError(
            f"{source}: coin remainder {remainder} conflicts with inclusive source rate {coins.rarity_raw}"
        )
    rates[pool.index(coins)] = remainder
    pool_size = 1
    for rate in rates + access_rates:
        pool_size = pool_size * rate.denominator // gcd(pool_size, rate.denominator)
    entries = [
        replace(
            entry,
            weight=rate.numerator * (pool_size // rate.denominator),
            out_of=pool_size,
            roll_denominator=pool_size,
            published_rarity=entry.rarity_raw,
            weight_basis="remainder" if entry is coins else "",
        )
        for entry, rate in zip(pool, rates)
    ]
    accesses = [
        replace(
            access,
            numerator=rate.numerator * (pool_size // rate.denominator),
            denominator=pool_size,
        )
        for access, rate in zip(subtable_accesses, access_rates)
    ]
    return entries, pool_size, accesses


def build_table_spec(
    wiki_page: str, table: ParsedDropTable, items: ItemIdLookup
) -> DropTableSpec:
    """Resolve a parsed drop table into an exportable spec.

    :param wiki_page: Underscored wiki page key the table came from.
    :param table: The parsed table.
    :param items: Item ID lookup.
    :return: The resolved :class:`DropTableSpec`.
    """
    guaranteed: List[ResolvedEntry] = []
    main: List[ResolvedEntry] = []
    tertiary: List[ResolvedEntry] = []
    unresolved: List[str] = []
    unresolved_pool: List[str] = []

    # Seed drops are listed individually and as a shared table access on some
    # pages; the access wins so the seeds are not counted twice.
    has_seed_access = any(
        access.table_key in ("seed", "rareSeed") for access in table.subtable_accesses
    )

    # Keep adjacency and run size from source rows, before unresolved items or
    # skipped seed entries disappear. Distinct runs of one footnote stay distinct.
    source_pairs = {}
    for (ref, subsection), run in groupby(
        enumerate(table.drops), key=lambda row: (row[1].bundle_ref, row[1].subsection)
    ):
        rows = list(run)
        if ref and len(rows) == 2:
            for _, source_drop in rows:
                source_pairs[id(source_drop)] = f"{ref}:{rows[0][0]}"

    for drop in table.drops:
        if has_seed_access and drop.subsection.lower() == "seeds":
            continue
        entry = _resolve_entry(drop, items)
        if entry is None:
            if drop.section == SECTION_MAIN:
                unresolved_pool.append(f"{drop.name} ({drop.rarity})")
            if not drop.is_nothing and wikitext.has_known_drop_rate(drop.rarity):
                unresolved.append(drop.name)
            continue
        entry.bundle_ref = source_pairs.get(id(drop), "")
        if drop.section == SECTION_GUARANTEED:
            guaranteed.append(entry)
        elif drop.section == SECTION_TERTIARY:
            tertiary.append(entry)
        else:
            main.append(entry)

    main = _bundle_dropped_together(main)

    reward_chain = None
    tertiary_groups = []
    if table.reward_policy:
        from scripts.drops.reward_chain import build_reward_chain, build_clue_group

        reward_chain, main = build_reward_chain(
            table.reward_policy, main, items, _entry_json, _bonus_drop_json
        )
        tertiary_groups, tertiary = build_clue_group(
            table.reward_policy, tertiary, _entry_json
        )

    pre_roll_drops = []
    standard_main = []
    for entry in main:
        if entry.subsection.lower() == PRE_ROLL_SUBSECTION.lower():
            pre_roll_drops.append(entry)
        else:
            standard_main.append(entry)

    pre_roll, _, pre_roll_separate = _finalize_main_rolls(pre_roll_drops, [])
    accesses = table.subtable_accesses
    if {"gwdRareDrop", "gwdGem"}.issubset(a.table_key for a in accesses):
        main_entries, main_max_roll, accesses = _exclusive_source_pool(
            standard_main, accesses, wiki_page, unresolved_pool
        )
        separate_rolls = []
    else:
        main_entries, main_max_roll, separate_rolls = _finalize_main_rolls(
            standard_main, accesses
        )
    if main_max_roll is not None:
        used = sum(entry.weight or 0 for entry in main_entries) + sum(
            access.numerator for access in accesses
        )
        main_max_roll = max(main_max_roll, used)

    if reward_chain:
        # The source guarantees resources after failed accesses. Published rates
        # describe relative resource weights; condition this remaining pool on access.
        if accesses or separate_rolls or not main_entries:
            raise ValueError("Unsupported conditional resource pool")
        main_max_roll = sum(entry.weight for entry in main_entries)
        main_entries = [
            replace(
                entry,
                out_of=main_max_roll,
                published_rarity=entry.rarity_raw,
                weight_basis="conditional_pool",
            )
            for entry in main_entries
        ]

    return DropTableSpec(
        table_id=_table_id(wiki_page, table.table_name, table.drop_variant),
        label=(table.drop_variant or table.table_name or "Drops"),
        table_name=_table_identifier(wiki_page, table.table_name, table.drop_variant),
        wiki_page=display_wiki_page_name(wiki_page),
        npc_ids=table.npc_ids,
        excluded_npc_ids=list(table.excluded_npc_ids),
        guaranteed=guaranteed,
        pre_roll=pre_roll,
        pre_roll_separate=pre_roll_separate,
        main=main_entries,
        main_max_roll=main_max_roll,
        separate_rolls=separate_rolls,
        subtable_accesses=accesses,
        tertiary=tertiary,
        unresolved_items=list(dict.fromkeys(unresolved)),
        reward_chain=reward_chain,
        tertiary_groups=tertiary_groups,
    )


# ---------------------------------------------------------------------------
# JSON shaping
# ---------------------------------------------------------------------------


def _without_nulls(values: Dict, keep=()) -> Dict:
    return {
        key: value for key, value in values.items() if value is not None or key in keep
    }


def _rarity(weight: Optional[int], out_of: Optional[int]) -> Optional[float]:
    """Chance of a single roll landing on an entry, to seven decimal places."""
    if weight is None or out_of is None or out_of <= 0:
        return None
    return round((weight / out_of) * 10_000_000) / 10_000_000


def _parse_quantity(raw: str) -> Optional[List[int]]:
    """``"1"`` -> [1, 1]; ``"3-5"`` -> [3, 5]; anything else stays raw."""
    # Wiki DropsLine commas separate alternatives, not thousands. Keep those
    # expressions raw rather than inventing a quantity or distribution.
    trimmed = raw.strip()
    if not trimmed:
        return None
    if re.fullmatch(r"\d+", trimmed):
        return [int(trimmed), int(trimmed)]
    match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", trimmed)
    if not match:
        return None
    return [int(match.group(1)), int(match.group(2))]


def _bonus_drop_json(entry: ResolvedEntry) -> Dict:
    """A row dropped together with its slot's first row: item and amount only."""
    alternatives = wikitext.parse_quantity_alternatives(entry.quantity)
    quantity = (
        list(alternatives[0]) if alternatives else _parse_quantity(entry.quantity)
    )
    return _without_nulls(
        {
            "item_id": entry.item_id,
            "name": entry.name,
            "quantity": quantity,
            "quantity_raw": entry.quantity if quantity is None else None,
            "noted": True if entry.is_noted else None,
        }
    )


def _entry_json(
    entry: ResolvedEntry,
    out_of: Optional[int],
    always: bool = False,
    separate: bool = False,
    pre_roll: bool = False,
) -> Optional[Dict]:
    if entry.is_nothing:
        return _without_nulls(
            {
                "nothing": True,
                "weight": entry.weight,
                "out_of": out_of,
                "pre_roll": True if pre_roll else None,
                "separate_roll": True if separate else None,
            }
        )
    if not entry.name:
        return None

    alternatives = wikitext.parse_quantity_alternatives(entry.quantity)
    if alternatives:
        # The first-listed alternative is the source's default; the full list
        # stays beside it so a consumer with the right context can choose.
        quantity: Optional[List[int]] = list(alternatives[0])
        quantity_raw: Optional[str] = entry.quantity
        quantity_alternatives: Optional[List[Dict]] = [
            {"quantity": [low, high]} for low, high in alternatives
        ]
        if entry.quantity_condition:
            for alternative in quantity_alternatives[1:]:
                alternative["condition"] = dict(entry.quantity_condition)
            quantity_selection: Optional[str] = "conditional"
        else:
            quantity_selection = "unknown"
    else:
        quantity = _parse_quantity(entry.quantity)
        quantity_raw = entry.quantity if entry.quantity and quantity is None else None
        quantity_alternatives = None
        quantity_selection = None
    rarity = _rarity(entry.weight if entry.weight is not None else 1, out_of)

    return _without_nulls(
        {
            "item_id": entry.item_id,
            "name": entry.name,
            "quantity": quantity,
            "quantity_raw": quantity_raw,
            "quantity_alternatives": quantity_alternatives,
            "quantity_selection": quantity_selection,
            "always": True if always else None,
            "pre_roll": True if pre_roll else None,
            "separate_roll": True if separate else None,
            "weight": entry.weight,
            "out_of": out_of,
            "rarity": rarity,
            "rarity_raw": (
                entry.rarity_raw if entry.rarity_raw and rarity is None else None
            ),
            "section": entry.subsection or None,
            "noted": True if entry.is_noted else None,
            "clue_scroll_box": True if entry.clue_scroll_box else None,
            "assumed_rarity": True if entry.assumed_rarity else None,
            "weight_basis": entry.weight_basis or None,
            "published_rarity": entry.published_rarity or None,
            "notes": entry.notes or None,
            "bonus_drops": [_bonus_drop_json(bonus) for bonus in entry.bonus_drops]
            or None,
        },
        keep=("item_id",),
    )


def _pre_roll_json(entry: ResolvedEntry, separate: bool = False) -> Optional[Dict]:
    """Keep a pre-roll's source probability exact, including decimal fractions.

    Scale decimal components together without reducing integer source slots:
    1/181.1 becomes 10/1811, while 4/540 stays 4/540 so peer rows still share
    their source pool. Invalid probabilities retain raw provenance only.
    """
    out_of = entry.out_of or entry.roll_denominator
    match = wikitext.DECIMAL_FRACTION_RARITY.search(entry.rarity_raw)
    if match:
        numerator, denominator = map(Decimal, match.groups())
        out_of = None
        if denominator > 0 and 0 <= numerator <= denominator:
            places = max(
                0, -numerator.as_tuple().exponent, -denominator.as_tuple().exponent
            )
            scale = 10**places
            entry = replace(entry, weight=int(numerator * scale))
            out_of = int(denominator * scale)
    return _entry_json(entry, out_of=out_of, pre_roll=True, separate=separate)


def build_table_json(spec: DropTableSpec) -> Dict:
    """Shape a resolved drop table into its exported JSON form."""
    entries = []
    for entry in spec.guaranteed:
        row = _entry_json(entry, out_of=None, always=True)
        if row:
            entries.append(row)
    for entry in spec.pre_roll:
        row = _pre_roll_json(entry)
        if row:
            entries.append(row)
    for entry in spec.main:
        row = _entry_json(entry, out_of=entry.out_of or spec.main_max_roll)
        if row:
            entries.append(row)
    for access in spec.subtable_accesses:
        entries.append(
            _without_nulls(
                {
                    "shared_table": access.table_key,
                    "weight": access.numerator,
                    "out_of": access.denominator,
                    "rarity": _rarity(access.numerator, access.denominator),
                    "section": access.subsection or None,
                    "roll_count_weights": access.roll_count_weights or None,
                    "unresolved_roll_count": (
                        True if access.unresolved_roll_count else None
                    ),
                },
                keep=("rarity",),
            )
        )
    for rolls, is_pre_roll in (
        (spec.separate_rolls, False),
        (spec.pre_roll_separate, True),
    ):
        for roll in rolls:
            for entry in roll.entries:
                row = (
                    _pre_roll_json(entry, separate=True)
                    if is_pre_roll
                    else _entry_json(
                        entry,
                        out_of=entry.out_of or roll.access_denominator,
                        separate=True,
                    )
                )
                if row:
                    entries.append(row)

    tertiary = []
    for entry in spec.tertiary:
        if entry.brimstone_combat_roll or entry.brimstone_konar_bonus:
            continue
        row = _entry_json(entry, out_of=entry.out_of)
        if row:
            tertiary.append(row)

    return _without_nulls(
        {
            "table_id": spec.table_id,
            "label": spec.label or "Drops",
            "table_name": spec.table_name,
            "wiki_page": spec.wiki_page,
            "main_max_roll": spec.main_max_roll,
            "entries": entries,
            "tertiary": tertiary,
            "reward_chain": spec.reward_chain,
            "tertiary_groups": spec.tertiary_groups or None,
            "brimstone_key_roll": (
                True
                if any(entry.brimstone_combat_roll for entry in spec.tertiary)
                else None
            ),
            "brimstone_konar_bonus": (
                True
                if any(entry.brimstone_konar_bonus for entry in spec.tertiary)
                else None
            ),
            # Kept as names rather than dropping the whole table.
            "unresolved_items": spec.unresolved_items or None,
        }
    )


class NpcDropsAggregator:
    """Collects drop tables across every monster page and writes the dump.

    Output is keyed by npc ID, each holding the IDs of the tables it rolls, so
    monsters with several drop tables (variants, difficulty tiers) keep all of
    them.
    """

    def __init__(self, npc_names: Optional[Dict[int, str]] = None):
        """
        :param npc_names: Optional npc ID to cache name mapping.
        """
        self.npc_names = npc_names or {}
        self.npcs: Dict[int, Dict] = {}
        self.tables: Dict[str, Dict] = {}
        self.shared_refs = set()
        self.unresolved_items = set()
        self.table_count = 0

    def add(self, spec: DropTableSpec) -> None:
        """Register a resolved drop table and the npcs that roll it."""
        table = build_table_json(spec)
        self.table_count += 1
        table_id = self._register_table(table)

        for access in spec.subtable_accesses:
            self.shared_refs.add(access.table_key)
        self.unresolved_items.update(spec.unresolved_items)

        # Keep known source variants even when this table explicitly excludes
        # them. An empty table list is executable no-loot data, not a lost ID.
        for npc_id in dict.fromkeys(spec.npc_ids + spec.excluded_npc_ids):
            npc = self.npcs.get(npc_id)
            if npc is None:
                npc = _without_nulls(
                    {
                        "npc_id": npc_id,
                        "name": spec.wiki_page,
                        # Cache name, useful for telling variant IDs apart where
                        # the wiki page is shared.
                        "cache_name": self.npc_names.get(npc_id),
                        "wiki_page": spec.wiki_page,
                        "tables": [],
                    }
                )
                self.npcs[npc_id] = npc
            if npc_id in spec.npc_ids and table_id not in npc["tables"]:
                npc["tables"].append(table_id)

    def _register_table(self, table: Dict) -> str:
        """Store a table once and return the ID npcs should reference.

        Table IDs come from wiki page names, so two genuinely different tables
        can derive the same ID. Those get a numeric suffix rather than silently
        overwriting one another.
        """
        base = table["table_id"]
        table_id = base
        suffix = 2
        while True:
            existing = self.tables.get(table_id)
            if existing is None:
                self.tables[table_id] = {**table, "table_id": table_id}
                return table_id
            if existing == {**table, "table_id": table_id}:
                return table_id
            table_id = f"{base}_{suffix}"
            suffix += 1

    def write(self, out_dir: Path, subtables: Dict, wiki_pages_scanned: int) -> None:
        """Write the three dump files to ``out_dir``.

        :param out_dir: Directory to write into (created if missing).
        :param subtables: Shared subtable export, from :func:`export_shared_subtables`.
        :param wiki_pages_scanned: Number of wiki pages processed, for the meta block.
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "generated": date.today().isoformat(),
            "source": "https://oldschool.runescape.wiki",
            "license": "CC BY-NC-SA 3.0 — content from the Old School RuneScape Wiki",
            "id_space": "osrs cache ids (item and npc ids from the osrsreboxed databases)",
            "npc_count": len(self.npcs),
            "table_count": len(self.tables),
            "table_refs": sum(len(npc["tables"]) for npc in self.npcs.values()),
            "wiki_pages_scanned": wiki_pages_scanned,
            "shared_tables": sorted(self.shared_refs),
            "unresolved_item_count": len(self.unresolved_items),
        }

        npcs = {str(npc_id): self.npcs[npc_id] for npc_id in sorted(self.npcs)}
        tables = {table_id: self.tables[table_id] for table_id in sorted(self.tables)}

        with open(out_dir / "npc-drops.json", "w") as out_file:
            json.dump(
                {"meta": meta, "tables": tables, "npcs": npcs}, out_file, indent=2
            )
        with open(out_dir / "subtables.json", "w") as out_file:
            json.dump(subtables, out_file, indent=2)
        with open(out_dir / "unresolved-items.json", "w") as out_file:
            json.dump(sorted(self.unresolved_items), out_file, indent=2)


# ---------------------------------------------------------------------------
# Shared subtables
# ---------------------------------------------------------------------------

ANY_HEADING = re.compile(r"^(=+)\s*([^=\n]+?)\s*=+[ \t]*$", re.M)


def _section_body(page_wikitext: str, heading: str) -> Optional[str]:
    """Return the body under a heading, ending at the next same-or-higher heading."""
    match = re.search(
        r"^(=+)\s*" + re.escape(heading) + r"\s*=+[ \t]*$", page_wikitext, re.I | re.M
    )
    if not match:
        return None
    level = len(match.group(1))
    rest = page_wikitext[match.end() :]
    for following in ANY_HEADING.finditer(rest):
        if len(following.group(1)) <= level:
            return rest[: following.start()]
    return rest


def export_shared_subtables(
    pages: Dict[str, Optional[str]], items: ItemIdLookup
) -> Dict:
    """Extract the shared drop tables from their source wiki pages.

    Shared tables are referenced by name from monster entries and emitted once
    here, rather than inlined into every monster that rolls them.

    :param pages: Source page titles mapped to cached wikitext, or None when unavailable.
    :param items: Item ID lookup.
    :return: Dictionary of shared table name to its entries.
    """
    subtables = {}
    for key, heading, wiki_label in SHARED_TABLE_SECTIONS:
        entries = []
        source_page = SHARED_TABLE_SOURCE_PAGES.get(key, SHARED_TABLE_PAGE)
        page_wikitext = pages.get(source_page)
        body = _section_body(page_wikitext, heading) if page_wikitext else None
        for _, params in wikitext.extract_templates(body or "", "DropsLine"):
            name = params.get("name")
            if not name:
                continue
            quantity = params.get("quantity", "")
            rarity = params.get("rarity", "")
            nested = NESTED_TABLE_REFS.get(name.strip().lower())
            if nested and nested != key:
                entries.append(
                    {"shared_table": nested, "name": name, "rarity_raw": rarity}
                )
            elif name.strip().lower() == "nothing":
                entries.append({"nothing": True, "rarity_raw": rarity})
            else:
                entries.append(
                    {
                        "item_id": items.resolve(name),
                        "name": name,
                        "quantity_raw": quantity,
                        "rarity_raw": rarity,
                    }
                )
        if not entries:
            logger.debug(
                "shared table '%s' — no entries extracted from '%s'",
                key,
                source_page,
            )
        subtables[key] = {
            "name": key,
            "wiki_label": wiki_label,
            "wiki_page": source_page,
            "entries": entries,
        }
        if key == "seed" and body:
            # Each displayed seed table has its own denominator and is selected
            # by an interval of random(CombatLevel * 10), not a merged pool.
            groups = re.findall(
                r"less than (\d+).*?\n(\{\{DropsTableHead\}\}.*?\{\{DropsTableBottom\}\})|"
                r"is (\d+) or greater, the player.*?\n(\{\{DropsTableHead\}\}.*?\{\{DropsTableBottom\}\})",
                body,
                re.S,
            )
            categories = []
            offset = 0
            minimum = 0
            for upper, group, lower, last_group in groups:
                count = len(
                    wikitext.extract_templates(group or last_group, "DropsLine")
                )
                category = {
                    "minimum": minimum,
                    "entries": entries[offset : offset + count],
                }
                if upper:
                    category["maximum_exclusive"] = int(upper)
                    minimum = int(upper)
                categories.append(category)
                offset += count
            if len(categories) != 6 or offset != len(entries):
                raise ValueError("General seed table category structure is incomplete")
            subtables[key].update(
                entries=[], combat_level_multiplier=10, categories=categories
            )
    return subtables
