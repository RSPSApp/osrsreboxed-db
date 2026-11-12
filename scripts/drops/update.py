"""
Author:  Toby Wisener
Email:   tobywisener@googlemail.com

Description:
Program to generate the OSRS npc drops JSON dump.

Reads the monster wiki page text already fetched by ``scripts.monsters.update``,
parses every ``==Drops==`` table on those pages, and writes the dump to
``docs/drops-json/``. Item and npc IDs come from the databases in this
repository, so the only network access is for wiki pages missing from the
caches under ``data/drops/``: the shared drop table pages (``Drop table`` and
the God Wars rare drop table) and the include-only ``Template:Uniques/<name>``
pages that hold some monsters' unique drops.

Usage:
    python -m scripts.drops.update
    python -m scripts.drops.update --limit 50 --out /tmp/drops

Set SOURCE_DATE_EPOCH to Unix seconds to pin the generated metadata date for
reproducible exports across build days; otherwise the current date is used.

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

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Iterable, Optional
from urllib.parse import unquote

import config
from builders.run_log import begin_run
from osrsreboxed import items_api
from scripts.drops import drops_tables
from scripts.drops.drops_tables import ItemIdLookup, NpcDropsAggregator
from scripts.drops.drops_wikitext import (
    has_non_numeric_npc_id,
    parse_all_drop_tables,
    unique_template_titles,
)
from scripts.wiki.wiki_page_text import WikiPageText

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"

# Alternate encounters (Echo bosses) share npc IDs with their canonical page.
ALTERNATE_ENCOUNTER_MARKER = "(echo)"


def load_npc_cache_names() -> Dict[int, str]:
    """Map npc ID to its cache name, used to tell shared-page variants apart."""
    with open(
        Path(config.DATA_MONSTERS_PATH / "monsters-cache-data.json")
    ) as monsters_file:
        cache_data = json.load(monsters_file)
    return {int(npc_id): monster["name"] for npc_id, monster in cache_data.items()}


def load_monster_wikitext() -> Dict[str, str]:
    """Load currently listed monster pages from the incremental wikitext cache.

    Renamed/deleted pages remain in that cache. The category title listing is
    authoritative, as in the shops exporter; NPC IDs cannot identify obsolete
    pages because distinct current encounters can legitimately share those IDs.
    """
    page_text_file = Path(config.DATA_MONSTERS_PATH / "monsters-wiki-page-text.json")
    if not page_text_file.exists():
        raise SystemExit(
            f">>> ERROR: {page_text_file.name} not found. Run scripts.monsters.update first."
        )
    titles_file = Path(config.DATA_MONSTERS_PATH / "monsters-wiki-page-titles.json")
    if not titles_file.exists():
        raise SystemExit(
            f">>> ERROR: {titles_file.name} not found. Run scripts.monsters.update first."
        )
    with open(titles_file) as titles:
        current_titles = json.load(titles)
    if not current_titles:
        raise SystemExit(
            f">>> ERROR: {titles_file.name} is empty; refusing drop export."
        )
    with open(page_text_file) as wiki_file:
        cached = json.load(wiki_file)
    current = {title: text for title, text in cached.items() if title in current_titles}
    logger.info("Ignoring %d obsolete cached monster pages", len(cached) - len(current))
    return current


# Reviewed source anchors for bare drop names that are also a later variant's
# exact item name. The wiki's Giantsoul amulet page declares version 1 as
# Uncharged (id 30637), and both Royal Titans drop that version; the charged
# 30638 is created by charging it.
REVIEWED_DROP_VERSIONS = {
    "Giantsoul amulet": "Uncharged",
}


def _item_page_and_version(item) -> Optional[tuple]:
    """Split an item's wiki URL into its page title and version anchor."""
    url = item.wiki_url or ""
    if "/w/" not in url:
        return None
    page, _, anchor = url.split("/w/", 1)[1].partition("#")
    page = unquote(page).replace("_", " ").strip()
    anchor = unquote(anchor).replace("_", " ").strip()
    return (page, anchor or None) if page else None


def load_drop_version_items(items: Iterable) -> Dict[str, int]:
    """Resolve only reviewed bare drop names to the source's declared version."""
    reviewed = {}
    for item in items:
        if item.duplicate or item.noted or item.placeholder or item.stacked:
            continue
        page_version = _item_page_and_version(item)
        if not page_version:
            continue
        page, version = page_version
        if version and REVIEWED_DROP_VERSIONS.get(page) == version:
            reviewed[page] = item.id
    return reviewed


def load_unique_template_wikitext(
    names: Iterable[str], refresh: bool = False
) -> Dict[str, str]:
    """Load cached ``{{Uniques/<name>}}`` template wikitext, fetching missing ones."""
    config.DATA_DROPS_PATH.mkdir(parents=True, exist_ok=True)
    cache_file = Path(config.DATA_DROPS_PATH / "unique-templates-wiki-page-text.json")

    cached = {}
    if cache_file.exists() and not refresh:
        with open(cache_file) as template_file:
            cached = json.load(template_file)

    templates = {}
    for name in sorted(names):
        page_title = f"Template:Uniques/{name}"
        text = cached.get(page_title)
        if text and text != "None":
            templates[name] = text
            continue
        logger.info("Fetching '%s' wiki page for a unique drop template...", page_title)
        page = WikiPageText(WIKI_API_URL, page_title)
        page.extract_page_wiki_text()
        if not page.wiki_text:
            raise SystemExit(f">>> ERROR: Could not fetch required unique template: {page_title}")
        page.export_wiki_text_to_json(str(cache_file))
        templates[name] = page.wiki_text
    return templates


def load_shared_table_wikitext(refresh: bool = False) -> Dict[str, Optional[str]]:
    """Load the wikitext of every shared drop table page, fetching any not cached.

    :param refresh: Re-fetch the pages even when a cached copy exists.
    :return: Page title to wikitext, None for a page that could not be fetched.
    """
    config.DATA_DROPS_PATH.mkdir(parents=True, exist_ok=True)
    cache_file = Path(config.DATA_DROPS_PATH / "drop-tables-wiki-page-text.json")

    cached = {}
    if cache_file.exists() and not refresh:
        with open(cache_file) as drop_table_file:
            cached = json.load(drop_table_file)

    pages = {}
    for title in drops_tables.SHARED_TABLE_PAGES:
        page_text = cached.get(title)
        if page_text and page_text != "None":
            pages[title] = page_text
            continue
        logger.info("Fetching '%s' wiki page for shared drop tables...", title)
        page = WikiPageText(WIKI_API_URL, title)
        page.extract_page_wiki_text()
        if not page.wiki_text:
            logger.warning(
                "Could not fetch '%s' — its shared tables will be empty.", title
            )
            pages[title] = None
            continue
        page.export_wiki_text_to_json(str(cache_file))
        pages[title] = page.wiki_text
    return pages


def generate(
    out_dir: Path,
    limit: Optional[int] = None,
    refresh_shared: bool = False,
    refresh_unique: bool = False,
) -> None:
    """Parse every monster wiki page and write the drops dump."""
    logger.info("Loading item database for drop item ID lookup...")
    item_db = items_api.load()
    items = ItemIdLookup(item_db, load_drop_version_items(item_db))
    npc_names = load_npc_cache_names()
    all_wikitext = load_monster_wikitext()
    unique_names = {
        name
        for page_wikitext in all_wikitext.values()
        for name in unique_template_titles(page_wikitext)
    }
    unique_templates = load_unique_template_wikitext(unique_names, refresh=refresh_unique)

    aggregator = NpcDropsAggregator(npc_names=npc_names)
    scanned_pages = 0
    skipped_pages = 0

    total_pages = len(all_wikitext) if limit is None else min(limit, len(all_wikitext))
    logger.info("Processing %d monster wiki pages...", total_pages)

    for page_title, page_wikitext in all_wikitext.items():
        if limit is not None and scanned_pages >= limit:
            break
        scanned_pages += 1
        if scanned_pages % 250 == 0:
            logger.info("Progress: %4d of %4d pages", scanned_pages, total_pages)

        if ALTERNATE_ENCOUNTER_MARKER in page_title.lower():
            skipped_pages += 1
            continue
        if not page_wikitext or page_wikitext == "None":
            skipped_pages += 1
            continue
        if has_non_numeric_npc_id(page_wikitext):
            skipped_pages += 1
            continue

        tables = parse_all_drop_tables(page_wikitext, unique_templates=unique_templates)
        if not tables:
            skipped_pages += 1
            continue

        wiki_page = page_title.replace(" ", "_")
        exported = 0
        for table in tables:
            spec = drops_tables.build_table_spec(wiki_page, table, items)
            if not spec.has_drop_content():
                continue
            aggregator.add(spec)
            exported += 1
        if not exported:
            skipped_pages += 1

    subtables = drops_tables.export_shared_subtables(
        load_shared_table_wikitext(refresh=refresh_shared), items
    )
    aggregator.write(out_dir, subtables, scanned_pages)

    logger.info(
        "Wrote drops dump to %s (%d npcs, %d tables, %d pages scanned, %d skipped)",
        out_dir,
        len(aggregator.npcs),
        len(aggregator.tables),
        scanned_pages,
        skipped_pages,
    )
    if aggregator.unresolved_items:
        logger.info(
            "%d drop names could not be matched to an item ID (see unresolved-items.json)",
            len(aggregator.unresolved_items),
        )


def main():
    parser = argparse.ArgumentParser(
        description="Generate the OSRS npc drops JSON dump."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=config.DOCS_DROPS_PATH,
        help="Directory to write the dump files to.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process this many wiki pages."
    )
    parser.add_argument(
        "--refresh-shared",
        action="store_true",
        help="Re-fetch the shared drop table wiki pages instead of using cached copies.",
    )
    parser.add_argument(
        "--refresh-unique",
        action="store_true",
        help="Re-fetch the unique drop templates instead of using cached copies.",
    )
    args = parser.parse_args()

    begin_run("scripts_drops_update")
    logger.info("Starting npc drops extraction...")
    generate(
        out_dir=args.out,
        limit=args.limit,
        refresh_shared=args.refresh_shared,
        refresh_unique=args.refresh_unique,
    )
    logger.info("Npc drops extraction completed!")


if __name__ == "__main__":
    main()
