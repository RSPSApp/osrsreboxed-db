"""Export NPC and quest conversations with stable plugin hook points.

Run with --offline to rebuild from data/dialogues/wiki-pages.json without fetching.
"""

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

import mwparserfromhell as mw

import config
from scripts.dialogues.fetch import (
    CACHE,
    QUEST_CACHE,
    NPC_CACHE,
    TEMPLATE_CACHE,
    fetch,
    load_navigation_templates,
    participant_pages,
    read_cache,
    save,
    trailing_template_name,
)
from scripts.dialogues.hooks import enrich_records, walk as dialogue_nodes
from scripts.dialogues.compact import compact_record, write_split
from scripts.dialogues.corrections import apply_corrections
from scripts.dialogues.bindings import apply_bindings


def clean(raw):
    """Remove presentation markup; retain unfamiliar templates verbatim."""
    code = mw.parse(str(raw))
    for template in code.filter_templates(recursive=False):
        name = str(template.name).strip().lower()
        if name in ("colour", "color") and template.has(2):
            code.replace(template, clean(template.get(2).value))
        elif name == "overhead" and template.has(1):
            code.replace(template, clean(template.get(1).value))
        elif name in ("sic", "^"):
            code.replace(template, "")
    # Keep unrecognised templates through strip_code rather than dropping data.
    saved = []
    for template in code.filter_templates(recursive=False):
        saved.append(str(template))
        code.replace(template, f"\ue000{len(saved)-1}\ue001")
    text = code.strip_code().strip()
    for i, template in enumerate(saved):
        text = text.replace(f"\ue000{i}\ue001", template)
    return text


# Gameplay slugs inferred from wiki prose rather than template parameters. This is
# a guess: every step matched here is marked action_source="text" so a consumer can
# choose to trust only the template-derived slugs. First pattern wins; a named group
# "t" supplies the target. Prose targets are wiki display strings, not interface ids.
CONDITION_PROSE = re.compile(r"^\(?If\s+(?:the\s+player|you|they)\b", re.I)

PROSE_ACTIONS = [
    (
        "open_interface",
        re.compile(
            r"^\(?(?:the\s+|game\s+opens\s+the\s+)?(?P<t>.+?)\s+"
            r"(?:interface|menu|screen)\s+opens\b",
            re.I,
        ),
    ),
    (
        "open_interface",
        re.compile(r"^\(?(?:game\s+)?opens\s+(?:the\s+)?(?P<t>.+?)[.)]*$", re.I),
    ),
    ("open_interface", re.compile(r"^\(?(?P<t>[A-Z][^.)]*?)\s+opens\b")),
    (
        "receive",
        re.compile(r"\b(?:player|you)\s+(?:receives?|is\s+given|are\s+given)\b", re.I),
    ),
    (
        "teleport",
        re.compile(
            r"\btelep(?:orts?|orted)\s+the\s+player\b"
            r"|\btransports?\s+the\s+player\b"
            r"|\bplayer\b[^.]{0,40}?\b(?:is|are|gets?)\s+"
            r"(?:teleported|transported|brought|taken|moved)\b",
            re.I,
        ),
    ),
    (
        "heal",
        re.compile(
            r"\bheals?\b[^.]{0,30}\b(?:player|you)\b|\bplayer\s+is\s+healed\b", re.I
        ),
    ),
    (
        "emote",
        re.compile(
            r"\bperforms?\s+the\b.*\bemote\b"
            r"|\b(?:bows|dances|cheers|waves|claps|shrugs|nods|laughs)\b",
            re.I,
        ),
    ),
]


TARGET_NOUN = re.compile(r"\s+(?:interface|menu|screen|panel)$", re.I)
TARGET_NOISE = {"interface", "menu", "screen", "panel", "tab", "game", "shop"}


def infer_action(text):
    """Guess a gameplay slug from an action's prose; empty when nothing matches."""
    if not text:
        return {}
    if CONDITION_PROSE.match(text):
        return dict(type="condition", action_source="text")
    for slug, pattern in PROSE_ACTIONS:
        match = pattern.search(text)
        if not match:
            continue
        inferred = dict(action=slug, action_source="text")
        target = TARGET_NOUN.sub("", match.groupdict().get("t") or "")
        target = target.strip(" .)\"'")
        # A bare noun ("Interface", "Game") names nothing; keep the prose instead.
        if target and target.lower() not in TARGET_NOISE:
            inferred["target"] = target
        return inferred
    return {}


def speaker_label(raw):
    label = clean(raw).strip()
    if label.endswith(":"):
        return label[:-1].strip()
    if len(label) >= 3 and label[-1] in "'\"" and label[-2] == ":":
        return (label[:-2] + label[-1]).strip()
    return None


def parse_step(raw, issues, line):
    code = mw.parse(str(raw))
    anchors = []
    for template in code.filter_templates(recursive=False):
        if str(template.name).strip().casefold() != "anchor":
            continue
        if template.has(1):
            anchor = clean(template.get(1).value).strip()
            if anchor:
                anchors.append(anchor)
        code.replace(template, "")
    if anchors:
        node = parse_step(str(code).strip(), issues, line)
        node["_anchors"] = anchors
        return node
    speech = re.fullmatch(r"'''(.*?)'''\s*(.*)", raw, re.S)
    speaker = speaker_label(speech[1]) if speech else None
    if speaker is not None:
        text = clean(speech[2])
        node = dict(type="line", speaker=speaker, text=text)
        if "{{overhead" in raw.lower():
            node["display"] = "overhead"
        if "{{" in text:
            issues.append(
                dict(line=line, reason="Unrecognised inline template", raw=raw)
            )
        return node
    templates = mw.parse(raw).filter_templates(recursive=False)
    if templates and str(templates[0].name).strip().lower() == "topt":
        option = str(templates[0])
        annotation = raw.removeprefix(option).strip()
        if annotation:
            condition = clean(annotation).strip("() ")
            after = re.fullmatch(r"only after (.+)", condition, re.I)
            if after:
                node = parse_step(option, issues, line)
                node["condition"] = f"If the player has completed {after[1]}:"
                return node
    cleaned = clean(raw)
    cleaned_templates = mw.parse(cleaned).filter_templates(recursive=False)
    if len(cleaned_templates) == 1 and str(cleaned_templates[0]) == cleaned:
        t = cleaned_templates[0]
        name = str(t.name).strip().lower()
        # Resolve links before clean() discards their page/section identity.
        if name in ("tact", "qact"):
            links = [
                link
                for link in mw.parse(str(t)).filter_wikilinks()
                if str(link.title).strip().startswith(("Transcript:", "#"))
            ]
            if len(links) == 1:
                page, _, section = (
                    str(links[0].title).strip().replace("_", " ").partition("#")
                )
                return dict(
                    type="reference",
                    target=page,
                    section=section,
                    text=clean(t.get(1).value) if t.has(1) else "",
                )
        args = {str(p.name).strip(): clean(p.value) for p in t.params}
        text = args.get("1", "")
        if name == "topt":
            node = dict(type="option", text=text)
            if text == "cond" and args.get("2") and args.get("3"):
                node.update(text=args["3"], condition=args["2"])
                issues.append(
                    dict(
                        line=line,
                        reason="Recovered positional option condition",
                        raw=raw,
                    )
                )
            if "cond" in args:
                node["condition"] = args["cond"]
            if args.get("quest", "").casefold() == "no":
                node["_shared"] = True
            return node
        if name in ("tcond", "tselect", "tbox", "mes", "qact", "tinput"):
            node = dict(
                type={
                    "tcond": "condition",
                    "tselect": "menu",
                    "tbox": "message",
                    "mes": "message",
                    "qact": "action",
                    "tinput": "input",
                }[name],
                text=text,
            )
            if "pic" in args:
                node["image"] = args["pic"]
            if node["type"] == "action":
                node.update(infer_action(text))
            return node
        if name == "trandom":
            return dict(type="random_marker")
        if name in ("tmissing", "transcript missing"):
            issues.append(dict(line=line, reason="Transcript missing"))
            return dict(type="missing")
        if name == "tact":
            if text == "end":
                return dict(type="end")
            # A free-to-play branch stops here; the conversation is members-only.
            if text == "members":
                return dict(type="end", reason="members")
            if re.fullmatch(r"above|below|previous\d*|initial|other|continues?", text):
                anchor = args.get("2", "").strip()
                if anchor and text in ("above", "below"):
                    return dict(
                        type="jump",
                        target=None,
                        reference=text,
                        _anchor=anchor,
                    )
                issues.append(
                    dict(line=line, reason="Unresolved dialogue reference", raw=raw)
                )
                return dict(type="jump", target=None, reference=text)
            # opens2 is the unlinked spelling of opens; the two never co-occur.
            if "opens" in args or "opens2" in args:
                return dict(
                    type="action",
                    action="open_interface",
                    target=args.get("opens") or args.get("opens2"),
                )
            if "receives" in args:
                return dict(type="action", action="receive", text=args["receives"])
            if "gives" in args:
                return dict(type="action", action="give", text=args["gives"])
            node = dict(type="action", text=text, parameters=args)
            node.update(infer_action(text))
            return node
    issues.append(dict(line=line, reason="Unrecognised markup retained", raw=raw))
    if re.match(r"Before starting this quest,?\s", raw, re.I):
        issues.pop()
        return dict(type="message", text=clean(raw), _identity={"type": "unavailable"})
    return dict(type="unparsed", raw=raw)


def group_options(nodes, random_options=False):
    """Group menu alternatives.

    The wiki writes a menu's options either as following siblings (`{{tselect}}`
    then `{{topt}}` at the same bullet depth) or nested as children (`{{tselect}}`
    then deeper `{{topt}}` bullets). Both must become the menu's options; the
    nested style used to emit an empty menu and drop every choice.
    """
    result = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if node["type"] in ("menu", "random_marker", "option"):
            kind = (
                "random"
                if random_options or node["type"] == "random_marker"
                else "choice"
            )
            group = dict(type=kind, options=[])
            option_nodes = []
            if node["type"] == "option":
                option_nodes.append(node)
                i += 1
            else:
                if node.get("text"):
                    group["prompt"] = node["text"]
                # Deeper-bullet options parsed as children of the tselect.
                for child in node.get("steps", []):
                    if child["type"] == "option":
                        option_nodes.append(child)
                    elif option_nodes:
                        # Some transcripts put an option's body at its own depth.
                        option_nodes[-1].setdefault("steps", []).append(child)
                i += 1
            if not option_nodes or node["type"] == "option":
                while i < len(nodes):
                    sibling = nodes[i]
                    if sibling["type"] == "option":
                        option_nodes.append(sibling)
                        i += 1
                        continue
                    if not option_nodes:
                        break
                    next_option = next(
                        (
                            index
                            for index in range(i + 1, len(nodes))
                            if nodes[index]["type"] == "option"
                            or nodes[index]["type"] in ("menu", "random_marker")
                        ),
                        len(nodes),
                    )
                    between = nodes[i:next_option]
                    if (
                        next_option < len(nodes)
                        and nodes[next_option]["type"] == "option"
                        and between
                        and all(step["type"] in ("action", "end") for step in between)
                    ):
                        # Some source pages put an option's action/end body at
                        # the same bullet depth, before the next alternative.
                        option_nodes[-1].setdefault("steps", []).extend(between)
                        i = next_option
                        continue
                    option_text = str(option_nodes[-1].get("text", "")).rstrip(".!?")
                    if (
                        sibling.get("type") == "line"
                        and sibling.get("speaker", "").casefold() == "player"
                        and sibling.get("text", "").rstrip(".!?").casefold() == option_text.casefold()
                    ):
                        # A same-depth player echo is the option's response;
                        # keep the continuation only until the next alternative.
                        # Do not absorb another parent-level choice into this branch.
                        next_control = next(
                            (
                                index
                                for index in range(i + 1, len(nodes))
                                if nodes[index]["type"]
                                in ("option", "menu", "random_marker", "condition")
                            ),
                            len(nodes),
                        )
                        option_nodes[-1].setdefault("steps", []).extend(
                            nodes[i:next_control]
                        )
                        i = next_control
                        if i < len(nodes) and nodes[i]["type"] == "option":
                            continue
                    break
            for option in option_nodes:
                group["options"].append(
                    {k: v for k, v in option.items() if k != "type"}
                )
                option_body = group["options"][-1]
                option_body["steps"] = group_options(option.get("steps", []))
            result.append(group)
        else:
            if "steps" in node:
                node["steps"] = group_options(node["steps"])
            result.append(node)
            i += 1
    return result


def select_default(variants):
    """Choose a baseline conversation by headings, never by NPC name."""
    ordinary = {
        "standard dialogue",
        "normal dialogue",
        "dialogue",
        "talking",
        "talking to",
    }
    repeats = {"subsequent dialogue", "repeat dialogue", "subsequent conversation"}
    initial = {
        "initial dialogue",
        "initial conversation",
        "first conversation",
        "starting off",
        "starting out",
    }
    candidates = []
    for key, variant in variants.items():
        steps = variant["steps"]
        if not steps or steps[0]["type"] not in (
            "line",
            "choice",
            "random",
            "condition",
            "reference",
        ):
            continue
        *parents, label = [part.strip().casefold() for part in variant["section_path"]]
        if any(parent not in ordinary | initial for parent in parents):
            continue
        if label in ordinary:
            rank = 0
        elif label in repeats:
            rank = 1
        elif label in initial:
            rank = 2
        elif (
            parents
            and parents[0] in initial
            and re.match(r"(?:talking|speaking) to\b", label)
            and "again" not in label
        ):
            rank = 2
        elif label == "unsectioned":
            rank = 3
        elif label in ("pre-quest", "pre quest", "before quest") or re.match(
            r"(?:(?:standard|normal) dialogue\s+)?before\b", label
        ):
            rank = 4
        elif re.match(
            r"(?:without\b|if (?:the player )?(?:isn't|is not) (?:carrying|wearing)\b)",
            label,
        ):
            rank = 5
        else:
            continue
        candidates.append((rank, key))
    # ponytail: heading heuristic, ties use wiki order; explicit gameplay conditions need structured data.
    return (
        min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None
    )


COMPLETION_ACTION = "Congratulations! Quest complete!"


def normalize_terminal_completion(steps):
    for node in steps:
        if node.get("steps"):
            normalize_terminal_completion(node["steps"])
        for option in node.get("options", []):
            normalize_terminal_completion([option])
    if (
        len(steps) >= 2
        and steps[-2] == {"type": "end"}
        and steps[-1].get("type") == "action"
        and steps[-1].get("text") == COMPLETION_ACTION
    ):
        steps[-2], steps[-1] = steps[-1], steps[-2]
    return steps


def apply_structure_annotations(name, raw, structure=None, revision=None):
    """Apply reviewed bullet-depth fixes to cached wiki text.

    Each fix names an exact source line and its hash, so a refreshed revision
    stops the dump for review instead of silently moving content. Only the
    bullet prefix changes; dialogue, templates, order and line endings stay in
    the source.
    """
    if not structure:
        return raw
    if revision is not None and structure.get("revision") != revision:
        raise ValueError(f"Stale dialogue structure annotation: {name}")
    lines = raw.splitlines(keepends=True)
    for fix in structure.get("lines", []):
        number = fix["line"]
        if not isinstance(number, int) or not 0 < number <= len(lines):
            raise ValueError(
                f"Stale dialogue structure annotation: {name} line {number}"
            )
        line = lines[number - 1]
        body, ending = line, ""
        for terminator in ("\r\n", "\r", "\n"):
            if line.endswith(terminator):
                body, ending = line[: -len(terminator)], terminator
                break
        if hashlib.sha256(body.encode()).hexdigest() != fix["sha256"]:
            raise ValueError(
                f"Stale dialogue structure annotation: {name} line {number}"
            )
        bullet = re.match(r"\*+", body)
        if not bullet:
            raise ValueError(
                f"Unbulleted dialogue structure annotation: {name} line {number}"
            )
        depth = fix["depth"]
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
            raise ValueError(
                f"Invalid dialogue structure annotation depth: {name} line {number}"
            )
        lines[number - 1] = "*" * depth + body[bullet.end() :] + ending
    return "".join(lines)


def parse_npc(name, raw, nav_templates=None):
    if nav_templates is None:
        nav_templates = load_navigation_templates()
    nav_template_names = {template.casefold() for template in nav_templates}
    variants, issues, headings = {}, [], []
    participants = participant_pages(raw)
    stack = []
    current = None
    raw = re.sub(
        r"<!--.*?-->", lambda match: "\n" * match[0].count("\n"), raw, flags=re.S
    )
    poem = None
    source_lines = raw.splitlines()
    last_content_line = max(
        (number for number, text in enumerate(source_lines, 1) if text.strip()),
        default=0,
    )
    for number, original in enumerate(source_lines, 1):
        node_override = None
        line = original.strip()
        if not line:
            continue
        if line.casefold() == "<poem>":
            poem = []
            poem_depth = stack[-1][0] if stack else 1
            continue
        if poem is not None:
            if line.casefold() != "</poem>":
                poem.append(clean(line))
                continue
            node_override = dict(type="message", text="\n".join(poem))
            line = "*" * poem_depth + " {{tbox}}"
            poem = None
        heading = re.fullmatch(r"(={2,6})\s*(.*?)\s*\1", line)
        if heading:
            level = len(heading[1])
            headings = [(n, h) for n, h in headings if n < level]
            headings.append((level, clean(heading[2])))
            current = None
            stack = []
            continue
        if line.lower().startswith(
            ("{{transcript|", "{{transcript list|", "{{external|")
        ):
            continue
        if (
            line.lower().startswith("{{incomplete")
            and mw.parse(line).filter_templates()
        ):
            t = mw.parse(line).filter_templates()[0]
            issues.append(
                dict(
                    line=number,
                    reason="Incomplete source",
                    text=clean(t.get(1).value) if t.has(1) else "",
                )
            )
            continue
        if current is None:
            path = [h for _, h in headings] or ["Unsectioned"]
            key = re.sub(r"[^a-z0-9]+", "-", "/".join(path).lower()).strip("-")
            base = key
            suffix = 2
            while key in variants:
                key = f"{base}-{suffix}"
                suffix += 1
            current = dict(label=path[-1], section_path=path, steps=[])
            variants[key] = current
        if (
            not line.startswith(("*", "{{", "'''"))
            and "the topic just asked about is left out" in line.casefold()
        ):
            current["_omit_selected"] = True
            continue
        bullet = re.fullmatch(r"(\*+)\s*(.*)", line)
        depth, body = (len(bullet[1]), bullet[2]) if bullet else (1, line)
        footer = trailing_template_name(original, name)
        if (
            number == last_content_line
            and footer
            and footer.casefold() in nav_template_names
        ):
            continue
        node = node_override or parse_step(body, issues, number)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1].setdefault("steps", []).append(node)
        else:
            current["steps"].append(node)
        stack.append((depth, node))
    if poem is not None:
        raise ValueError(f"Unclosed poem in {name}")
    for variant in variants.values():
        is_oracle = name == "Oracle" and variant["section_path"] == [
            "Standard dialogue"
        ]
        variant["steps"] = group_options(variant["steps"], random_options=is_oracle)
        normalize_terminal_completion(variant["steps"])
        if is_oracle:
            variant["notes"] = [
                "Curated: numbered alternatives are random dialogue, not player choices; probabilities unknown."
            ]
    return dict(
        default=select_default(variants),
        variants=variants,
        review_issues=issues,
        participants=participants,
    )


def gameplay_step(node, name):
    """Drop editorial/source data while retaining dialogue flow and gameplay requirements."""
    if node.get("type") == "line" and node.get("speaker") in (name, "Player"):
        result = {"npc" if node["speaker"] == name else "player": node["text"]}
    elif node.get("type") == "unparsed":
        result = {"type": "unavailable"}
    else:
        result = {
            key: value
            for key, value in node.items()
            if key
            in (
                "type",
                "speaker",
                "text",
                "condition",
                "action",
                "target",
                "reference",
                "section",
                "reason",
                "action_source",
                "prompt",
                "_shared",
                "_identity",
                "_anchors",
                "_anchor",
            )
            and value is not None
        }
    if node.get("display") == "overhead":
        result["presentation"] = "overhead"
    if node.get("steps"):
        result["steps"] = [gameplay_step(child, name) for child in node["steps"]]
    if "options" in node:
        result["options"] = [gameplay_step(option, name) for option in node["options"]]
    if result.get("prompt", "").lower() in ("select an option", "select an option."):
        result.pop("prompt")
    return result


def gameplay_npc(name, parsed):
    default = parsed["default"]
    variants = {
        key: [gameplay_step(step, name) for step in variant["steps"]]
        for key, variant in parsed["variants"].items()
    }
    return {
        "default": default,
        "variants": variants,
        "sections": {
            key: value["section_path"] for key, value in parsed["variants"].items()
        },
        "participants": parsed.get("participants", []),
        "_omit_selected": [
            key
            for key, variant in parsed["variants"].items()
            if variant.get("_omit_selected")
        ],
    }


SHOPS = "shops-items-by-shop.json"
# A wiki link and a shop page title disagree on decoration, not on identity.
SHOP_DECORATION = re.compile(r"\[\[|\]\]|\s*\(shop\)\s*$", re.I)


def normalise_shop(name):
    """Fold a target and a shop page title onto one key, or "" when there is none."""
    name = re.sub(r"\{\{!\}\}.*$", "", name)  # pipe-trick display half
    name = SHOP_DECORATION.sub("", name).strip().strip(".").casefold()
    return re.sub(r"\s+", " ", re.sub(r"^the\s+", "", name))


def shop_keys(name):
    """Spellings a dialogue may use for one shop, loosest last; "" is never a key."""
    key = normalise_shop(name)
    # Tried strictest first, so a target spelled exactly like a shop still resolves
    # when a near-identical sibling would make the looser keys ambiguous. The wiki
    # and the shop title disagree on hyphens and spacing (Black Market Goods vs
    # Black-market Goods); dropping punctuation entirely settles that.
    spellings = (name, key, re.sub(r"[^a-z0-9]", "", key))
    return [k for k in dict.fromkeys(spellings) if k]


def shop_index():
    """Every shop spelling to its canonical key. Empty when the shops dump is unbuilt."""
    path = config.DOCS_PATH / SHOPS
    if not path.exists():
        print(f"{path} not built; every interface stays open_interface", flush=True)
        return {}
    names = collections.defaultdict(set)
    for shop in json.loads(path.read_text()):
        for key in shop_keys(shop):
            names[key].add(shop)
    # Two shops folding onto one key (quest-state variants) cannot be told apart.
    return {key: value.pop() for key, value in names.items() if len(value) == 1}


def resolve_shops(npcs, index):
    """Retag interfaces naming a known shop so consumers can join on the shops dump."""
    resolved = 0

    def walk(node):
        nonlocal resolved
        if isinstance(node, dict):
            target = (
                node.get("target") if node.get("action") == "open_interface" else None
            )
            shop = next(
                (index[key] for key in shop_keys(target or "") if key in index), None
            )
            if shop:
                node["action"] = "open_shop"
                node["target"] = shop
                resolved += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(npcs)
    from scripts.dialogues.hooks import walk as nodes

    for record in npcs.values():
        variants = (
            [record]
            if isinstance(record, list)
            else [
                *record.get("variants", {}).values(),
                *record.get("branches", {}).values(),
                record.get("steps", []),
            ]
        )
        steps = [node for variant in variants for node in nodes(variant)]
        shops = {node["target"] for node in steps if node.get("action") == "open_shop"}
        if len(shops) == 1:
            for node in steps:
                if (
                    node.get("action") == "open_interface"
                    and not node.get("target")
                    and re.fullmatch(
                        r"\(?Shop interface opens\.?\)?", node.get("text", ""), re.I
                    )
                ):
                    node.update(action="open_shop", target=next(iter(shops)))
                    resolved += 1
    return resolved


# A master's assignment line is a fixed game message, not a wiki template, so it
# survives as prose. Consumers cannot act on "[number] [monster]", so retag it as a
# slug the Slayer plugin starts a task from.
SLAYER_TASKS = "slayer-tasks.json"
SLAYER_ASSIGNMENT = re.compile(
    r"Your new task is to kill \[(?:amount|number)\] \[(?:task monster|monster)\]",
    re.I,
)
# The tip itself is dynamic; the transcript only notes that the master gives one.
SLAYER_TIP = re.compile(r"provides the corresponding Slayer task tip", re.I)


def slayer_masters():
    """Transcript names that assign tasks, taken from the Slayer tasks dump."""
    path = config.DOCS_PATH / SLAYER_TASKS
    if not path.exists():
        print(f"{path} not built; no Slayer lines are slugged", flush=True)
        return set()
    return {
        master["dialogue"]
        for master in json.loads(path.read_text()).values()
        if master.get("dialogue")
    }


def resolve_slayer(npcs, masters):
    """Retag a Slayer master's assignment line and task tip so consumers can act.

    The master name is written to ``target`` so a consumer joins on the Slayer
    tasks dump instead of inferring the master from the runtime NPC.
    """
    resolved = 0

    def walk(node, master):
        nonlocal resolved
        if isinstance(node, dict):
            text = node.get("npc")
            if isinstance(text, str) and SLAYER_ASSIGNMENT.search(text):
                node.pop("npc")
                node["type"] = "action"
                node["action"] = "slayer_assignment"
                node["target"] = master
                node["text"] = text
                node["action_source"] = "text"
                resolved += 1
            elif (
                node.get("type") == "action"
                and isinstance(node.get("text"), str)
                and SLAYER_TIP.search(node["text"])
            ):
                node["action"] = "slayer_task_tip"
                node["target"] = master
                node["action_source"] = "text"
                resolved += 1
            for value in node.values():
                walk(value, master)
        elif isinstance(node, list):
            for item in node:
                walk(item, master)

    for master in masters:
        record = npcs.get(master)
        if record:
            walk(record, master)
    return resolved


def action_report(npcs):
    """Every prose-inferred action plus the prose left unslugged, for human review."""
    inferred, unmatched = (
        collections.defaultdict(collections.Counter),
        collections.Counter(),
    )
    owners = collections.defaultdict(set)

    def walk(name, node):
        if isinstance(node, dict):
            if node.get("action_source") == "text":
                slug = node.get("action") or node["type"]
                key = (node.get("target", ""), node.get("text", ""))
                inferred[slug][key] += 1
                owners[slug, key].add(name)
            elif node.get("type") == "action" and "action" not in node:
                unmatched[node.get("text", "")] += 1
                owners["", node.get("text", "")].add(name)
            for value in node.values():
                walk(name, value)
        elif isinstance(node, list):
            for item in node:
                walk(name, item)

    for name, npc in npcs.items():
        walk(name, npc)

    def examples(key):
        names = sorted(owners[key])
        shown = ", ".join(names[:3])
        return f"{shown}{', +%d more' % (len(names) - 3) if len(names) > 3 else ''}"

    total = sum(sum(c.values()) for c in inferred.values())
    lines = [
        "Inferred dialogue actions",
        "=" * 72,
        "Generated by scripts/dialogues/update.py -- do not edit by hand.",
        "",
        "Every step in the INFERRED sections was slugged by matching a regex against",
        "the wiki's prose, not by reading a template parameter, and carries",
        'action_source="text" in docs/npc-dialogues.json. Read each line and check',
        "the slug (and target) describe what the prose says. Wrong ones mean a",
        "pattern in PROSE_ACTIONS is too loose; the UNMATCHED section is the other",
        "half of the review -- anything there that clearly is one of the slugs means",
        "a pattern is too tight.",
        "",
        "Template-derived slugs (opens/opens2/receives/gives) are exact and are not",
        "listed here.",
        "",
        f"{total} inferred steps, {sum(unmatched.values())} left as prose.",
        "",
    ]
    for slug in sorted(inferred):
        counts = inferred[slug]
        lines.append("")
        lines.append(
            f"INFERRED {slug}  ({sum(counts.values())} steps, {len(counts)} distinct)"
        )
        lines.append("-" * 72)
        for (target, text), count in counts.most_common():
            lines.append(f"  [{count:>3}] {text}".rstrip())
            if target:
                lines.append(f"        target: {target}")
            lines.append(f"        npcs:   {examples((slug, (target, text)))}")
    lines.append("")
    lines.append("")
    lines.append(
        f"UNMATCHED  ({sum(unmatched.values())} steps, {len(unmatched)} distinct) "
        "-- still prose, no action key"
    )
    lines.append("-" * 72)
    for text, count in unmatched.most_common():
        lines.append(f"  [{count:>3}] {text}".rstrip())
        lines.append(f"        npcs:   {examples(('', text))}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="Use the saved wiki sources."
    )
    parser.add_argument(
        "--out", type=Path, default=config.DOCS_PATH / "npc-dialogues.json"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Refresh cached wiki revisions"
    )
    args = parser.parse_args()
    if args.offline and args.refresh:
        parser.error("--refresh cannot be combined with --offline")
    if args.offline:
        missing = [
            str(path)
            for path in (CACHE, QUEST_CACHE, NPC_CACHE, TEMPLATE_CACHE)
            if not path.exists()
        ]
        if missing:
            parser.error(
                "Missing source caches; run online first: " + ", ".join(missing)
            )
    pages = read_cache(CACHE) if args.offline else fetch(refresh=args.refresh)
    nav_templates = load_navigation_templates()
    bindings = json.loads(
        (config.DATA_PATH / "dialogues" / "runtime-bindings.json").read_text()
    )
    npcs, quests, issues = {}, {}, {}
    for sources, output in ((pages, npcs), (read_cache(QUEST_CACHE), quests)):
        for title, page in sorted(sources.items()):
            if page.get("missing"):
                issues[title] = [{"reason": "Missing referenced page"}]
                continue
            name = title.removeprefix("Transcript:")
            structure = bindings.get(name, {}).get("structure")
            raw = apply_structure_annotations(
                name, page["wikitext"], structure, page["revision"]
            )
            parsed = parse_npc(name, raw, nav_templates)
            output[name] = gameplay_npc(name, parsed)
            output[name]["source"] = {"page": title, "revision": page["revision"]}
            if parsed["review_issues"]:
                issues[title] = parsed["review_issues"]
    if npcs.keys() & quests.keys():
        raise ValueError("NPC and quest transcript names overlap")
    index = enrich_records(npcs, quests, read_cache(NPC_CACHE), clean, bindings)
    resolved = resolve_shops(npcs, shop_index())
    # Shared quest replies retain their NPC source IDs, including inferred shops.
    source_shops = {
        node["id"]: node["target"]
        for record in npcs.values()
        for steps in [
            *record["variants"].values(),
            *record.get("branches", {}).values(),
        ]
        for node in dialogue_nodes(steps)
        if node.get("action") == "open_shop" and "id" in node
    }
    for record in quests.values():
        for steps in [
            *record["variants"].values(),
            *record.get("branches", {}).values(),
        ]:
            for node in dialogue_nodes(steps):
                if (
                    node.get("action") == "open_interface"
                    and node.get("id") in source_shops
                ):
                    node["target"] = source_shops[node["id"]]
    resolved += resolve_shops(quests, shop_index())
    slayer = resolve_slayer(npcs, slayer_masters())
    report_text = action_report({**npcs, **quests})
    authoring = {}
    for group in (npcs, quests):
        for name, record in group.items():
            authoring["Transcript:" + name] = compact_record(record)
    dialogues = dict(sorted({**npcs, **quests}.items()))
    data = {"records": dialogues, "authoring": authoring, "index": index}
    apply_bindings(data, bindings)
    apply_corrections(
        data,
        json.loads((config.DATA_PATH / "dialogues" / "corrections.json").read_text()),
    )
    dialogues = dict(sorted(data["records"].items()))
    report = config.DATA_PATH / "dialogues" / "inferred-actions.txt"
    report.write_text(report_text)
    save(config.DATA_PATH / "dialogues" / "authoring-index.json", authoring)
    save(args.out, dialogues)
    save(args.out.with_name("npc-dialogues-minified.json"), dialogues, minified=True)
    save(args.out.with_name("npc-dialogue-index.json"), index)
    write_split(args.out.parent, (dialogues,))
    save(config.DATA_PATH / "dialogues" / "review-issues.json", issues)
    print(
        f"Wrote {len(npcs)} NPCs and {len(quests)} quest/reference pages, {sum(len(n.get('variants', {'standard-dialogue': n.get('steps', [])})) for n in npcs.values())} variants, "
        f"{sum('steps' in n or n.get('default') is not None for n in npcs.values())} selected defaults to {args.out}"
    )
    print(f"Resolved {resolved} interfaces to a named shop")
    print(f"Slugged {slayer} Slayer lines")


if __name__ == "__main__":
    main()
