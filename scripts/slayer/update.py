"""Build the Slayer-master task dump from the OSRS Wiki."""

import argparse
import json
import re

import mwparserfromhell as mw
import requests

import config

API = "https://oldschool.runescape.wiki/api.php"
MASTERS = [
    "Turael", "Spria", "Krystilia", "Mazchna", "Vannaka",
    "Chaeldar", "Konar quo Maten", "Nieve", "Duradel", "Mortimer",
]
CACHE = config.DATA_PATH / "slayer" / "slayer-master-pages.json"
OUTPUT = config.DOCS_PATH / "slayer-tasks.json"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_pages(titles):
    pages = {}
    session = requests.Session()
    for offset in range(0, len(titles), 50):
        batch = titles[offset : offset + 50]
        response = session.get(
            API,
            headers=config.custom_agent,
            params={
                "action": "query", "format": "json", "formatversion": 2,
                "prop": "revisions", "rvprop": "ids|content", "rvslots": "main",
                "redirects": 1, "titles": "|".join(batch),
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        aliases = {
            item["from"]: item["to"]
            for kind in ("normalized", "redirects")
            for item in result["query"].get(kind, [])
        }
        fetched = {}
        for page in result["query"]["pages"]:
            if "missing" in page:
                raise ValueError(f"Wiki page is missing: {page['title']}")
            revision = page["revisions"][0]
            fetched[page["title"]] = {
                "revision": revision["revid"],
                "wikitext": revision["slots"]["main"]["content"],
            }
        for title in batch:
            target = aliases.get(title, title)
            pages[title] = dict(fetched[target], **({"title": target} if target != title else {}))
    return pages


def task_section(wikitext):
    match = re.search(r"^==\s*Tasks\s*==\s*(.*?)(?=^==[^=]|\Z)", wikitext, re.M | re.S | re.I)
    return match.group(1) if match else wikitext


def page_cache(refresh):
    pages = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() and not refresh else {}
    missing = set(MASTERS) - pages.keys()
    if missing:
        pages.update(fetch_pages(sorted(missing)))
    assignment_pages = set()
    for master in MASTERS:
        assignment_pages.update(
            match.group(1).strip()
            for match in re.finditer(r"\{\{:\s*([^}|]+)", task_section(pages[master]["wikitext"]))
        )
    missing = assignment_pages - pages.keys()
    if missing:
        pages.update(fetch_pages(sorted(missing)))
    save(CACHE, pages)
    return pages


def infobox(wikitext):
    return next(
        (
            template
            for template in mw.parse(wikitext).filter_templates()
            if str(template.name).strip().casefold() == "infobox npc"
        ),
        None,
    )


def params(template):
    return {str(param.name).strip().casefold(): str(param.value).strip() for param in template.params}


def master_ids(page_title, wikitext):
    box = infobox(wikitext)
    if not box:
        raise ValueError(f"{page_title}: NPC infobox not found")
    values = params(box)
    ids = []
    for suffix in [""] + [str(i) for i in range(1, 20)]:
        options = values.get("options" + suffix, "")
        if suffix and "assignment" not in options.casefold():
            continue
        raw = values.get("id" + suffix)
        if raw:
            ids.extend(int(value) for value in re.findall(r"\d+", raw))
    if not ids:
        raise ValueError(f"{page_title}: no Slayer-master NPC IDs found")
    return str(values.get("name", page_title)), sorted(set(ids))


def table_text(wikitext):
    tables = re.findall(r"\{\|.*?\n\|\}", wikitext, re.S)
    for table in tables:
        if re.search(r"!.*Monster", table, re.I) and re.search(r"!.*Weight", table, re.I):
            return table
    raise ValueError("No Slayer task table found")


def cells(row, marker):
    result = []
    current = None
    for line in row.splitlines():
        line = line.strip()
        if line.startswith(marker):
            if current is not None:
                result.append(current.strip())
            value = line[1:]
            if marker in ("|", "!") and "|" in value and value.split("|", 1)[0].strip().startswith(
                ("class", "style", "rowspan", "colspan", "data-")
            ):
                value = value.split("|", 1)[1]
            current = value.strip()
        elif current is not None and line and not line.startswith("!"):
            current += "\n" + line
    if current is not None:
        result.append(current.strip())
    return result


def clean(value):
    value = re.sub(r"<ref(?: [^>]*)?>.*?</ref>|<ref[^>]*/>", "", value, flags=re.I | re.S)
    value = value.replace("{{!}}", "|")
    return str(mw.parse(value).strip_code()).strip()


def links(value):
    return [clean(str(link.text or link.title)) for link in mw.parse(value).filter_wikilinks()]


def first_link(value):
    values = links(value)
    return values[0] if values else clean(value).split("\n", 1)[0].strip("* ")


def number_range(value):
    match = re.search(r"(\d+)\s*[–-]\s*(\d+)", clean(value))
    return [int(match.group(1)), int(match.group(2))] if match else None


def levels(row):
    slayer = [int(value) for value in re.findall(r"\{\{SCP\|Slayer\|(\d+)", row, re.I)]
    combat = [int(value) for value in re.findall(r"\{\{SCP\|Combat\|(\d+)", row, re.I)]
    return min(slayer) if slayer else 0, min(combat) if combat else 0


def singular(name):
    value = name.casefold().strip()
    if value.endswith("ies"):
        return value[:-3] + "y"
    if value.endswith("ves") and not value.endswith("devils"):
        return value[:-3] + "f"
    if value.endswith("men"):
        return value[:-3] + "man"
    if value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value


def monster_names():
    source = json.loads((config.DOCS_PATH / "monsters-complete.json").read_text(encoding="utf-8"))
    names = sorted({entry["name"] for entry in source.values() if entry.get("name")})
    return (
        {name.casefold(): name.casefold() for name in names},
        {singular(name): name.casefold() for name in names},
    )


def resolve_names(task_name, alternative_cells, exact, singulars):
    resolved = []
    candidates = [task_name]
    for cell in alternative_cells:
        candidates.extend(links(cell))
    for candidate in candidates:
        match = exact.get(candidate.casefold()) or singulars.get(singular(candidate))
        if match and match not in resolved:
            resolved.append(match)
    return resolved or [singular(task_name)]


def parse_tasks(wikitext, exact, singulars):
    table = table_text(wikitext)
    table_parts = re.split(r"(?m)^\|-.*$", table)
    header_part = table_parts[0]
    first_row = 1
    if not re.search(r"!.*Monster", header_part, re.I):
        header_part = table_parts[1]
        first_row = 2
    headers = [clean(value).casefold() for value in cells(header_part, "!")]
    index = {header: position for position, header in enumerate(headers)}
    tasks = []
    for row in table_parts[first_row:]:
        values = cells(row, "|")
        if not values or len(values) < len(headers) - 1:
            continue
        values = values[: len(headers)]
        value = lambda *names: next(
            (values[index[name]] for name in names if name in index and index[name] < len(values)), ""
        )
        name = first_link(value("monster"))
        quantity = number_range(value("amount"))
        if not name or not quantity:
            continue
        slayer_level, combat_level = levels(row)
        weight_match = re.search(r"weight\|\s*(\d+)", row, re.I)
        if not weight_match:
            continue
        task = {
            "slug": re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-"),
            "name": name,
            "quantity": quantity,
            "extended_quantity": number_range(value("extended amt.", "extended amount")),
            "slayer_level": slayer_level,
            "combat_level": combat_level,
            "weight": int(weight_match.group(1)),
            "npc_names": resolve_names(
                name, [value("alternative(s)", "alternative")], exact, singulars
            ),
        }
        location = value("possible locations", "location")
        if location:
            task["locations"] = links(location) or [clean(location)]
        tasks.append(task)
    if not tasks:
        raise ValueError("No Slayer tasks parsed")
    return tasks


def build(pages):
    exact, singulars = monster_names()
    dump = {}
    for master in MASTERS:
        name, ids = master_ids(master, pages[master]["wikitext"])
        section = task_section(pages[master]["wikitext"])
        target = next(
            (
                match.group(1).strip()
                for match in re.finditer(r"\{\{:\s*([^}|]+)", section)
                if match.group(1).strip() in pages
            ),
            None,
        )
        source = pages[target]["wikitext"] if target else section
        tasks = parse_tasks(source, exact, singulars)
        for npc_id in ids:
            dump[str(npc_id)] = {"name": name, "dialogue": name, "tasks": tasks}
    return dict(sorted(dump.items(), key=lambda item: int(item[0])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use the saved wiki page cache.")
    parser.add_argument("--refresh", action="store_true", help="Refresh the wiki page cache.")
    args = parser.parse_args()
    if args.offline and args.refresh:
        parser.error("--offline cannot be combined with --refresh")
    pages = page_cache(args.refresh) if not args.offline else json.loads(CACHE.read_text(encoding="utf-8"))
    save(OUTPUT, build(pages))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
