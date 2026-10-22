import json

import config
from scripts.dialogues import update
from scripts.dialogues.compact import compact_record
from scripts.dialogues.hooks import enrich_records


def test_ordinary_bold_speaker_label_still_parses():
    assert update.parse_step("'''Monk:''' Hello.", [], 1) == {
        "type": "line",
        "speaker": "Monk",
        "text": "Hello.",
    }


def test_quoted_nowiki_speaker_keeps_quoted_identity():
    assert update.parse_step(
        "'''<nowiki>'Black-eye':</nowiki>''' Why, thanks.", [], 1
    ) == {
        "type": "line",
        "speaker": "'Black-eye'",
        "text": "Why, thanks.",
    }


def test_colon_inside_closing_quote_is_structural():
    assert update.parse_step(
        "'''<nowiki>'No fingers:'</nowiki>''' I do have many boots.", [], 1
    ) == {
        "type": "line",
        "speaker": "'No fingers'",
        "text": "I do have many boots.",
    }


def test_colon_outside_closing_quote_is_structural():
    assert update.parse_step(
        "'''<nowiki>'The Guns'</nowiki>:''' Shirt.", [], 1
    ) == {
        "type": "line",
        "speaker": "'The Guns'",
        "text": "Shirt.",
    }


def test_anchor_prefixed_quoted_speaker_keeps_both():
    assert update.parse_step(
        "{{anchor|guns}}'''<nowiki>'The Guns':</nowiki>''' Shirt.", [], 1
    ) == {
        "type": "line",
        "speaker": "'The Guns'",
        "text": "Shirt.",
        "_anchors": ["guns"],
    }


def test_non_speech_bold_text_stays_unparsed():
    node = update.parse_step("'''Note'''", [], 1)
    assert node == {"type": "unparsed", "raw": "'''Note'''"}
    assert update.gameplay_step(node, "Monk") == {"type": "unavailable"}


def test_cached_tower_of_life_parses_quoted_speakers():
    pages = json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text()
    )
    source = pages["Transcript:Tower of Life"]
    record = update.gameplay_npc(
        "Tower of Life", update.parse_npc("Tower of Life", source["wikitext"])
    )
    record["source"] = {
        "page": "Transcript:Tower of Life",
        "revision": source["revision"],
    }
    enrich_records({}, {"Tower of Life": record}, {}, update.clean)
    compact_record(record)

    expected = {
        "Why, thanks.": "'Black-eye'",
        "Bingo! Okay, now what takes 3 planks, 3 cloths and 3 nails to make, "
        "and helps remove light from a room?": "'Black-eye'",
        "Well... Urmph! Ye can 'ave me shirt...": "'The Guns'",
        "I do have many boots.": "'No fingers'",
    }
    found = {}
    old_ids = {"mZhTt4", "LZ3lbQ", "wT2tpz", "h5aJ8E"}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, dict):
                if node.get("text") in expected:
                    found[node["text"]] = node
                assert node.get("id") not in old_ids
                walk(node.get("steps", []))
                walk(node.get("options", []))

    for steps in record["variants"].values():
        walk(steps)

    assert set(found) == set(expected)
    for text, speaker in expected.items():
        assert found[text]["speaker"] == speaker
