"""Resolve transcript reuse only when the source supplies an unambiguous body."""

import copy
import json
import re


def text_key(text):
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def own(node):
    return {
        k: v
        for k, v in node.items()
        if k not in ("id", "steps", "options", "condition_key")
        and not k.startswith("_")
    }


ARTICLES = re.compile(r"\b(?:the|a|an)\b", re.I)


def utterance_key(text):
    """Fold case, punctuation and articles; never match partial utterances."""
    return text_key(ARTICLES.sub(" ", text or ""))


def player_text(node):
    if "player" in node:
        return node["player"]
    if node.get("type") == "line" and node.get("speaker") == "Player":
        return node.get("text", "")
    return None


def short_label(text):
    return 0 < len(text_key(text)) <= 4


def complementary(left, right):
    """True for the same predicate with opposite negation, e.g. has/has not."""

    def polarity(text):
        text = re.sub(r"^(?:if|when)\s+", "", text or "", flags=re.I)
        negated = bool(re.search(r"\b(?:not|never|n't)\b", text, re.I))
        return negated, text_key(re.sub(r"\b(?:not|never)\b", " ", text, re.I))

    left, right = polarity(left), polarity(right)
    return left[0] != right[0] and bool(left[1]) and left[1] == right[1]


def locations(steps, speaker=None, menu=None, option=None):
    for index, node in enumerate(steps):
        if node.get("speaker") and node["speaker"] != "Player":
            speaker = node["speaker"]
        yield node, steps, index, speaker, menu, option
        yield from locations(node.get("steps", []), speaker, menu, option)
        for alternative in node.get("options", []):
            yield from locations([alternative], speaker, node, alternative)


def resolve_shared(npcs, quests, identities):
    sources = {}
    for name, record in npcs.items():
        options = {}
        for steps in record["variants"].values():
            for node, *_ in locations(steps):
                for option in node.get("options", []):
                    if option.get("steps") and not all(
                        n.get("type") == "jump" for n in option["steps"]
                    ):
                        options.setdefault(text_key(option.get("text", "")), []).append(
                            option["steps"]
                        )
        sources[name] = options
    for record in quests.values():
        participants = record.get("participants", [])
        for steps in record["variants"].values():
            for node, _, _, speaker, _, _ in list(locations(steps)):
                if not node.pop("_shared", False) or node.get("steps"):
                    continue
                candidates = [
                    name
                    for name in participants
                    if name in sources
                    and speaker in identities.get(name, ([], {name}))[1]
                ]
                bodies = [
                    (name, body)
                    for name in candidates
                    for body in sources[name].get(text_key(node.get("text", "")), [])
                ]
                distinct = {}
                shop_targets = {
                    child["target"]
                    for _, body in bodies
                    for child, *_ in locations(body)
                    if child.get("action") == "open_interface"
                    and "shop" in child.get("target", "").casefold()
                }
                for name, body in bodies:
                    comparable = strip_ids(body)
                    if len(shop_targets) == 1:
                        for child, *_ in locations(comparable):
                            if (
                                child.get("action") == "open_interface"
                                and not child.get("target")
                                and re.fullmatch(
                                    r"\(?Shop interface opens\.?\)?",
                                    child.get("text", ""),
                                    re.I,
                                )
                            ):
                                child.pop("text", None)
                                child.pop("action_source", None)
                                child["target"] = next(iter(shop_targets))
                    signature = json.dumps(comparable, sort_keys=True)
                    if signature not in distinct or any(
                        child.get("target") in shop_targets
                        for child, *_ in locations(body)
                    ):
                        distinct[signature] = name, body
                if len(distinct) != 1:
                    continue
                name, body = next(iter(distinct.values()))
                node["steps"] = copy.deepcopy(body)
                for child, *_ in locations(node["steps"]):
                    if "npc" in child:
                        child.update(type="line", speaker=name, text=child.pop("npc"))
    for record in [*npcs.values(), *quests.values()]:
        for steps in record["variants"].values():
            for node, *_ in locations(steps):
                node.pop("_shared", None)


def strip_ids(value):
    if isinstance(value, list):
        return [strip_ids(child) for child in value]
    if isinstance(value, dict):
        return {
            k: strip_ids(v)
            for k, v in value.items()
            if k not in ("id", "condition_key") and not k.startswith("_")
        }
    return value


def resolve_navigation(record, anchors=None):
    omit_selected = record.pop("_omit_selected", [])
    option_paths = {}

    def contexts(nodes, ancestors):
        for node in nodes:
            option_paths[id(node)] = ancestors
            contexts(node.get("steps", []), ancestors)
            for option in node.get("options", []):
                contexts([option], ancestors + [option.get("text", "")])

    for steps in record["variants"].values():
        contexts(steps, [])
    entries = [
        (variant, *entry)
        for variant, steps in record["variants"].items()
        for entry in locations(steps)
    ]
    positions = {id(entry[1]): i for i, entry in enumerate(entries)}
    parents = {id(node["steps"]): node for _, node, *_ in entries if "steps" in node}
    containers = {id(node): steps for _, node, steps, *_ in entries}
    explicit_anchors = {}
    for entry in entries:
        for anchor in entry[1].get("_anchors", []):
            explicit_anchors.setdefault(anchor, []).append(entry)

    def begins_option(entry):
        _, _, siblings, at, _, _, option = entry
        if option is None or at != 0:
            return False
        body = option.get("steps", [])
        if siblings is body:
            return True
        # A leading run of guards can introduce alternative Player prefixes.
        parent = parents.get(id(siblings))
        for child in body:
            if child.get("type") != "condition":
                break
            if child is parent:
                return True
        return False

    anchored = {}
    for source, anchor in (anchors or {}).items():
        jumps = [entry for entry in entries if entry[1].get("id") == source]
        destinations = [
            entry for entry in entries if entry[1].get("id") == anchor["after"]
        ]
        if (
            len(jumps) != 1
            or jumps[0][1].get("type") != "jump"
            or jumps[0][1].get("reference") != anchor["expected"]
            or len(destinations) != 1
        ):
            raise ValueError(f"Stale dialogue navigation anchor: {source}")
        _, _, siblings, at, *_ = destinations[0]
        if not siblings[at + 1 :]:
            raise ValueError(f"Empty dialogue navigation anchor: {source}")
        anchored[id(jumps[0][1])] = siblings[at + 1 :]

    def condition_template(variant, condition):
        label = re.sub(r"\s*\([^)]*\)", "", record["sections"][variant][-1])
        text = condition.get("text", "")
        replaced = re.sub(
            r"\b" + re.escape(label) + r"\b", "<section>", text, flags=re.I
        )
        return replaced.casefold() if replaced != text else None

    pending = {}
    named = {}
    for variant, node, steps, index, speaker, menu, option in entries:
        reference = node.get("reference", "")
        if node.get("type") == "action" and not node.get("action"):
            reference = node.get("text", "")
        if not reference:
            continue
        anchor = node.get("_anchor")
        if anchor:
            matches = explicit_anchors.get(anchor, [])
            if len(matches) == 1:
                _, target_node, siblings, at, _, _, target_option = matches[0]
                target = (
                    target_node.get("steps", [])
                    if target_option is target_node
                    else siblings[at:]
                )
                if target:
                    pending[id(node)] = target
            continue
        headings = [
            key
            for key, path in record["sections"].items()
            if text_key(reference) in (text_key(key), text_key(path[-1]))
        ]
        if len(headings) == 1 and id(node) not in anchored:
            key = headings[0]
            choices = {
                text_key(option.get("text", ""))
                for child, *_ in locations(record["variants"][key])
                for option in child.get("options", [])
            }
            skip = (
                next(
                    (
                        text_key(text)
                        for text in reversed(option_paths[id(node)])
                        if text_key(text) in choices
                    ),
                    None,
                )
                if key in omit_selected
                else None
            )
            named[id(node)] = (key, skip)
            continue
        quoted = re.fullmatch(
            r'Continues?\s+(?:(above|below)\s+)?(after|from|as)\s+["“](.+?)["”](?:\s+(above|below))?\.?',
            reference,
            re.I,
        )
        target = anchored.get(id(node))
        direction = "above" if reference == "above" else "below"
        here = positions[id(node)]
        if target is None and quoted:
            direction = (quoted[1] or quoted[4] or "above").casefold()
            key = text_key(quoted[3].rstrip("."))
            if quoted[2].casefold() == "as":
                matches = [
                    entry
                    for entry in entries
                    if entry[1].get("steps")
                    and text_key(entry[1].get("text", "")) == key
                ]
                if len(matches) == 1:
                    target = matches[0][1]["steps"]
            matches = [
                entry
                for entry in entries
                if (
                    entry[1].get("type") == "line"
                    or "npc" in entry[1]
                    or "player" in entry[1]
                )
                and text_key(
                    entry[1].get(
                        "text", entry[1].get("npc", entry[1].get("player", ""))
                    )
                ).startswith(key)
            ]
            if target is None and len(matches) == 1:
                _, _, siblings, at, *_ = matches[0]
                target = siblings[at + (quoted[2].casefold() == "after") :]
        elif target is None and reference in ("above", "below"):
            # A repeated preceding line identifies the shared tail precisely.
            previous = own(steps[index - 1]) if index else None
            matches = [
                entry
                for entry in entries
                if entry[0] == variant
                and previous
                and own(entry[1]) == previous
                and entry[1] is not steps[index - 1]
                and (
                    positions[id(entry[1])] < here
                    if direction == "above"
                    else positions[id(entry[1])] > here
                )
            ]
            matches.sort(key=lambda entry: abs(positions[id(entry[1])] - here))
            if matches:
                _, _, siblings, at, *_ = matches[0]
                target = siblings[at + 1 :]
            elif previous and (
                "npc" in previous
                or "player" in previous
                or previous.get("type") == "line"
            ):
                tails = [
                    siblings[at + 1 :]
                    for other, candidate, siblings, at, *_ in entries
                    if other != variant
                    and own(candidate) == previous
                    and (
                        positions[id(candidate)] < here
                        if direction == "above"
                        else positions[id(candidate)] > here
                    )
                    and any(
                        child.get("type") not in ("jump", "end")
                        for child in siblings[at + 1 :]
                    )
                    and not any(
                        child.get("type") == "jump"
                        for child, *_ in locations(siblings[at + 1 :])
                    )
                ]
                distinct = {
                    json.dumps(strip_ids(tail), sort_keys=True): tail for tail in tails
                }
                if len(distinct) == 1:
                    target = next(iter(distinct.values()))
            parent = parents.get(id(steps), {})
            template = (
                condition_template(variant, parent)
                if parent.get("type") == "condition"
                else None
            )
            if target is None and template:
                bodies = [
                    candidate[1].get("steps", [])
                    for candidate in entries
                    if candidate[1].get("type") == "condition"
                    and condition_template(candidate[0], candidate[1]) == template
                    and (
                        positions[id(candidate[1])] < here
                        if direction == "above"
                        else positions[id(candidate[1])] > here
                    )
                    and any(
                        child.get("type") not in ("jump", "end")
                        for child in candidate[1].get("steps", [])
                    )
                ]
                distinct = {
                    json.dumps(strip_ids(body), sort_keys=True): body for body in bodies
                }
                if len(distinct) == 1:
                    target = next(iter(distinct.values()))
            if target is None and menu and option:
                same = [
                    (candidate[1]["steps"], candidate[5])
                    for candidate in entries
                    if candidate[1] is not option
                    and (
                        len(text_key(option.get("text", ""))) >= 12
                        or (
                            "npc_ids" in record
                            and text_key(option.get("text", ""))
                            not in {"yes", "no", "ok", "okay"}
                        )
                    )
                    and ("npc_ids" in record or candidate[4] == speaker)
                    and candidate[1].get("text") == option.get("text")
                    and (
                        positions[id(candidate[1])] < here
                        if direction == "above"
                        else positions[id(candidate[1])] > here
                    )
                    and candidate[1].get("steps")
                    and any(
                        child.get("type") not in ("jump", "end")
                        for child in candidate[1]["steps"]
                    )
                ]
                labels = {text_key(child.get("text", "")) for child in menu["options"]}
                matched = [
                    body
                    for body, context in same
                    if context
                    and {
                        text_key(child.get("text", "")) for child in context["options"]
                    }
                    == labels
                ]
                same = matched or [body for body, _ in same]
                distinct = {
                    json.dumps(strip_ids(body), sort_keys=True): body for body in same
                }
                if len(distinct) == 1:
                    target = next(iter(distinct.values()))
            # A long option label repeated verbatim as Player speech names the
            # option body it introduces. Repeating the option itself must not
            # replay that spoken prefix. The whole label is compared, not a stem.
            if (
                target is None
                and menu
                and option
                and len(text_key(option.get("text", ""))) >= 12
            ):
                key = utterance_key(option.get("text", ""))
                bodies = {}
                for candidate in entries:
                    other, spoken = candidate[6], player_text(candidate[1])
                    if (
                        other is None
                        or other is option
                        or spoken is None
                        or not begins_option(candidate)
                        or utterance_key(spoken) != key
                        or candidate[4] != speaker
                        or (positions[id(candidate[1])] < here)
                        != (direction == "above")
                    ):
                        continue
                    body = other.get("steps", [])
                    repeated = (
                        body
                        and player_text(body[0]) is not None
                        and utterance_key(player_text(body[0]))
                        == utterance_key(other.get("text", ""))
                    )
                    body = body[1:] if repeated else body
                    if any(child.get("type") not in ("jump", "end") for child in body):
                        bodies[id(other)] = body
                if len(bodies) == 1:
                    target = next(iter(bodies.values()))

            # Short labels need the whole menu and the adjacent section to
            # identify their acceptance; a nearby opposite answer is not one.
            if (
                target is None
                and menu
                and option
                and short_label(option.get("text", ""))
                and len(menu.get("options", [])) > 1
            ):
                labels = {text_key(child.get("text", "")) for child in menu["options"]}
                keys = list(record["variants"])
                adjacent = keys.index(variant) + (-1 if direction == "above" else 1)
                bodies = {}
                source_path = record["sections"][variant]
                adjacent_path = record["sections"].get(
                    keys[adjacent] if 0 <= adjacent < len(keys) else "", []
                )
                related_section = (
                    adjacent_path
                    and source_path[:-1] == adjacent_path[:-1]
                    and text_key(adjacent_path[-1]).startswith(
                        text_key(source_path[-1])
                    )
                )
                if related_section:
                    for candidate in entries:
                        if (
                            candidate[0] != keys[adjacent]
                            or candidate[6] is None
                            or candidate[4] != speaker
                        ):
                            continue
                        other_menu, other = candidate[5], candidate[6]
                        if (
                            other_menu is menu
                            or {
                                text_key(child.get("text", ""))
                                for child in other_menu.get("options", [])
                            }
                            != labels
                            or text_key(other.get("text", ""))
                            != text_key(option.get("text", ""))
                        ):
                            continue
                        body = other.get("steps", [])
                        if any(
                            child.get("type") not in ("jump", "end") for child in body
                        ):
                            bodies[id(other)] = body
                if len(bodies) == 1:
                    target = next(iter(bodies.values()))

            # A "below" inside one of two complementary conditional siblings
            # resumes the other branch's shared tail, not its player reply.
            if (
                target is None
                and reference == "below"
                and previous
                and player_text(previous) is not None
                and index == len(steps) - 1
            ):
                parent = parents.get(id(steps))
                outer = containers.get(id(parent)) if parent else None
                if parent and parent.get("type") == "condition" and outer:
                    at = outer.index(parent)
                    if at + 1 < len(outer):
                        sibling = outer[at + 1]
                        if sibling.get("type") == "condition" and complementary(
                            parent.get("text", ""), sibling.get("text", "")
                        ):
                            body = sibling.get("steps", [])
                            if (
                                body
                                and player_text(body[0]) is not None
                                and any(
                                    child.get("type") not in ("jump", "end")
                                    for child in body[1:]
                                )
                            ):
                                target = body[1:]

            if target is None and menu and option:
                alternatives = menu["options"]
                at = alternatives.index(option)
                candidates = (
                    alternatives[:at][::-1]
                    if direction == "above"
                    else alternatives[at + 1 :]
                )
                for candidate in candidates:
                    body = candidate.get("steps", [])
                    if candidate.get("text") != option.get("text") and (
                        reference == "above" or short_label(option.get("text", ""))
                    ):
                        continue
                    start = (
                        1
                        if body
                        and ("player" in body[0] or body[0].get("speaker") == "Player")
                        else 0
                    )
                    if any(
                        n.get("type") not in ("jump", "end") and "player" not in n
                        for n in body[start:]
                    ):
                        target = body[start:]
                        break
        elif (
            target is None
            and reference in ("continue", "continues")
            and menu
            and option
        ):
            # The final alternative often spells out the continuation shared by
            # earlier replies. Only borrow its explicit follow-up menu.
            alternatives = menu["options"]
            at = alternatives.index(option)
            for candidate in alternatives[at + 1 :]:
                body = candidate.get("steps", [])
                next_menu = next(
                    (
                        i
                        for i, child in enumerate(body)
                        if child.get("type") == "choice"
                    ),
                    None,
                )
                if next_menu is not None:
                    target = body[next_menu:]
                    break
        if target:
            pending[id(node)] = target

    for _, node, *_ in entries:
        node.pop("_anchor", None)
        node.pop("_anchors", None)

    from scripts.dialogues.hooks import token

    targets = {}
    routes = {}
    for key, target in pending.items():
        branch = "jump-" + token([node.get("id") for node in target])
        targets[branch] = target
        routes[key] = branch

    def expand(nodes):
        result = []
        for original in nodes:
            node = dict(original)
            key = id(original)
            if key in named:
                variant, skip = named[key]
                node = {
                    "type": "call",
                    "branch": variant + ("-without-" + skip if skip else ""),
                }
            elif key in pending:
                node = {k: v for k, v in node.items() if k not in ("text", "action")}
                node.update(
                    type="jump", steps=[{"type": "call", "branch": routes[key]}]
                )
                if node.get("reference") in ("above", "below"):
                    node.pop("reference")
            else:
                if "steps" in original:
                    node["steps"] = expand(original["steps"])
                if "options" in original:
                    node["options"] = expand(original["options"])
            result.append(node)
        return result

    record["variants"] = {
        key: expand(steps) for key, steps in record["variants"].items()
    }
    for key, target in targets.items():
        record.setdefault("branches", {})[key] = expand(target)
    for key, skip in sorted(
        set(named.values()), key=lambda item: (item[0], item[1] or "")
    ):
        branch = copy.deepcopy(record["variants"][key])
        if skip:
            for node, *_ in locations(branch):
                if node.get("type") == "choice":
                    node["options"] = [
                        option
                        for option in node["options"]
                        if text_key(option.get("text", "")) != skip
                    ]
                    break
        record.setdefault("branches", {})[
            key + ("-without-" + skip if skip else "")
        ] = branch

    def immediate_calls(steps):
        calls = set()
        for node in steps:
            if (
                "npc" in node
                or "player" in node
                or node.get("type") in ("line", "message", "input", "choice", "random")
            ):
                break
            if node.get("type") == "call":
                calls.add(node["branch"])
            calls.update(immediate_calls(node.get("steps", [])))
        return calls

    graph = {
        key: immediate_calls(steps) for key, steps in record.get("branches", {}).items()
    }
    unsafe, done = set(), set()

    def visit(key, active):
        if key in active:
            unsafe.update(active[active.index(key) :])
        elif key not in done:
            for child in graph.get(key, []):
                visit(child, active + [key])
            done.add(key)

    for key in graph:
        visit(key, [])
    if unsafe:
        if not unsafe <= targets.keys():
            raise ValueError(
                "Named dialogue sections form a loop without a player/UI step"
            )
        original = {node.get("id"): node for _, node, *_ in entries}
        for steps in [
            *record["variants"].values(),
            *record.get("branches", {}).values(),
        ]:
            for node, *_ in list(locations(steps)):
                if node.get("type") == "jump" and any(
                    child.get("branch") in unsafe for child in node.get("steps", [])
                ):
                    source = copy.deepcopy(original[node["id"]])
                    node.clear()
                    node.update(source)
        for key in unsafe:
            del record["branches"][key]
