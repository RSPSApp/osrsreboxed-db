import json

import config
from scripts.dialogues import update
from scripts.dialogues.hooks import enrich_records
from scripts.shops.shop_owners import npc_ids_from_wikitext


def test_mixed_switch_infoboxes_union_all_recognized_instances():
    wikitext = """{{Switch infobox
|item1 = {{Infobox Monster
|id = 101, 102 <!-- inline comment -->
}}
|item2 = {{Infobox NPC
|id = 201
}}
}}"""
    assert npc_ids_from_wikitext(wikitext) == [101, 102, 201]


def test_repeated_recognized_infoboxes_are_unioned():
    wikitext = "{{Infobox NPC|id=11}}{{Infobox Monster|id=12}}"
    assert npc_ids_from_wikitext(wikitext) == [11, 12]
    assert npc_ids_from_wikitext(
        "{{Infobox NPC|id=21}}{{Infobox NPC|id=22}}"
    ) == [21, 22]


def test_ordinary_single_npc_infobox():
    assert npc_ids_from_wikitext("{{Infobox NPC|id=42}}") == [42]


def test_unrelated_infobox_is_rejected():
    assert npc_ids_from_wikitext("{{Infobox Item|id=99}}") == []
    assert npc_ids_from_wikitext("{{Infobox Scenery|id=99}}") == []
    assert npc_ids_from_wikitext("{{Infobox Pet|id=99}}") == []


def test_inline_html_comments_do_not_corrupt_ids():
    assert npc_ids_from_wikitext("{{Infobox NPC|id=<!--c-->3}}") == [3]
    assert npc_ids_from_wikitext("{{Infobox NPC|id=4<!--c-->}}") == [4]
    assert npc_ids_from_wikitext("{{Infobox NPC|id=1<!--c-->2}}") == [12]


def test_cached_general_khazard_keeps_monster_and_npc_identities():
    pages = json.loads(
        (config.DATA_PATH / "dialogues" / "npc-pages.json").read_text()
    )
    ids = npc_ids_from_wikitext(pages["General Khazard"]["wikitext"])
    assert 12054 in ids
    assert 3510 in ids
    assert 12059 in ids


def test_fight_arena_index_contains_actual_arena_host_12054():
    npc_pages = json.loads(
        (config.DATA_PATH / "dialogues" / "npc-pages.json").read_text()
    )
    quest_pages = json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text()
    )
    source = quest_pages["Transcript:Fight Arena"]
    record = update.gameplay_npc(
        "Fight Arena", update.parse_npc("Fight Arena", source["wikitext"])
    )
    index = enrich_records(
        {},
        {"Fight Arena": record},
        {"General Khazard": npc_pages["General Khazard"]},
        update.clean,
    )
    assert any(
        entry["page"] == "Transcript:Fight Arena"
        and "the-battles-upon-killing-the-khazard-ogre" in entry["variants"]
        for entry in index["12054"]
    )
    assert "3510" in index
