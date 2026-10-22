import json
import sys
from pathlib import Path

import pytest

import config
from scripts.dialogues import fetch as fetch_module
from scripts.dialogues import update
from scripts.dialogues.compact import compact_record
from scripts.dialogues.hooks import enrich_records


def test_terminal_end_before_quest_completion_becomes_reachable():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text()
    )["Transcript:Shilo Village"]
    parsed = update.parse_npc("Shilo Village", source["wikitext"])
    variant = parsed["variants"][
        "visiting-the-tomb-of-rashiliyia-using-rashiliyias-remains-on-the-dolmen"
    ]
    assert [node.get("type") or "line" for node in variant["steps"]] == [
        "message",
        "line",
        "line",
        "action",
        "end",
    ]

    record = update.gameplay_npc("Shilo Village", parsed)
    record["source"] = {
        "page": "Transcript:Shilo Village",
        "revision": source["revision"],
    }
    enrich_records({}, {"Shilo Village": record}, {}, update.clean)
    compact_record(record)
    steps = record["variants"][
        "visiting-the-tomb-of-rashiliyia-using-rashiliyias-remains-on-the-dolmen"
    ]
    assert steps[-1] == {
        "type": "action",
        "text": "Congratulations! Quest complete!",
        "id": "l7zrz_",
    }


def test_end_before_unrelated_content_remains_terminal():
    parsed = update.parse_npc(
        "Bob",
        "==Standard dialogue==\n"
        "* '''Bob:''' Hi.\n"
        "* {{tact|end}}\n"
        "* {{tbox|Unrelated content.}}",
    )
    steps = parsed["variants"]["standard-dialogue"]["steps"]
    assert steps[1] == {"type": "end"}
    assert steps[2] == {"type": "message", "text": "Unrelated content."}


def test_offline_requires_the_template_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "TEMPLATE_CACHE", tmp_path / "missing-template.json")
    monkeypatch.setattr(
        sys, "argv", ["update", "--offline", "--out", str(tmp_path / "out.json")]
    )
    with pytest.raises(SystemExit):
        update.main()
    assert not (tmp_path / "out.json").exists()


def test_navigation_template_cache_loads_fresh_metadata(monkeypatch, tmp_path):
    cache = tmp_path / "template-pages.json"
    cache.write_text(
        json.dumps(
            {
                "Template:Bob": {
                    "revision": 1,
                    "wikitext": "{{Navbox}}",
                    "categories": ["Category:Navbox templates"],
                }
            }
        )
    )
    monkeypatch.setattr(fetch_module, "TEMPLATE_CACHE", cache)
    assert fetch_module.load_navigation_templates() == {"Bob"}
