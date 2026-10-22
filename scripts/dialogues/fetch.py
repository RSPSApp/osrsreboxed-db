"""Cache NPC and quest transcripts, their references, and NPC identity pages."""

import json
import time

import mwparserfromhell as mw

import config
from scripts.wiki.wiki_page_text import WikiPageText
from scripts.wiki.wiki_page_titles import WikiPageTitles

API = "https://oldschool.runescape.wiki/api.php"
DIALOGUE_CATEGORIES = (
    "NPC dialogue",
    "Quest transcript",
    "Miniquest transcript",
)
TRANSCRIPT_CATEGORIES = ("Quest transcript", "Miniquest transcript")
CACHE = config.DATA_PATH / "dialogues" / "wiki-pages.json"
QUEST_CACHE = CACHE.with_name("quest-pages.json")
NPC_CACHE = CACHE.with_name("npc-pages.json")
TEMPLATE_CACHE = CACHE.with_name("template-pages.json")


def save(path, data, *, minified=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    text = json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        **({"separators": (",", ":")} if minified else {"indent": 2}),
    )
    temporary.write_text(text if minified else text + "\n", encoding="utf-8")
    temporary.replace(path)


def read_cache(path):
    return json.loads(path.read_text()) if path.exists() else {}


def trailing_template_name(raw, name):
    """Return a standalone, non-bulleted final template named after the page."""
    lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
    if not lines or lines[-1].startswith("*"):
        return None
    line = lines[-1]
    code = mw.parse(line)
    templates = code.filter_templates(recursive=False)
    if (
        len(templates) != 1
        or str(templates[0]).strip() != line
        or templates[0].params
        or str(templates[0].name).strip().casefold() != name.casefold()
    ):
        return None
    return str(templates[0].name).strip()


def navigation_template(page):
    """Classify a template as navigation from its fetched source or categories."""
    categories = {str(value).casefold() for value in page.get("categories", [])}
    if any("navbox" in category for category in categories):
        return True
    templates = mw.parse(str(page.get("wikitext", ""))).filter_templates(
        recursive=False
    )
    return bool(
        templates
        and str(templates[0].name).strip().casefold().startswith("navbox")
    )


def load_navigation_templates():
    if not TEMPLATE_CACHE.exists():
        raise FileNotFoundError(f"Missing dialogue template cache: {TEMPLATE_CACHE}")
    return {
        title.removeprefix("Template:")
        for title, page in read_cache(TEMPLATE_CACHE).items()
        if navigation_template(page)
    }


def transcript_targets(raw):
    return {
        str(link.title).split("#", 1)[0].strip().replace("_", " ")
        for link in mw.parse(raw).filter_wikilinks()
        if str(link.title).strip().startswith("Transcript:")
    }


def participant_pages(raw):
    pages = set()
    for template in mw.parse(raw).filter_templates():
        if str(template.name).strip().casefold() != "transcript list":
            continue
        for param in template.params:
            if not str(param.name).strip().isdigit():
                continue
            value = str(param.value).strip()
            links = mw.parse(value).filter_wikilinks()
            page = (
                str(links[0].title)
                if links
                else value.replace("{{!}}", "|").split("|", 1)[0]
            )
            if page.casefold() not in ("player", "noplayer", ""):
                pages.add(page.strip())
    return sorted(pages)


def download(names, path, session, refresh=False, with_categories=False):
    pages = read_cache(path)
    missing = sorted(set(names) if refresh else set(names) - pages.keys())
    for offset in range(0, len(missing), 50):
        batch = missing[offset : offset + 50]
        response = session.get(
            API,
            headers=config.custom_agent,
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "prop": "revisions|categories" if with_categories else "revisions",
                "rvprop": "ids|content",
                "rvslots": "main",
                "redirects": 1,
                "titles": "|".join(batch),
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            raise ValueError(result["error"])
        query = result["query"]
        fetched = {}
        for page in query["pages"]:
            if "missing" in page or "invalid" in page:
                fetched[page["title"]] = {"missing": True}
                continue
            revision = page["revisions"][0]
            fetched[page["title"]] = {
                "revision": revision["revid"],
                "wikitext": revision["slots"]["main"]["content"],
            }
            if with_categories:
                fetched[page["title"]]["categories"] = [
                    category["title"] for category in page.get("categories", [])
                ]
        aliases = {
            item["from"]: item["to"]
            for kind in ("normalized", "redirects")
            for item in query.get(kind, [])
        }
        for title in batch:
            target, seen = title, set()
            while target in aliases and target not in seen:
                seen.add(target)
                target = aliases[target]
            if target not in fetched:
                raise ValueError(f"Incomplete batch: {title}")
            pages[title] = dict(
                fetched[target], **({"title": target} if target != title else {})
            )
        save(path, pages)
        print(
            f"{path.name}: downloaded {min(offset + 50, len(missing))}/{len(missing)}",
            flush=True,
        )
        time.sleep(0.3)
    return pages


def fetch(refresh=False):
    categories = {}
    for category in DIALOGUE_CATEGORIES:
        titles = WikiPageTitles(API, [category])
        titles.extract_page_titles()
        categories[category] = {
            title for title in titles if title.startswith("Transcript:")
        }
        if not categories[category]:
            raise ValueError(f"{category} returned no transcripts")
    session = WikiPageText(API, "").session
    npc_names = categories["NPC dialogue"]
    transcript_names = set().union(
        *(categories[category] for category in TRANSCRIPT_CATEGORIES)
    )
    pages = download(npc_names, CACHE, session, refresh)
    quests = download(transcript_names - npc_names, QUEST_CACHE, session, refresh)
    if refresh:
        quests = download(set(quests) - transcript_names, QUEST_CACHE, session, True)
    # Follow explicit dependencies to a fixed point. Cache missing pages too, so a
    # broken wiki link is reported once rather than retried forever.
    while True:
        targets = set().union(
            *(
                transcript_targets(p.get("wikitext", ""))
                for p in [*pages.values(), *quests.values()]
            )
        )
        missing = targets - pages.keys() - quests.keys()
        if not missing:
            break
        quests = download(missing, QUEST_CACHE, session)
    footer_templates = set()
    for title, page in [*pages.items(), *quests.items()]:
        template = trailing_template_name(
            page.get("wikitext", ""), title.removeprefix("Transcript:")
        )
        if template:
            footer_templates.add("Template:" + template)
    download(
        footer_templates,
        TEMPLATE_CACHE,
        session,
        refresh,
        with_categories=True,
    )
    identity_names = {title.removeprefix("Transcript:") for title in npc_names}
    for page in quests.values():
        identity_names.update(participant_pages(page.get("wikitext", "")))
    download(identity_names, NPC_CACHE, session, refresh)
    save(CACHE, {name: pages[name] for name in sorted(npc_names)})
    return {name: pages[name] for name in sorted(npc_names)}


if __name__ == "__main__":
    fetch()
