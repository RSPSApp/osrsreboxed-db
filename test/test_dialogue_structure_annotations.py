"""Reviewed bullet-depth annotations stay source-backed and fail closed."""

import copy
import hashlib
import json

import pytest

import config
from scripts.dialogues import update
from scripts.dialogues.hooks import enrich_records

PAGE = "Transcript:Icthlarin's Little Helper"
NAME = "Icthlarin's Little Helper"
HIGH_PRIEST = (
    "figuring-out-what-on-gielinor-is-going-on-"
    "talking-to-the-high-priest-after-receiving-the-sphinx-s-token"
)
SPHINX_RIDDLE = "figuring-out-what-on-gielinor-is-going-on-asking-the-sphinx-for-help"


def source():
    return json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text()
    )[PAGE]


def structure():
    return json.loads(
        (config.DATA_PATH / "dialogues" / "runtime-bindings.json").read_text()
    )[NAME]["structure"]


def annotated_raw():
    page = source()
    assert structure()["revision"] == page["revision"]
    return update.apply_structure_annotations(
        NAME, page["wikitext"], structure(), page["revision"]
    )


def variants():
    return update.parse_npc(NAME, annotated_raw())["variants"]


def enriched_variants():
    parsed = update.parse_npc(NAME, annotated_raw())
    record = update.gameplay_npc(NAME, parsed)
    record["source"] = {"page": PAGE, "revision": source()["revision"]}
    enrich_records({}, {NAME: record}, {}, update.clean)
    return record["variants"]


def find(nodes, predicate):
    for node in nodes:
        if predicate(node):
            return node
        found = find(node.get("steps", []), predicate)
        if found:
            return found
        for option in node.get("options", []):
            found = find(option.get("steps", []), predicate)
            if found:
                return found
    return None


def test_annotation_changes_only_the_two_reviewed_bullet_depths():
    before = source()["wikitext"].splitlines()
    after = annotated_raw().splitlines()
    assert len(before) == len(after)
    changed = [
        number
        for number, pair in enumerate(zip(before, after), 1)
        if pair[0] != pair[1]
    ]
    assert changed == [259, 415]
    for number in changed:
        assert before[number - 1].lstrip("*") == after[number - 1].lstrip("*")


def test_annotation_preserves_line_endings_and_trailing_newline():
    raw = "intro\r\n** keep\r\n* target\r\nend\r\n"
    fix = {
        "revision": 7,
        "lines": [
            {
                "line": 3,
                "sha256": hashlib.sha256(b"* target").hexdigest(),
                "depth": 2,
            }
        ],
    }
    assert update.apply_structure_annotations("Example", raw, fix, 7) == (
        "intro\r\n** keep\r\n** target\r\nend\r\n"
    )


def test_annotation_rejects_a_changed_source_line():
    stale = copy.deepcopy(structure())
    stale["lines"][0]["sha256"] = "0" * 64
    with pytest.raises(
        ValueError,
        match="Stale dialogue structure annotation: Icthlarin's Little Helper line 259",
    ):
        update.apply_structure_annotations(NAME, source()["wikitext"], stale)


def test_annotation_rejects_a_stale_revision():
    with pytest.raises(
        ValueError,
        match="Stale dialogue structure annotation: Icthlarin's Little Helper",
    ):
        update.apply_structure_annotations(
            NAME, source()["wikitext"], structure(), structure()["revision"] + 1
        )


def test_annotation_rejects_an_out_of_range_line():
    stale = copy.deepcopy(structure())
    stale["lines"][0]["line"] = len(source()["wikitext"].splitlines()) + 1
    with pytest.raises(
        ValueError,
        match="Stale dialogue structure annotation: Icthlarin's Little Helper line",
    ):
        update.apply_structure_annotations(NAME, source()["wikitext"], stale)


def test_annotation_rejects_a_non_bullet_line():
    raw = "==Talk==\n* '''Guide:''' Hi.\n"
    fix = {
        "lines": [
            {
                "line": 1,
                "sha256": hashlib.sha256(b"==Talk==").hexdigest(),
                "depth": 2,
            }
        ]
    }
    with pytest.raises(
        ValueError,
        match="Unbulleted dialogue structure annotation: Example line 1",
    ):
        update.apply_structure_annotations("Example", raw, fix)


def test_high_priest_token_conditions_are_sibling_branches():
    steps = variants()[HIGH_PRIEST]["steps"]
    no_token, has_token = steps[-2:]
    assert no_token["type"] == "condition"
    assert no_token["text"] == "If player does not have the token:"
    assert no_token["steps"] == [
        {
            "type": "line",
            "speaker": "Player",
            "text": "She gave me a token to show you, but I lost it.",
        },
        {
            "type": "line",
            "speaker": "High Priest",
            "text": "Well then stop wasting my time! Can't you see I'm trying to put a stop to these plagues?",
        },
        {"type": "end"},
    ]
    assert has_token["type"] == "condition"
    assert has_token["text"] == "If the player has the token:"
    assert has_token["steps"][0] == {
        "type": "message",
        "text": "You hand the token to the High Priest.",
        "image": "Sphinx's_token_detail.png",
    }
    assert has_token["steps"][-1]["type"] == "choice"
    assert [option["text"] for option in has_token["steps"][-1]["options"]] == [
        "Why is it so important that the jar be returned?",
        "Can you tell me more about the plagues.",
        "Can you tell me more about Icthlarin.",
        "Can you tell me more about the Devourer.",
        "I'd better get going.",
    ]


def test_high_priest_branches_keep_their_ids_and_actions_after_annotation():
    steps = enriched_variants()[HIGH_PRIEST]
    no_token, has_token = steps[-2:]
    assert no_token["id"]
    assert has_token["id"]
    assert no_token["steps"][-1]["id"]
    choice = has_token["steps"][-1]
    assert choice["id"]
    assert all(option["id"] for option in choice["options"])
    assert [node.get("reference") for node in choice["options"][0]["steps"]] == [
        "below"
    ]


def test_sphinx_answers_are_one_menu_with_are_you_sure_in_the_seven_branch():
    steps = variants()[SPHINX_RIDDLE]["steps"]
    menu = find(
        steps,
        lambda node: node.get("type") == "choice"
        and any(
            option["text"] == "Okay, that sounds fair." for option in node["options"]
        ),
    )
    fair = next(
        option
        for option in menu["options"]
        if option["text"] == "Okay, that sounds fair."
    )
    answers = next(node for node in fair["steps"] if node.get("type") == "choice")
    assert [option["text"] for option in answers["options"]] == [
        "7.",
        "9.",
        "12.",
        "14.",
        "I don't know.",
    ]
    seven = answers["options"][0]["steps"]
    assert seven[0] == {"type": "line", "speaker": "Player", "text": "7."}
    assert seven[1] == {"type": "line", "speaker": "Sphinx", "text": "Are you sure?"}
    assert seven[2]["type"] == "message"
    assert seven[3]["type"] == "choice"
    assert [option["text"] for option in seven[3]["options"]] == [
        "Totally positive.",
        "I don't know. I don't want to risk my cat.",
    ]
    assert answers["options"][2]["steps"] == [
        {
            "type": "action",
            "text": "Same as answering 7 (incorrect answer)",
            "parameters": {"1": "Same as answering 7 (incorrect answer)"},
        }
    ]
    assert answers["options"][3]["steps"] == answers["options"][2]["steps"]


def test_sphinx_answer_options_keep_their_ids_choices_and_order():
    steps = enriched_variants()[SPHINX_RIDDLE]
    menu = find(
        steps,
        lambda node: node.get("type") == "choice"
        and any(
            option["text"] == "Okay, that sounds fair." for option in node["options"]
        ),
    )
    fair = next(
        option
        for option in menu["options"]
        if option["text"] == "Okay, that sounds fair."
    )
    answers = next(node for node in fair["steps"] if node.get("type") == "choice")
    assert answers["id"]
    assert all(option["id"] for option in answers["options"])
    seven = answers["options"][0]["steps"]
    assert seven[1]["id"]
    assert seven[3]["id"]
    assert all(option["id"] for option in seven[3]["options"])
    assert seven[3]["options"][0]["steps"][2]["id"]


def test_annotation_leaves_unannotated_pages_unchanged():
    raw = "==Talk==\n* '''Guide:''' Hi.\n"
    assert update.apply_structure_annotations("Guide", raw) == raw
