import copy
import hashlib
import json

import pytest

import config
from scripts.dialogues.corrections import apply_corrections, fingerprint
from scripts.dialogues import update
from scripts.dialogues.update import apply_capture_lines


def test_corrections_preserve_ids_additions_deletions_and_indexes():
    data = {
        "records": {"X": {"steps": [{"type": "missing", "id": "old-id"}]}},
        "authoring": {
            "Transcript:X": {"sections": {"standard-dialogue": ["Standard dialogue"]}}
        },
        "index": {"1": [{"page": "Transcript:X", "variants": ["standard-dialogue"]}]},
    }
    replacement = [{"type": "message", "id": "quest:handover", "text": "Done."}]
    corrections = {
        "X": {
            "base_sha256": fingerprint(data["records"]["X"]),
            "changes": [
                {
                    "path": ["records", "X", "steps"],
                    "expected": fingerprint(data["records"]["X"]["steps"]),
                },
                {
                    "path": ["records", "X", "variants"],
                    "expected": None,
                    "value": {"resume": replacement},
                },
                {"path": ["records", "X", "default"], "expected": None, "value": None},
                {
                    "path": ["authoring", "Transcript:X", "sections"],
                    "expected": fingerprint(
                        data["authoring"]["Transcript:X"]["sections"]
                    ),
                    "value": {"resume": ["Resume"]},
                },
                {
                    "path": ["index", "1", 0, "variants"],
                    "expected": fingerprint(["standard-dialogue"]),
                    "value": ["resume"],
                },
            ],
        }
    }
    apply_corrections(data, corrections)
    assert data["records"]["X"] == {
        "variants": {"resume": replacement},
        "default": None,
    }
    assert data["index"]["1"][0]["variants"] == ["resume"]
    assert data["authoring"]["Transcript:X"]["sections"] == {"resume": ["Resume"]}
    replacement[0]["text"] = "Changed source"
    assert data["records"]["X"]["variants"]["resume"][0]["text"] == "Done."


def test_captured_record_requires_absent_source_and_rejects_a_new_wiki_record():
    record = {"steps": [{"npc": "Captured speech."}]}
    correction = {
        "base_sha256": None,
        "changes": [
            {"path": ["records", "Captured"], "expected": None, "value": record}
        ],
    }
    data = {"records": {}}
    apply_corrections(data, {"Captured": correction})
    assert data["records"]["Captured"] == record
    with pytest.raises(ValueError, match="Stale dialogue correction: Captured"):
        apply_corrections(data, {"Captured": correction})

    wiki = {"records": {"Captured": {"steps": [{"npc": "New wiki speech."}]}}}
    before = copy.deepcopy(wiki)
    with pytest.raises(ValueError, match="Stale dialogue correction: Captured"):
        apply_corrections(wiki, {"Captured": correction})
    assert wiki == before


@pytest.mark.parametrize("conflict", ["record", "path", "expected"])
def test_stale_corrections_do_not_partially_apply(conflict):
    data = {"records": {"X": {"steps": [1, 2]}}}
    correction = {
        "base_sha256": fingerprint(data["records"]["X"]),
        "changes": [
            {
                "path": ["records", "X", "steps", 0],
                "expected": fingerprint(1),
                "value": 3,
            },
            {
                "path": ["records", "X", "steps", 1],
                "expected": fingerprint(2),
                "value": 4,
            },
        ],
    }
    if conflict == "record":
        data["records"]["X"]["steps"][1] = 5
    elif conflict == "path":
        correction["changes"][1]["path"] = ["records", "X", "missing", 0]
    else:
        correction["changes"][1]["expected"] = fingerprint(5)
    before = copy.deepcopy(data)
    with pytest.raises(ValueError, match="Stale dialogue correction: X"):
        apply_corrections(data, {"X": correction})
    assert data == before


def test_dump_applies_corrections_before_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "dialogues.update",
            "--offline",
            "--out",
            str(tmp_path / "npc-dialogues.json"),
        ],
    )
    monkeypatch.setattr(update, "read_cache", lambda path: {})
    monkeypatch.setattr(update, "shop_index", lambda: {})
    monkeypatch.setattr(update, "slayer_masters", lambda: set())
    monkeypatch.setattr(update, "apply_bindings", lambda *args: None)
    monkeypatch.setattr(
        update,
        "save",
        lambda *args, **kwargs: pytest.fail("Published before checking corrections"),
    )

    def stale(data, corrections):
        assert corrections
        raise ValueError("Stale dialogue correction")

    monkeypatch.setattr(update, "apply_corrections", stale)
    with pytest.raises(ValueError, match="Stale dialogue correction"):
        update.main()
    assert not list(tmp_path.iterdir())


def test_rocky_narration_lines_continue_the_conversation():
    # The Wiki writes these as bare prose, which parsed as unavailable markers and ended the chat.
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    options = dialogues["Rocky"]["variants"]["standard-dialogue"][0]["options"]
    first, fourth = options[0]["steps"], options[3]["steps"]
    assert first[1] == {"type": "action", "text": "You slip your hand into Rocky's pocket.", "id": "B65XlG"}
    assert first[2]["npc"].startswith("OY!! You're going to have to do better than that!")
    assert fourth[2] == {"type": "action", "text": "Rocky jumps into your backpack...", "id": "JL_pBJ"}
    assert fourth[4] == {"type": "action", "text": "Rocky flicks the coin back into your backpack", "id": "BJK-M1"}
    assert fourth[5] == {"player": "I better keep my eyes on you..."}
    assert "unavailable" not in json.dumps(dialogues["Rocky"]["variants"]["standard-dialogue"])


def test_captured_ides_line_replaces_the_wiki_typo():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variant = dialogues["The Ides of Milk"]["variants"][
        "starting-off-talking-to-gillie"
    ]
    text = json.dumps(variant)
    assert "he'll be happy" in text
    assert "he'll he happy" not in text


def test_baraek_medium_clue_answer_prompt_is_spoken_by_baraek():
    # Live sends "Baraek|Please enter the answer to the question." with his chathead
    # (revision 227 capture); the Wiki transcript names Dunstan, a copy from his page.
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    again = dialogues["Baraek"]["variants"]["treasure-trails-medium-when-talked-to-again"]
    assert again[0] == {"npc": "Please enter the answer to the question."}
    assert "Dunstan" not in json.dumps(dialogues["Baraek"])


def test_prince_ali_rescue_keeps_the_captured_paste_line_and_the_wiki_flow():
    record = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())[
        "Prince Ali Rescue"
    ]
    variants = record["variants"]
    aggie = json.dumps(variants["preparations-for-rescue-talking-to-aggie"])
    assert (
        "Yes, I can. I see you already have the ingredients - the water, flour,"
        " ashes and redberries. Would you like me to mix some for you now?"
    ) in aggie
    assert "Yes I can. I see you already have the ingredients." not in aggie

    # The Wiki's first visit to Leela always explains the plan; a visit with every
    # item is the separate "after having all the required items" variant.
    leela = variants["starting-out-talking-to-leela"]
    assert [step.get("player") or step.get("text") for step in leela[:3]] == [
        "You must be Leela. Your father sent me to help rescue Prince Ali.",
        "Yes, he sent word ahead that you'd be coming. Are you aware of the plan?",
        "I need to obtain a copy of the key to the Prince's cell, create a disguise"
        " for him that makes him look like Keli and then break him out of the jail.",
    ]
    assert "I already have everything we need." not in json.dumps(leela)
    prepared = variants[
        "preparations-for-rescue-talking-to-leela-after-having-all-the-required-items"
    ]
    assert [step.get("player") or step.get("text") for step in prepared[:2]] == [
        "You're back. Do you have everything needed yet?",
        "I do indeed.",
    ]

    # The Wiki asks "Not too drunk?" after every first beer, before branching on
    # the beers still held.
    for steps in [
        variants["executing-the-rescue-talking-to-joe"][2]["options"][0]["steps"],
        record["branches"]["jump-c2dcd1ef49d2a376"],
    ]:
        assert steps[4]["text"] == "That was perfect! I can't thank you enough."
        assert steps[5] == {"player": "How are you? Still okay? Not too drunk?"}
        fewer, more = steps[6], steps[7]
        assert fewer["text"] == "If the player has less than three beers:"
        assert fewer["steps"][0]["text"].startswith(
            "No, I don't get drunk from only one drink."
        )
        assert more["text"] == "If the player has two more beers:"
        assert more["steps"][0] == {
            "player": "Would you care for another beer, my friend?"
        }


def test_witchs_house_follows_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = dialogues["Witch's House"]["variants"]
    start = variants["getting-started"][2]["options"][0]["steps"][3]["options"][0]
    assert start["steps"][1]["text"] == "Thanks, mister!"
    boy = dialogues["Boy"]["variants"]["before-witch-s-house"]
    assert boy[2]["options"][0]["steps"][2]["options"][0]["steps"][1] == {
        "npc": "Thanks, mister!"
    }
    # The locked back door is a game message the plugin sends; the transcript is the
    # player's live line alone.
    assert variants[
        "the-witch-s-house-attempting-to-open-the-garden-door-without-unlocking-it"
    ] == [
        {
            "player": "It's locked. That's strange - I can't see any kind of lock"
            " or handle to open it..."
        }
    ]
    gate = variants["the-witch-s-house-attempting-to-open-the-gate-without-correct-gloves"]
    assert gate[0]["text"] == "As your hands touch the gate you feel a shock."
    form = variants["the-ball-killing-the-first-form"]
    assert form[0]["text"] == "The shapeshifters' body begins to deform!"

    # Node-level edits only: no generated variant or branch is supplied whole.
    corrections = json.loads(
        (config.DATA_PATH / "dialogues" / "corrections.json").read_text(encoding="utf-8")
    )
    for name in ("Witch's House", "Boy"):
        for change in corrections[name]["changes"]:
            assert len(change["path"]) > 4, change["path"]
            assert not isinstance(change.get("value"), (list, dict)), change["path"]

    # The back door is a source input applied to the cached Wiki revision before
    # parsing, not a post-parse edit of the generated variant.
    assert not any(
        "garden-door-without-unlocking-it" in str(key)
        for change in corrections["Witch's House"]["changes"]
        for key in change["path"]
    )
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Witch's House"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Witch's House"
    ]
    assert source["revision"] == page["revision"]
    lines = page["wikitext"].splitlines()
    for fix in source["lines"]:
        assert hashlib.sha256(lines[fix["line"] - 1].encode()).hexdigest() == fix["sha256"]
    raw = apply_capture_lines("Witch's House", page["wikitext"], source, page["revision"])
    assert "This door is locked." not in raw
    assert "It's locked. That's strange" in raw
    # Applying it twice from the same inputs is identical; a moved revision stops the dump.
    assert raw == apply_capture_lines("Witch's House", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Witch's House", page["wikitext"], source, page["revision"] + 1)


def test_biohazard_follows_the_revision_242_capture():
    # speaker_ids is derived identity metadata, not part of the captured wording.
    variants = json.loads(
        (config.DOCS_PATH / "npc-dialogues.json").read_text(),
        object_hook=lambda node: {k: v for k, v in node.items() if k != "speaker_ids"},
    )["Biohazard"]["variants"]
    # Before the wall is crossed, Elena points back to Jerico (capture tick 29).
    assert variants["getting-started-talking-to-elena-again"] == [
        {"player": "Hello Elena."},
        {"type": "line", "speaker": "Elena", "text": "Hello friend. Any luck finding my distillator?"},
        {"player": "No, I'm afraid not."},
        {
            "type": "line",
            "speaker": "Elena",
            "text": "Speak to Jerico, he might be able to help you cross the wall. He lives"
            " in a house south east of here, north of the chapel.",
        },
    ]
    # The mud patch stays under the first conversation with Elena.
    assert "getting-started-talking-to-elena-trying-to-dig-in-the-mud-patch" in variants
    assert variants["getting-started-talking-to-jerico-again"][:2] == [
        {"player": "Hello Jerico."},
        {"type": "line", "speaker": "Jerico", "text": "Hello again. Have you spoken to Omart yet?"},
    ]
    # Talking to Jerico after Omart already opened with the greeting; it gains no second one.
    after_omart = variants["getting-started-talking-to-jerico-after-talking-to-omart"]
    assert [step.get("player") for step in after_omart[:2]] == ["Hello Jerico.", None]
    assert variants["visiting-south-east-varrock-talking-to-asyff"][1] == {
        "player": "Errr... what are you saying exactly?"
    }

    # Source inputs over the cached revision, not edits of the generated record.
    corrections = json.loads(
        (config.DATA_PATH / "dialogues" / "corrections.json").read_text(encoding="utf-8")
    )
    assert "Biohazard" not in corrections
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Biohazard"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Biohazard"
    ]
    assert source["revision"] == page["revision"]
    lines = page["wikitext"].splitlines()
    for fix in source["lines"]:
        assert hashlib.sha256(lines[fix["line"] - 1].encode()).hexdigest() == fix["sha256"]
    raw = apply_capture_lines("Biohazard", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Biohazard", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Biohazard", page["wikitext"], source, page["revision"] + 1)


def test_goblin_diplomacy_peace_answer_returns_to_the_captured_menu():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    record = dialogues["Goblin Diplomacy"]
    branches = record["branches"]
    first = record["variants"]["starting-off-talking-to-general-wartface-or-general-bentnoze"][0]
    why = first["options"][0]["steps"][8]["options"][0]["steps"][3]["options"][0]["steps"]
    answers = [
        why[5]["options"][1]["steps"],
        branches["jump-0e7d80c33faa9aaa"][5]["options"][1]["steps"],
        branches["jump-eb18bfb27195d785"],
    ]
    # Every copy of the answer ends in the menu live shows, without the question just
    # asked (revision 242 capture, ticks 126 and 138).
    for peace in answers:
        assert peace[0] == {"player": "Wouldn't you prefer peace?"}
        menu = peace[-1]
        assert menu["type"] == "choice"
        assert [option["text"] for option in menu["options"]] == [
            "Why are you arguing about the colour of your armour?",
            "Do you want me to pick an armour colour for you?",
            "I'll leave you to it.",
        ]
        for option in menu["options"]:
            (call,) = option["steps"]
            assert call["type"] == "call" and call["branch"] in branches
            assert branches[call["branch"]][0] == {"player": option["text"]}


def test_shadow_of_the_storm_golem_exchange_plays_once_with_both_sigil_branches():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    source = json.loads(
        (config.DATA_PATH / "dialogues/quest-pages.json").read_text()
    )["Transcript:Shadow of the Storm"]["wikitext"]
    variant = dialogues["Shadow of the Storm"]["variants"][
        "performing-the-ritual-talking-to-the-golem-after-reprogramming"
    ]

    def spoken(node):
        return node.get("text") or node.get("player") or node.get("npc") or ""

    def texts(steps):
        for node in steps:
            yield spoken(node)
            yield from texts(node.get("steps", []))
            for option in node.get("options", []):
                yield from texts(option.get("steps", []))

    exchange = [
        "I sensed a great darkness, as of a demon revelling in its moment of triumph.",
        "And now this sandstorm appears, the likes of which I have not seen in three thousand years. What can it mean?",
        "Denath was Agrith-Naar all along! We've accidentally helped him get back to his own dimension!",
        "It is a terrible thing for a demon to be victorious. I wish there was something I could do to rectify the situation.",
        "You could help me summon the demon again so I could kill him!",
        "What are we waiting for? What do I need to do?",
    ]
    assert [spoken(node) for node in variant[:6]] == exchange
    assert [node.get("text") for node in variant[6:]] == [
        "While having a demonic sigil:",
        "Without a demonic sigil:",
    ]
    played = list(texts(variant))
    for line in exchange + ["I need to get you a demonic sigil.", "I will wait."]:
        assert played.count(line) == 1, line
    assert [text for text in texts(variant[6]["steps"]) if text] == [
        "Take this demonic sigil and go through the portal."
    ]
    assert [text for text in texts(variant[7]["steps"]) if text] == [
        "I need to get you a demonic sigil.",
        "I will wait.",
    ]
    assert all(text in source for text in played if text)


def test_audited_variants_are_indexed():
    index = json.loads((config.DOCS_PATH / "npc-dialogue-index.json").read_text())
    authoring = json.loads(
        (config.DATA_PATH / "dialogues/authoring-index.json").read_text()
    )
    for name, variant in [
        ("Shantay", "arrested"),
        ("The Ides of Milk", "returning-to-cassius-after-sampling-the-milk-resume"),
    ]:
        page = "Transcript:" + name
        assert variant in authoring[page]["sections"]
        assert any(
            entry["page"] == page and variant in entry["variants"]
            for entries in index.values()
            for entry in entries
        )


def test_cache_bound_shared_npc_variants_are_indexed():
    index = json.loads((config.DOCS_PATH / "npc-dialogue-index.json").read_text())
    for npc_id in ("913", "1987"):
        assert len(index[npc_id]) == 1
        entry = index[npc_id][0]
        assert entry["page"] == "Transcript:Shadow of the Storm"
        assert "to-uzer-talking-to-evil-dave" in entry["variants"]
        assert "after-killing-agrith-naar-evil-dave" in entry["variants"]
    assert index["15839"] == [
        {
            "page": "Transcript:The Blood Moon Rises",
            "variants": ["pre-release-dialogue", "starting-out"],
        }
    ]


def test_correction_inserts_a_node_before_its_anchor_and_rejects_a_stale_anchor():
    steps = [{"npc": "One."}, {"type": "message", "text": "Two.", "id": "keep"}]
    data = {"records": {"X": {"steps": copy.deepcopy(steps)}}}
    branch = {"type": "condition", "text": "If asked:", "steps": [], "id": "x:new"}
    correction = {
        "base_sha256": fingerprint(data["records"]["X"]),
        "changes": [
            {
                "path": ["records", "X", "steps", 1],
                "expected": fingerprint(steps[1]),
                "insert": branch,
            }
        ],
    }
    apply_corrections(data, {"X": correction})
    assert [s.get("id") for s in data["records"]["X"]["steps"]] == [
        None,
        "x:new",
        "keep",
    ]
    branch["id"] = "mutated"
    assert data["records"]["X"]["steps"][1]["id"] == "x:new"

    fresh = {"records": {"X": {"steps": copy.deepcopy(steps)}}}
    fresh["records"]["X"]["steps"][1]["text"] = "Changed upstream."
    correction["base_sha256"] = fingerprint(fresh["records"]["X"])
    with pytest.raises(ValueError, match="Stale dialogue correction: X"):
        apply_corrections(fresh, {"X": correction})
    off_end = {"records": {"X": {"steps": copy.deepcopy(steps)}}}
    correction["base_sha256"] = fingerprint(off_end["records"]["X"])
    correction["changes"][0]["path"] = ["records", "X", "steps", 5]
    correction["changes"][0]["expected"] = None
    with pytest.raises(ValueError, match="Stale dialogue correction: X"):
        apply_corrections(off_end, {"X": correction})


def test_dragon_slayer_i_follows_the_revision_242_capture():
    path = config.DOCS_PATH / "npc-dialogues.json"
    record = json.loads(path.read_text(encoding="utf-8"))["Dragon Slayer I"]
    text = json.dumps(record, ensure_ascii=False)
    assert "with each of them taking one piece" in text
    assert "which each of them taking" not in text
    assert "Well, you're braver than I!" in text
    assert "a braver man than I" not in text
    assert "Of course! How does 2,000 coins sound?" in text
    assert "I'm sure the work needed to do on it" not in text
    needle = "Ask me about Melzar's map piece again when you have enough free inventory space for the key."
    key_nodes = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("id") == "dragon-slayer-i:melzar-key-no-space":
                key_nodes.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(record)
    assert len(key_nodes) == 2  # the variant and the shared branch
    for node in key_nodes:
        assert node["type"] == "condition"
        assert node["steps"][0]["text"] == needle
        # dragon.txt:23987: after the reply the Guildmaster's follow-up menu opens again.
        assert node["steps"][-1] == {
            "type": "jump",
            "reference": "other",
            "id": "dragon-slayer-i:melzar-key-no-space-menu",
        }


def _list_correction(items, changes):
    data = {"records": {"X": {"steps": list(items)}}}
    return data, {
        "X": {"base_sha256": fingerprint(data["records"]["X"]), "changes": changes}
    }


def _at(index, anchor, **change):
    expected = None if anchor is None else fingerprint(anchor)
    return {"path": ["records", "X", "steps", index], "expected": expected, **change}


def test_correction_indices_name_the_record_before_any_change_in_any_order():
    items = ["a", "b", "c"]
    for changes in (
        [_at(1, "b", insert="NEW"), _at(2, "c", value="C")],
        [_at(2, "c", value="C"), _at(1, "b", insert="NEW")],
    ):
        data, corrections = _list_correction(items, changes)
        apply_corrections(data, corrections)
        assert data["records"]["X"]["steps"] == ["a", "NEW", "b", "C"]
    for changes in ([_at(1, "b"), _at(2, "c")], [_at(2, "c"), _at(1, "b")]):
        data, corrections = _list_correction(items, changes)
        apply_corrections(data, corrections)
        assert data["records"]["X"]["steps"] == ["a"]
    data, corrections = _list_correction(items, [_at(0, "a"), _at(2, "c", value="C")])
    apply_corrections(data, corrections)
    assert data["records"]["X"]["steps"] == ["b", "C"]
    # A node's own edit goes before inserts at its index; inserts there keep their listed order.
    data, corrections = _list_correction(
        items, [_at(1, "b", insert="X1"), _at(1, "b"), _at(1, "b", insert="X2")]
    )
    apply_corrections(data, corrections)
    assert data["records"]["X"]["steps"] == ["a", "X1", "X2", "c"]
    data, corrections = _list_correction(items, [_at(3, None, insert="END")])
    apply_corrections(data, corrections)
    assert data["records"]["X"]["steps"] == ["a", "b", "c", "END"]


@pytest.mark.parametrize(
    "changes, message",
    [
        ([_at(-1, None, insert="NEW")], "Stale"),
        ([_at(-1, "c", value="C")], "Stale"),
        ([_at(3, None, value="D")], "Stale"),
        ([_at(3, None)], "Stale"),
        ([_at(1, "b", insert="NEW", value="B")], "Stale"),
        ([_at(1, "b", value="B"), _at(1, "b")], "Conflicting"),
    ],
)
def test_correction_rejects_unanchored_or_conflicting_list_changes(changes, message):
    data, corrections = _list_correction(["a", "b", "c"], changes)
    before = copy.deepcopy(data)
    with pytest.raises(ValueError, match=f"{message} dialogue correction: X"):
        apply_corrections(data, corrections)
    assert data == before


def test_correction_rejects_an_edit_inside_a_replaced_node():
    data = {"records": {"X": {"steps": [{"text": "a"}]}}}
    node = data["records"]["X"]["steps"][0]
    corrections = {
        "X": {
            "base_sha256": fingerprint(data["records"]["X"]),
            "changes": [
                {
                    "path": ["records", "X", "steps", 0],
                    "expected": fingerprint(node),
                    "value": {"text": "b"},
                },
                {
                    "path": ["records", "X", "steps", 0, "text"],
                    "expected": fingerprint("a"),
                    "value": "c",
                },
            ],
        }
    }
    with pytest.raises(ValueError, match="Conflicting dialogue correction: X"):
        apply_corrections(data, corrections)


def test_crab_quest_capture_lines_insert_and_reword_before_parsing():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Crab Quest"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Crab Quest"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Crab Quest", page["wikitext"], source, page["revision"])
    lines = raw.splitlines()
    # The inserted line lands ahead of its anchor, which is kept unchanged.
    tune = lines.index("* '''Crab:''' We can make a great tune with this!")
    assert lines[tune + 1].startswith("* '''Crab:''' Oh no... I can't easily play 13 different shells")
    assert len(lines) == len(page["wikitext"].splitlines()) + 1
    assert "how the practice is going." in raw and "how the practise is going." not in raw
    assert "But anyway, we are done here." in raw and "anyways" not in raw
    assert raw == apply_capture_lines("Crab Quest", page["wikitext"], source, page["revision"])
    # An anchor whose line moved stops the dump, inserts included.
    moved = "\n" + page["wikitext"]
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Crab Quest", moved, source, page["revision"])
    with pytest.raises(ValueError, match="Invalid dialogue capture source"):
        apply_capture_lines(
            "Crab Quest", page["wikitext"],
            {**source, "lines": [{**source["lines"][0], "insert_before": ["a\nb"]}]},
            page["revision"],
        )
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    assert "We can make a great tune with this!" in json.dumps(exported["Crab Quest"])


def test_twilights_promise_capture_lines_add_the_requirements_ending():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Twilight's Promise"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Twilight's Promise"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Twilight's Promise", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Twilight's Promise", page["wikitext"], source, page["revision"])
    # The captured comma after "Well", and the capitalised Colosseum.
    assert "'''Player:''' Well, this doesn't sound totally orthodox" in raw
    assert "Well this doesn't sound totally orthodox" not in raw
    assert "Where can I find the colosseum?" not in raw
    # Lines the capture doesn't play stay as cached.
    assert "Well rules are rules, I'm afraid." in raw
    # The unmet-requirements ending goes ahead of the Wiki's, which moves one level down.
    lines = raw.splitlines()
    unmet = lines.index(
        "* {{tcond|If the player does not meet all of the requirements to start The Heart of Darkness:}}"
    )
    assert lines[unmet + 3] == (
        "** '''Prince Itzla Arkan:''' Thank you, iknami. Timoiva for now, and may the sun light your way."
    )
    assert lines[unmet + 7].startswith("** '''Prince Itzla Arkan:''' Word has been sent to mother")
    assert len(lines) == len(page["wikitext"].splitlines()) + 7
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    ending = exported["Twilight's Promise"]["variants"][
        "the-twilight-emissaries-after-defeating-the-cultists"
    ]
    conditions = [step for step in ending if step.get("type") == "condition"]
    assert [c["text"].startswith("If the player does not meet") for c in conditions] == [True, False]
    assert conditions[0]["steps"][-2] == {
        "type": "action", "text": "Congratulations! Quest complete!", "id": conditions[0]["steps"][-2]["id"],
    }
    assert conditions[1]["steps"][-1]["type"] == "choice"


def test_sea_slug_capture_lines_box_the_torch_and_drop_the_repeat():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Sea Slug"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Sea Slug"
    ]
    assert source["revision"] == int(page["revision"])
    raw = apply_capture_lines("Sea Slug", page["wikitext"], source, int(page["revision"]))
    assert raw == apply_capture_lines("Sea Slug", page["wikitext"], source, int(page["revision"]))
    lines = raw.splitlines()
    # Kennith's after-the-wall exchange plays once (the Wiki repeats its first three lines).
    assert sum("Kennith, I've made an opening in the wall." in line for line in lines) == 1
    # The free-space branch gets the torch box the no-space branch already had, ahead of the hand-out.
    free = lines.index("* {{tcond|If the player has one free space in their in their inventory:}}")
    assert lines[free + 1] == "** {{tbox|pic=Unlit torch detail.png|Bailey gives you a torch.}}"
    assert lines[free + 2] == "** {{tact|receives=an unlit torch}}"
    assert "** {{mes|I need to get closer to use that.}}" in lines
    assert "I need to get closer to that." not in raw
    # The dropped repeat leaves three blank lines; the box adds one.
    assert len(lines) == len(page["wikitext"].splitlines()) + 1
    moved = "\n" + page["wikitext"]
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Sea Slug", moved, source, int(page["revision"]))
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Sea Slug"]
    after_wall = exported["variants"]["freeing-kennith-talking-to-kennith-after-making-a-hole-in-the-wall"]
    clear = next(step for step in after_wall if step.get("text") == "If there are no sea slugs or fishermen nearby:")
    assert [step.get("player") or step.get("text") for step in clear["steps"]][:3] == [
        "Kennith, I've made an opening in the wall. You can come out through there.",
        "Are there any sea slugs on the other side?",
        "Not one.",
    ]
    assert clear["steps"][3]["text"] == "How will I get downstairs?"


def test_observatory_quest_follows_the_revision_242_capture():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Observatory Quest"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Observatory Quest"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Observatory Quest", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Observatory Quest", page["wikitext"], source, page["revision"])
    assert "Just a plain stove. Nothing there." in raw and "Nothing here." not in raw
    lines = raw.splitlines()
    # Two lines are emptied and one is inserted, so the transcript is a line longer.
    assert len(lines) == len(page["wikitext"].splitlines()) + 1
    # Handing over the mould starts at the professor's question (capture tick 1013).
    mould = lines.index("==Returning with the lens mould==")
    assert lines[mould + 4 : mould + 7] == ["", "", "** '''Observatory professor:''' Did you bring me the mould?"]
    # The molten-glass hand-in keeps its own two lines.
    glass = lines.index("==Returning with molten glass==")
    assert lines[glass + 4] == "** '''Observatory professor:''' How are you getting on finding me some molten glass?"
    # The professor asks for the lens before it is handed over (tick 1038).
    lens = lines.index("==Returning with the observatory lens==")
    assert lines[lens + 4] == "** '''Observatory professor:''' Is the lens finished?"
    assert lines[lens + 5] == "** '''Player:''' Yes, here it is. You may as well take this mould too."
    # The hand-over sits under its menu option, so Treasure Trails is the menu's other option.
    assert lines[lens + 13] == "*** {{tact|end}}"
    assert lines[lens + 14] == "* {{topt|quest=no|Talk about Treasure Trails.}}"
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Observatory Quest", "\n" + page["wikitext"], source, page["revision"])

    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = exported["Observatory Quest"]["variants"]
    returning = json.dumps(variants["returning-with-the-lens-mould"])
    assert "How are you getting on finding me some molten glass?" not in returning
    assert "Did you bring me the mould?" in returning
    lens_variant = variants["returning-with-the-observatory-lens"]
    assert "Is the lens finished?" in json.dumps(lens_variant)
    menu = next(step for step in lens_variant if step.get("type") == "choice")
    assert [option["text"] for option in menu["options"]] == [
        "Talk about the Observatory quest.", "Talk about Treasure Trails."
    ]
    assert variants["inspecting-the-goblin-stove"][0]["text"] == "Just a plain stove. Nothing there."
    # The step ids TSPS binds.
    text = json.dumps(variants)
    # The lens hand-over and the closing box sit one level deeper, so their ids moved (HgpGGr, vj7Nry).
    for step_id in ("JH15Z2", "URgSXm", "HgpGGr", "vj7Nry", "Y5Z4-D", "Lmq76H"):
        assert f'"{step_id}"' in text


def test_plague_city_capture_lines_add_jethick_and_the_clerk():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Plague City"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Plague City"
    ]
    assert source["revision"] == int(page["revision"])
    raw = apply_capture_lines("Plague City", page["wikitext"], source, int(page["revision"]))
    assert raw == apply_capture_lines("Plague City", page["wikitext"], source, int(page["revision"]))
    lines = raw.splitlines()
    # The inserts are the Wiki's own lines from its other sections; nothing new is worded.
    cached = set(page["wikitext"].splitlines())
    for fix in source["lines"]:
        for line in fix.get("insert_before", []):
            assert line.lstrip("*") in {other.lstrip("*") for other in cached} or "{{t" in line
    # 10 intro lines, the 12-line book offer (the section's end becomes a blank line), the clerk's
    # option and its jump.
    assert len(lines) == len(page["wikitext"].splitlines()) + 10 + 12 + 2
    moved = "\n" + page["wikitext"]
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Plague City", moved, source, int(page["revision"]))
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Plague City"]["variants"]
    # Jethick's first talk with the picture (capture ticks 372-380) opens with the king conversation.
    first = exported["finding-elena-talking-to-jethick-after-getting-elena-s-picture"][0]
    assert [step.get("player") for step in first["steps"]][1] == "How come?"
    assert first["steps"][-1]["text"].startswith("Anyway, you clearly didn't come here to talk about kings.")
    # Again before delivering the book (397-405), he still offers it.
    again = exported[
        "finding-elena-talking-to-jethick-after-getting-elena-s-picture-talking-to-jethick-again-before-delivering-the-book"
    ]
    assert again[-2]["text"].startswith("I don't suppose you could run me a little errand")
    assert [option["text"] for option in again[-1]["options"]] == [
        "Yes, I'll return it for you.", "No, I don't have time for that.",
    ]
    # The clerk's menu after "Rather you than me!" has the third option (597-602).
    clerk = exported["finding-elena-talking-to-the-clerk-before-getting-permission-to-speak-to-bravek"]
    menu = clerk[1]["options"][0]["steps"][2]
    assert [option["text"] for option in menu["options"]] == [
        "I'll try asking them then.",
        "Surely you don't let them run everything for you?",
        "This is urgent though! Someone's been kidnapped!",
    ]


def test_historian_minas_reports_follow_the_captures():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Historian Minas"]
    page = json.loads((config.DATA_PATH / "dialogues/wiki-pages.json").read_text())[
        "Transcript:Historian Minas"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Historian Minas", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Historian Minas", page["wikitext"], source, page["revision"])
    lines = raw.splitlines()
    # Curse of the Empty Lord gains its three lamp lines and Making History those three and its
    # lamp box; every other fix replaces a line.
    assert len(lines) == len(page["wikitext"].splitlines()) + 7
    # The Wiki writes these narration boxes as bare prose, which parsed as unavailable markers.
    assert lines.count("*** {{tbox|You receive an old lamp.}}") == 4
    assert (
        "*** {{tbox|The historian pulls out his writing implements and listens while you explain the whole story....}}"
        in lines
    )
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Historian Minas", "\n" + page["wikitext"], source, page["revision"])

    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Historian Minas"]

    def find(steps, step_id):
        for step in steps or []:
            if step.get("id") == step_id:
                return step
            found = find(step.get("steps"), step_id)
            for option in step.get("options") or []:
                found = found or find(option.get("steps"), step_id)
            if found:
                return found
        return None

    def flow(step_id):
        return [
            step.get("player") and ("player", step["player"])
            or step.get("npc") and ("npc", step["npc"])
            or (step["type"], step.get("text"))
            for step in find(exported["steps"], step_id)["steps"]
        ]

    # Hazeel Cult: the box comes before Minas's closing line, so the report reaches it.
    hazeel = flow("9_Sehd")
    assert hazeel[-2] == (
        "message",
        "The historian pulls out his writing implements and listens while you explain the whole story....",
    )
    assert hazeel[-1] == ("npc", "How exciting, I'll get a display put up immediately. Display number 7, 5th Age, year 7.")
    assert "Zamorakian lord" in hazeel[-3][1]
    # Shield of Arrav, Merlin's Crystal and Making History end on the lamp box, like Defender of Varrock.
    for step_id in ("QqHvp-", "RaNFxc", "4Ij9Rt", "jeha67"):
        assert flow(step_id)[-1] == ("message", "You receive an old lamp.")
    assert flow("QqHvp-")[2] == ("player", "Erm, yes... Anyway, I managed to get half the Shield of Arrav back.")
    # The two Salve reports as the captures play them.
    assert flow("3q8-VQ")[0] == (
        "player", "I discovered some disturbing yet heroic information about the vampyres of Morytania."
    )
    assert flow("dHMXRQ")[-1] == ("npc", "How fascinating. I'll have the display updated. Number 23, 4th Age, year 1100-1200.")
    assert flow("0sSqOl")[-1] == ("npc", "You're welcome!")
    assert flow("IqnOid")[2] == ("player", "Don't worry. I put a stop to their plots.")
    # No report closes on an unavailable marker any more.
    reports = find(exported["steps"], "S57fCr")
    assert reports is not None
    for step_id in ("S57fCr", "QqHvp-", "oGD9-i", "GpIr8R", "RaNFxc", "EZzFyt", "3q8-VQ", "dHMXRQ",
                    "Yq_0tv", "4Ij9Rt", "SJoct1", "0sSqOl", "9_Sehd", "IqnOid", "jeha67"):
        assert '"unavailable"' not in json.dumps(find(exported["steps"], step_id))


def test_ghosts_ahoy_follows_the_revision_242_capture():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    bindings = json.loads(
        (config.DATA_PATH / "dialogues" / "runtime-bindings.json").read_text(encoding="utf-8")
    )
    quest = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Ghosts Ahoy"
    ]
    wiki = json.loads((config.DATA_PATH / "dialogues/wiki-pages.json").read_text())
    structure = bindings["Ghosts Ahoy"]["structure"]
    structured = update.apply_structure_annotations(
        "Ghosts Ahoy", quest["wikitext"], structure, quest["revision"]
    )
    raw = apply_capture_lines("Ghosts Ahoy", structured, sources["Ghosts Ahoy"], quest["revision"])
    assert raw == apply_capture_lines(
        "Ghosts Ahoy", structured, sources["Ghosts Ahoy"], quest["revision"]
    )
    # Robin's coin checks move up a level so they follow either opening (with or without the bow).
    assert all(fix["depth"] >= 1 for fix in structure["lines"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines(
            "Ghosts Ahoy", "\n" + structured, sources["Ghosts Ahoy"], quest["revision"]
        )
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines(
            "Ghosts Ahoy", structured, sources["Ghosts Ahoy"], quest["revision"] + 1
        )
    for name in ("Ghost guard", "Old crone"):
        page = wiki["Transcript:" + name]
        assert sources[name]["revision"] == page["revision"]
        apply_capture_lines(name, page["wikitext"], sources[name], page["revision"])

    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = exported["Ghosts Ahoy"]["variants"]
    # Velorina's vision (capture tick 265) and her completion line (1968).
    vision = json.dumps(variants["returning-to-velorina-after-talking-to-necrovarus"])
    assert "that there looms castles to the west" in vision
    assert "[player name]- I sensed" in variants["talking-to-velorina-2"][0]["text"]
    # The crone's first materials speech asks for the translation before her menu (452-453).
    milky = next(
        step for step in variants["talking-to-the-old-crone"] if step.get("id") == "pnTKEw"
    )["steps"]
    menu = next(index for index, step in enumerate(milky) if step.get("type") == "choice")
    assert milky[menu - 1]["text"].startswith("I cannot read the strange letters")
    # Robin with the bow asks for the autograph first (1227-1230); the coin checks follow either way.
    robin = variants["something-to-translate-the-book-of-haricanto-talking-to-robin"]
    assert robin[0]["text"] == "If the player has an oak longbow in their inventory:"
    assert robin[0]["steps"][0]["player"] == "Would you sign this oak longbow for me?"
    assert [step.get("text") for step in robin[2:4]] == [
        "If the player does not have 25 coins:",
        "If the player has at least 25 coins:",
    ]
    loses = next(
        step
        for step in robin[3]["steps"][0]["options"][0]["steps"]
        if step.get("text") == "If the player loses:"
    )["steps"]
    owed_nothing = loses[1]
    assert owed_nothing["text"] == "If Robin does not owe the player any coins:"
    assert owed_nothing["steps"][0]["player"] == "Well done, you beat me."
    assert [option["text"] for option in owed_nothing["steps"][2]["options"]][-1] == (
        "No, that doesn't sound fun."
    )
    # Robin's rematch options name what they repeat: every "Yes, I'll give you a game." calls the
    # game (its open and results), every "How do you play Runedraw?" the rules (ticks 1269-1390).
    branches = exported["Ghosts Ahoy"]["branches"]

    def calls(steps):
        for step in steps:
            if step.get("type") == "jump":
                yield from (call["branch"] for call in step.get("steps", []) if call.get("type") == "call")
            yield from calls(step.get("steps", []))
            for option in step.get("options", []):
                yield from ((option["text"], branch) for branch in calls(option.get("steps", [])))

    def option_calls(steps, text):
        found = []
        for step in steps:
            for option in step.get("options", []):
                if option["text"] == text:
                    found.extend(
                        call["branch"]
                        for jump in option.get("steps", [])
                        if jump.get("type") == "jump"
                        for call in jump.get("steps", [])
                    )
                found.extend(option_calls(option.get("steps", []), text))
            found.extend(option_calls(step.get("steps", []), text))
        return found

    games = option_calls(robin, "Yes, I'll give you a game.")
    rules = option_calls(robin, "How do you play Runedraw?")
    assert len(games) == 3 and len(set(games)) == 1
    assert len(rules) == 3 and len(set(rules)) == 1
    game = branches[games[0]]
    assert game[0]["player"] == "Yes, I'll give you a game."
    assert game[1]["action"] == "open_interface"
    assert [step.get("text") for step in game[2:]] == [
        "If the player wins:", "If the player loses:", "If the player wins 100 coins:",
    ]
    assert branches[rules[0]][0]["player"] == "How do you play Runedraw?"
    # A villager's refusal (1538).
    villager = json.dumps(variants["robes-of-necrovarus-talking-to-the-ghost-villagers"])
    assert "My answer is no." in villager
    # Without 2 Ectotokens the guard offers only the two captured options (106-108).
    guard = exported["Ghost guard"]["variants"]["standard-dialogue-before-or-during-ghosts-ahoy"]
    options = guard[0]["steps"][1]["options"]
    poor = [o["text"] for o in options if o.get("condition") != "If the player has at least 2 Ectotokens:"]
    assert poor == ["I don't have that many Ectotokens.", "Where can I get Ectotokens?"]
    # The farmers' thanks names Malcolm (349).
    crone = json.dumps(exported["Old crone"]["variants"])
    assert "Alice and Malcolm can communicate again." in crone
    assert "Alice and her husband" not in crone


def test_recruitment_drive_tiffy_greeting_plays_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    steps = dialogues["Recruitment Drive"]["variants"][
        "starting-out-talking-to-sir-tiffy-cashien-after-starting-the-quest"
    ]
    assert [step.get("text") for step in steps[3:5]] == [
        "Well, a top-notch adventurer like yourself is just the right sort we've"
        " been seeking for our organisation.",
        "So, are you ready to begin testing?",
    ]
    assert steps[5]["type"] == "choice"

def test_wanted_follows_the_revision_242_capture():
    # A whole revision 242 run (RSProx capture "Wanted!", 2026-11-12). Sir Amik's squire offer is one
    # menu whose entail talk returns to Yes/No (ticks 608-631); the rest is captured wording: the
    # 'Boss' hyphen (658), "deputised" (836), Tiffy's "old boy" (977), "was in the vicinity" (2550),
    # "all-clear" without a comma (2827) and the Dorgeshuun reply's hyphen (3815).
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Wanted!"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())["Transcript:Wanted!"]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Wanted!", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Wanted!", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Wanted!", "\n" + page["wikitext"], source, page["revision"])

    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Wanted!"]["variants"]
    offer = next(
        step for step in variants["falador-castle-first-visit-to-sir-amik"]
        if step.get("type") == "choice" and any(o["text"].startswith("What does being") for o in step["options"])
    )
    assert [option["text"] for option in offer["options"]] == [
        "What does being a Squire entail?", "Yes please!", "No, not right now...",
    ]
    entail = json.dumps(offer["options"][0]["steps"])
    assert "So what exactly does being a squire consist of, then?" in entail
    text = json.dumps(variants, ensure_ascii=False)
    for live in (
        "That is 'Sir Amik' or 'My Liege' - not 'Boss'.",
        "you will be deputised to act as a White Knight",
        "Well old [boy/gal/bean], we will need to equip you for the task",
        "an object that was in the vicinity rather than something he was carrying",
        "Results are all-clear [player name]. Savant out.",
        "Okay, I'm on my way - and Solus had better watch out",
    ):
        assert live in text, live
    for wiki in ("\u2013 not 'Boss'", "deputized", "Well old bean, we will", "object that as in", "all-clear, [player name]", "way \u2013 and Solus"):
        assert wiki not in text, wiki


def test_slug_menace_follows_the_revision_242_capture():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    quest_pages = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())
    npc_pages = json.loads((config.DATA_PATH / "dialogues/wiki-pages.json").read_text())
    for name, pages in (
        ("The Slug Menace", quest_pages),
        ("Witchaven villager", npc_pages),
        ("Sir Tiffy Cashien", npc_pages),
    ):
        page = pages[f"Transcript:{name}"]
        assert sources[name]["revision"] == page["revision"]
        raw = apply_capture_lines(name, page["wikitext"], sources[name], page["revision"])
        assert raw == apply_capture_lines(name, page["wikitext"], sources[name], page["revision"])
        with pytest.raises(ValueError, match="Stale dialogue capture source"):
            apply_capture_lines(name, "\n" + page["wikitext"], sources[name], page["revision"])

    exported = json.loads(
        (config.DOCS_PATH / "npc-dialogues.json").read_text(),
        object_hook=lambda node: {k: v for k, v in node.items() if k != "speaker_ids"},
    )
    variants = exported["The Slug Menace"]["variants"]
    # After the quest starts Tiffy offers his own menu, not the start prompt again (tick 241).
    start = variants["starting-off-talking-to-sir-tiffy-cashien-to-start-the-quest"]
    yes = start[2]["options"][0]["steps"][-1]["options"][0]
    assert yes["steps"][-2]["text"] == "Now, is there anything else I can do for you?"
    assert [o["text"] for o in yes["steps"][-1]["options"]] == [
        "Can you explain the Gaze of Saradomin to me?", "Can I buy some armour?",
        "Can I switch respawns, please?", "Goodbye.",
    ]
    assert "Nonsense, [old boy/my gal]," in json.dumps(yes["steps"])
    # "Something else." reaches Tiffy's standard menu (tick 271).
    started = variants["starting-off-talking-to-sir-tiffy-cashien-after-starting-the-quest"]
    other = started[2]["options"][1]
    assert other["text"] == "Something else."
    assert [o["text"] for o in other["steps"][0]["options"]] == [
        "Do you have any jobs for me yet?", "Can you explain the Gaze of Saradomin to me?",
        "Can I buy some armour?", "Can I switch respawns please?", "Goodbye.",
    ]
    # Revision 15395854 has these sections itself, so the capture no longer inserts them.
    assert sources["The Slug Menace"]["revision"] == 15395854
    inserted = json.dumps(sources["The Slug Menace"]["lines"])
    for section in ("Scanning the Mayor", "Contacting the commorb while", "Picking up the dead sea slug", "Mayor Hobb leaving"):
        assert section not in inserted, section
    assert variants["witchaven-scanning-mayor-hobb"][-1]["text"] == "Savant Out."
    contact = variants["witchaven-contacting-savant-after-talking-to-col-o-niall"]
    assert contact[0]["player"] == "So, Savant, what do you think?"
    # The Wiki names an editor's account where the capture sends the player's name.
    assert "Melee User3" not in json.dumps(exported["The Slug Menace"])
    assert contact[3]["text"] == "I really don't know at this point, [player name]."
    assert variants["the-shrine-picking-up-the-dead-sea-slug"][1]["text"] == (
        "I've detected a sea slug on you. Is everything okay?"
    )
    # The Wiki's wording, without the capture's comma (tick 2507: a recorded difference).
    assert variants["the-pages-during-the-cutscene-where-maledict-is-possessed"] == [{
        "type": "line", "speaker": "Mayor Hobb", "text": "Welcome to the family Brother Maledict",
        "presentation": "overhead",
    }]
    # Sections the Wiki still lacks.
    assert variants["witchaven-savant-asking-to-scan-the-mayor"][-1]["player"] == "Sure thing, one moment."
    assert variants["witchaven-talking-to-jeb-before-holgart-mentions-the-boat"][0]["text"] == "Hello there."
    # Jorral goes straight to the translation (tick 2099).
    assert variants["the-pages-talking-to-jorral"][0] == {"player": "Excuse me?"}
    # The glyph question plays before the transcript is added (tick 1854).
    scan = json.dumps(variants["the-shrine-scanning-commorb-near-the-door"])
    assert scan.index("So how am I supposed to show him the glyphs?") < scan.index("If the player has no inventory space")
    assert variants["the-pages-opening-hobb-s-desk"][0]["text"] == (
        "You open the locked drawer and find a page of Maledict's holy book."
    )
    assert variants["crafting-the-runes-enchanting-the-water-rune"][0]["text"] == (
        "You manage to empower the required water rune."
    )
    hobb = next(s for s in variants["witchaven-talking-to-mayor-hobb-2"] if s.get("type") == "choice")
    fish = next(o for o in hobb["options"] if o["text"] == "I'm here to fish.")
    assert fish["steps"][0] == {"player": "I'm here to fish."}
    # Every answer to "what brings you to Witchaven?" gets his reply and his questions (issue RSPSApp/tsps#6503).
    assert [o["text"] for o in hobb["options"]] == ["I'm here to relax.", "I'm just looking around.", "I'm here to fish."]
    for option in hobb["options"]:
        assert option["steps"][0] == {"player": option["text"]}
        assert option["steps"][1]["text"].startswith("That's good, yes, that's good.")
        assert "missing" not in json.dumps(option)
    villager = exported["Witchaven villager"]["variants"]
    normal = json.dumps(villager["pre-quest-dialogue"])
    possessed = json.dumps(villager["post-quest-dialogue"])
    assert "Hoorah, me boys, we're homeward bound." in normal and "pre-occupied" in normal
    assert "What is happening to the people in this town?" in normal
    assert "Can you see it?" in possessed and "She is close now... so close" in possessed


def test_nature_spirit_follows_the_revision_242_capture():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Nature Spirit"
    ]
    source = sources["Nature Spirit"]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Nature Spirit", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Nature Spirit", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Nature Spirit", "\n" + page["wikitext"], source, page["revision"])

    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Nature Spirit"]["variants"]
    # The plain wording: a coloured line's `styled` copy would count it twice.
    text = json.dumps(json.loads(json.dumps(variants), object_hook=lambda node: {k: v for k, v in node.items() if k != "styled"}))
    # Wording as live sends it (ticks 56, 553, 558, 1120, 1257).
    assert '"prompt": "Start the Nature Spirit quest?"' in text
    assert "rude or anything" in text and "rude or something" not in text
    assert "protect it as a nature spirit." in text
    assert "you can bless ~ ~ a new sickle" in text
    assert "The druid pouch makes the Ghast visible." in text
    assert text.count("~ The druid attempts to cast a spell. ~") == 3
    # The fungus talk (933-939) and Filliman's later greeting before the same menu (966), in the
    # order that keeps the greeting off the first talk once 55 is recorded.
    talk = next(step for step in variants["talking-to-filliman"] if step.get("id") == "L_2i2x")["steps"]
    assert [step["text"] for step in talk[:2]] == [
        "If the player has already shown Filliman the fungus:",
        "If the player has not shown Filliman the fungus yet:",
    ]
    assert talk[0]["steps"][0]["text"].startswith("Hello again! I don't suppose you've found out")
    assert talk[1]["steps"][2] == {"player": "Yes, I have a fungus here that I picked."}
    menu = talk[2]
    assert menu["options"][0]["steps"][0] == {"player": "What are the things that are needed again?"}
    puzzle = menu["options"][2]["steps"]
    assert puzzle[-1]["text"] == "If all the items are placed onto their respective stones:"
    assert puzzle[-1]["steps"][0]["text"].startswith("Aha, everything seems to be in place!")
    # Filliman approves each offering (1008, 1021); an unused bloom spell is the "spell scroll".
    brown = next(step for step in variants["talking-to-filliman-brown-stone"] if step.get("id") == "rjopYY")
    assert brown["steps"][1]["text"] == "Aha, yes, that seems right well done!"
    grey = variants["talking-to-filliman-grey-stone"][1]
    assert grey["text"] == "If the player uses the bloom spell scroll on the grey stone:"
    assert grey["steps"][0]["text"] == "The stone seems to absorb the spell scroll."


def test_fremennik_trials_follows_the_revision_241_242_captures():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:The Fremennik Trials"
    ]
    source = sources["The Fremennik Trials"]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("The Fremennik Trials", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("The Fremennik Trials", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("The Fremennik Trials", "\n" + page["wikitext"], source, page["revision"])

    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["The Fremennik Trials"]["variants"]
    text = json.dumps(variants)
    # Brundt greets before his first menu (local 1002236 t3093).
    start = variants["starting-off-talking-to-brundt-the-chieftain"]
    assert start[0]["text"] == "Greetings outerlander!" and start[1]["type"] == "choice"
    # Seven votes: the acceptance comes before the reminder and ends the talk (t10284-10305).
    votes = variants["the-council-members-talking-to-brundt"]
    accept = next(index for index, step in enumerate(votes) if step.get("id") == "Ve_OpV")
    remember = next(index for index, step in enumerate(votes) if str(step.get("text", "")).startswith("Remember:"))
    assert accept < remember
    assert votes[accept]["steps"][-1]["type"] == "end"
    assert votes[accept]["steps"][-2]["id"] == "3gWp4j"
    # Manni (t3266-3300) and the longhall's shout (t5812).
    assert "Ah, I see you have your keg of beer." in text and "As, I see" not in text
    assert "As you wish outerlander; I will drink first" in text
    assert "I canna drink another drop! I alsho feel veddy, veddy ill..." in text
    assert '"What was THAT?"' in text
    # Tuning (local 1001364 t2714-2728) and the Champions' Guild ballad (1002236 t5726-5738).
    assert "Doh Ray Me So." in text and "Dor Ray" not in text
    assert "Your lyre is perfectly tuned." in text and "Your lure" not in text
    for line in ("The thought of lots of questing,", "Leaves some people unfulfilled,",
                 "But I have done my simple best, in", "Entering the Champions' Guild."):
        assert line in text
    # The performance ends as live sends it (t5742-5752): messages, then Olaf's two lines.
    perform = json.dumps(variants["the-council-members-olaf-the-bard-performing-with-the-lyre"])
    order = ["Your lyre is perfectly tuned.", "Congratulations! You have completed the Bard's Trial!",
             "As you finished playing you felt Fossegrimen's power leave you...",
             "You are one of the greatest bards I have ever had the pleasure of watching performing!\"",
             "You have certainly earned my vote! I hope we can duet together soon!",
             "You feel the musical ability from the Fossegrimen leave you..."]
    assert [perform.index(line) for line in order] == sorted(perform.index(line) for line in order)
    # Koschei's overheads (t8412; local 1001646 t2331, t2440) and Thorvald after the fight (t2703-2709).
    assert "Outerlander... you made a mistake coming down here!" in text
    assert "What kind of person calls [him/her]self [player name]?" in text
    assert "Hey outerlander! Let's see what you have!" in text
    assert "The death was your own!" in text and "THAT is bravery." in text
    # The unicorn head when its disk is already taken (t3145, t3163).
    assert "It's unusual because you removed it already!" in text


@pytest.mark.parametrize(
    "name, cache",
    [
        ("Fairytale I - Growing Pains", "quest-pages.json"),
        ("Fairy Nuff", "wiki-pages.json"),
        ("Martin the Master Gardener", "wiki-pages.json"),
        ("Fairytale II - Cure a Queen", "quest-pages.json"),
    ],
)
def test_fairytale_i_capture_sources_are_pinned(name, cache):
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    page = json.loads((config.DATA_PATH / "dialogues" / cache).read_text())[f"Transcript:{name}"]
    source = sources[name]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines(name, page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines(name, page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines(name, "\n" + page["wikitext"], source, page["revision"])


def test_fairytale_i_follows_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = dialogues["Fairytale I - Growing Pains"]["variants"]
    text = json.dumps(variants)
    # Martin's "have you noticed" menu before his offer (ticks 126-133, 157-164).
    start = json.dumps(variants["starting-the-quest"])
    assert '"text": "Now that I think about it, you\'re right!"' in start
    assert "That's not very observant of you." in start and "I know I am. Depressing isn't it?" in start
    # Dreven, the fifth gardener (785, 794).
    assert "I'm an adventurer, not a weather controller!" in text
    assert "catalysts to our problems" in text
    # A gardener asked again keeps the menu (277-281).
    again = variants["talking-to-the-gardeners-if-the-player-has-already-talked-to-them"][0]
    assert again["type"] == "choice" and len(again["options"]) == 5
    assert again["options"][0]["steps"][-1]["text"] == "I've already told you everything I suspect."
    # The Godfather and Slim Louie (1335, 1340, 1358, 1364, 1374).
    assert "She is-a being cared for by-a Fairy Nuff, who lives-a just north of-a da bank." in text
    assert "while you are in Zanaris. Ciao." in text and "eet iz-a not." in text
    assert '{"player": "Right. Thanks again."}' in text
    assert variants["entering-zanaris-trying-to-talk-to-the-fairy-godfather-again"][0]["speaker"] == "Slim Louie"
    # Fairy Nuff (1459-1534).
    assert "What can I help you with then?" in text and "what can I help you with?" in text
    assert "Here, I've written down a list of her symptoms." in text and "tempus fugit" in text
    assert "Dark Wizards' tower near Falador" in text and "Dark Wizard's tower" not in text
    # Zandar (1724-1751).
    assert "she saved me from a mortal injury" in text and "more details about the Fairy Queen's condition" in text
    assert "ethereal body" in text and "ethreal" not in text and "hmmmm" not in text
    assert "Malignus{{sic}} Mortifer. Okay, thanks very much." not in text
    assert "Malignus Mortifer. Okay, thanks very much." in text
    assert "seek out a necromancer" not in text and "fungus!" not in text
    # Malignius: his menu title and the skull from the "asked again" menu (2097-2421).
    again = variants["talking-to-malignius-mortifer-talking-to-malignius-again-before-getting-the-skull"][0]
    assert again["prompt"] == "What would you like to say?"
    skull = again["options"][1]["steps"]
    assert [step.get("text") for step in skull if step.get("type") == "condition"] == [
        "If the player has brought the skull:", "If the player has not brought the skull:",
    ]
    assert skull[2]["steps"][0] == {"player": "Yes, I have it right here."}
    assert "I guess so, forgot to take notes did you? Well, listen carefully this time." in text
    assert "You will need a pair of secateurs, you will also need to gather" in text
    # The Nature Spirit's menu after the blessing (1001455 ticks 2520-2525).
    lost = variants["in-the-nature-grotto-talking-to-the-nature-spirit-after-losing-the-secateurs"]
    assert [option["text"] for option in lost[1]["options"]] == [
        "I'm afraid I've lost the secateurs you enchanted.", "No reason, really.",
    ]
    assert "You should not lie to me, my friend." in json.dumps(lost)
    # After the fight (4108, 4175).
    assert "he'd be cross if he knew you brought them to me first, but come back" in text
    assert "So did-a yous getta back" in text

    nuff = dialogues["Fairy Nuff"]["variants"]
    first = nuff["initial-dialogue-before-fairytale-part-1"]
    assert first[0] == {"npc": "Hello, can I help you at all?"}
    assert [option["text"] for option in first[1]["options"]] == [
        "What do you do around here?", "Yes, please. I need healing.", "No thanks. Just looking around.",
    ]
    healing = json.dumps(nuff["initial-dialogue-before-fairytale-part-1-subsequent-dialogue"])
    assert healing.index("11 Hitpoints.") < healing.index("That will cost you 1 diamond.")
    assert "Not too well, the Godfather" in json.dumps(nuff["after-fairytale-part-1"])

    martin = json.dumps(dialogues["Martin the Master Gardener"])
    assert "Can you tell me about your skillcape?" in martin
    ft2 = json.dumps(dialogues["Fairytale II - Cure a Queen"])
    assert "in an enchanted sleep, because" in ft2 and "enchanted deep sleep" not in ft2


@pytest.mark.parametrize(
    "name, cache",
    [("Jungle Potion", "quest-pages.json"), ("Trufitus", "wiki-pages.json")],
)
def test_jungle_potion_capture_sources_are_pinned(name, cache):
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    page = json.loads((config.DATA_PATH / "dialogues" / cache).read_text())[f"Transcript:{name}"]
    source = sources[name]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines(name, page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines(name, page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines(name, "\n" + page["wikitext"], source, page["revision"])


@pytest.mark.parametrize(
    "name, cache",
    [
        ("Shilo Village", "quest-pages.json"),
        ("Mosol Rei", "wiki-pages.json"),
        ("Yanni Salika", "wiki-pages.json"),
        ("Vigroy", "wiki-pages.json"),
    ],
)
def test_shilo_village_capture_sources_are_pinned(name, cache):
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    page = json.loads((config.DATA_PATH / "dialogues" / cache).read_text())[f"Transcript:{name}"]
    source = sources[name]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines(name, page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines(name, page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines(name, "\n" + page["wikitext"], source, page["revision"])


def test_jungle_potion_follows_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    for name, variant in (("Jungle Potion", "starting-off"), ("Trufitus", "before-jungle-potion")):
        record = dialogues[name]
        text = json.dumps({"variants": record["variants"], "branches": record.get("branches", {})})
        # Trufitus's offer and the snake weed clue (ticks 107-162).
        assert "bring it to me. I will then give you details of where to find the next herb." in text
        assert "bring to me. I will give you" not in text
        assert "It grows near vines in an area to the south west where" in text
        assert "It grows near the vines" not in text
        assert "Hmm, sounds difficult, I don't know if I am ready for the challenge." in text
        assert "Hmmm, sounds difficult" not in text
        assert variant in record["variants"]
    # His post-quest line ends at the chief's title (tick 1130).
    after = dialogues["Trufitus"]["variants"]["after-jungle-potion"]
    assert after[-1]["npc"] == "You should deliver the good news to Bwana Timfraku, Chief of Tai Bwo Wannai."


def test_fairytale_ii_follows_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = dialogues["Fairytale II - Cure a Queen"]["variants"]
    text = json.dumps(variants)
    # Martin (FairyTale2 ticks 52, 56, 76).
    assert "Yeah, sure, whatever." in text and "Yah, sure" not in text
    ready = json.dumps(variants["starting-off-talking-to-martin-after-5-minutes-have-passed"])
    assert '"prompt": "Start the Fairytale II - Cure a Queen quest?"' in ready
    # The Godfather's first menu carries the certificate as its third option (420, 431).
    menu = variants["starting-off-talking-to-the-fairy-godfather"][0]
    assert menu["type"] == "choice"
    assert [option["text"] for option in menu["options"]] == [
        "Where is the Fairy Queen?", "Where have all the fairies gone?", "Show the Godfather the Certificate!",
    ]
    assert menu["options"][2]["condition"] == "With Fairy Nuff's certificate:"
    assert len(variants["starting-off-talking-to-the-fairy-godfather"]) == 1
    assert "datta da Queen Bee" in text and "explain- a to you" in text
    # The contract scroll route (507) and the refusal's reply (487).
    assert "I'm not signing this!" in text and "I am not signing" not in text
    assert "Come and talk-a to me when yous do." in text and "me me yous do" not in text
    # The co-ordinator's certificate box and answer (637, 639).
    assert "You show the certificate to the co-ordinator." in text and "Fairy Coordinator" not in text
    assert "maybe somebody else will recognise them." in text
    # The hideout fairies before Fairy Very Wise's news (877-941), then the Wiki's seven (1016-1020).
    fairies = variants["in-the-hideout-talking-to-the-fairies"]
    assert fairies[0]["type"] == "condition" and fairies[0]["text"] == "Before Fairy Very Wise brings her news:"
    assert [option["steps"][0]["text"] for option in fairies[0]["steps"][0]["options"]] == [
        "How could everything have gone so wrong, so quickly?",
        "What is that evil fairy doing to our beautiful kingdom?",
        "The Queen is the true ruler of Zanaris, not that wicked Godfather!",
        "I hope that the Queen wakes up soon, I want to go back home.",
        "The Godfather's henchmen tried to pull off my wings!",
    ]
    assert fairies[1]["type"] == "random" and len(fairies[1]["options"]) == 7
    # Fairy Nuff's recap by the planes visited (1910-1914, 2364-2370).
    recap = variants["curing-the-queen-talking-to-fairy-nuff-after-visiting-the-cosmic-plane-and-gorak-plane"]
    assert [step.get("text") for step in recap if step.get("type") == "condition"] == [
        "After visiting the Gorak Plane but not the Cosmic Plane:", "Before visiting the Gorak Plane:",
    ]
    assert recap[3]["steps"][0] == {
        "player": "Thanks for the lecture, I've seen a Gorak, but where do I get one of these Star Flowers from?"}
    assert recap[-1] == {"player": "Yes, I'm on my way."}
    # The Queen's reward lines as live splits them (2524, 2530).
    wake = json.dumps(variants["curing-the-queen-after-using-the-magic-essence-potion-on-the-fairy-queen"])
    assert "I'm afraid you find" in wake and '"us in trying times, but please accept this magic lamp' in wake


def test_shilo_village_follows_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = dialogues["Shilo Village"]["variants"]
    text = json.dumps(variants)
    # The broken cart and the village gate before the quest (ticks 671-773, 692-710).
    cart = variants["starting-out-search-broken-cart"]
    assert cart[1]["type"] == "random" and len(cart[1]["options"]) == 2
    assert [o["text"] for o in cart[2]["options"]] == [
        "I'm climbing over the cart anyway!", "I'm climbing in anyway. Don't warn me again.",
        "Actually, I'll stay out here.",
    ]
    gate = variants["starting-out-open-metal-gate"]
    assert gate[0]["text"].startswith("The gate feels very cold to your touch!")
    assert [o["text"] for o in gate[1]["options"]] == [
        "Yes, I am fearless!", "No, actually, I have a bad feeling about this!",
    ]
    # Mosol Rei asks after the belt first (1460-1498).
    belt = variants["starting-out-talking-to-mosol-rei-after-getting-the-wampum-belt"]
    assert belt[0]["text"] == "Hey there Bwana, have you delivered that Wampum Belt to Trufitus yet?"
    assert [o["text"] for o in belt[1]["options"]] == ["Yes, of course!", "Not yet, I've been busy."]
    assert [o["text"] for o in belt[1]["options"][0]["steps"][-1]["options"]] == [
        "Ok. Thanks for your help.", "Why are the undead here?",
    ]
    # Trufitus's Talk-to with the belt, and without it (1643-1772).
    greeting = variants["starting-out-talking-to-trufitus-with-the-wampum-belt"]
    assert greeting[0] == {"player": "Greetings."}
    assert [o["text"] for o in greeting[4]["options"]] == [
        "What do you know about Rashiliyia?", "What do you know about Mosol Rei?",
        "Mosol gave me something to show you.",
    ]
    assert variants["starting-out-talking-to-trufitus-without-the-wampum-belt"][1]["text"] == (
        "I have no more news since we last spoke."
    )
    assert "Usually a strong creature of some sort will be guarding her remains." in text
    assert "Trufitus goes back to his studies." in text
    # Ah Za Rhoon (2483, 2508-2513, 2648, 2758).
    assert variants["visiting-ah-za-rhoon-search-fissure"][1]["prompt"] == "Climb into the fissure?"
    torch = json.dumps(variants["visiting-ah-za-rhoon-use-lit-torch-on-fissure"])
    assert "You drop the torch into the fissure" in torch and "Some rope might help here." in torch
    assert "You see nothing here but an empty bookcase behind some rocks." in text
    assert "The gallows look pretty eerie. You search but find nothing." in text
    # Trufitus after Ah Za Rhoon and Bervirius' tomb (3050, 3270-3272, 3804-3805).
    assert "Leave no stone unturned." in text and "We need to identify that the place" not in text
    assert "If you found anything at Ah Za Rhoon that you're not sure of" not in text
    tomb = variants["visiting-the-tomb-of-bervirius-talking-to-trufitus-after-visiting-bervirius-tomb"]
    found = tomb[2]["options"][0]["steps"]
    assert found[1]["text"].startswith("Congratulations Bwana. Show me any items")
    assert [o["text"] for o in found[2]["options"]] == [
        "I actually need help with something else.", "I didn't find anything in the tomb.",
    ]
    # Rashiliyia's tomb (3984, 4592-4594, 4612, 4837-4854, 4891-4897, 4905, 5245-5257).
    assert "The trees are already pulled apart revealing some doors." in text
    up = variants["visiting-the-tomb-of-rashiliyia-climb-rocks-back-up"]
    assert [s["text"] for s in up] == [
        "You carefully pick your way through the rocks.", "You manage to carefully clamber up.",
    ]
    third = variants["visiting-the-tomb-of-rashiliyia-using-bones-on-tomb-doors"][2]["steps"]
    assert [s["text"][:30] for s in third] == [
        "You carefully place another bo", "You place the bone into the la",
        "You fit the last bone into the", "The door seems to change sligh",
    ]
    dolmen = variants["visiting-the-tomb-of-rashiliyia-look-at-or-search-tomb-dolmen"]
    assert dolmen[2]["text"] == "Who dares disturb Rashiliyia's rest?"
    assert [s.get("text", "")[:26] for s in dolmen[-5:]] == [
        "You see something appear o", "Nazastarool: May you peris", "Nazastarool: curse is upon",
        "You hear a disembodied voi", "You see something appear o",
    ]
    assert "You find nothing new on the dolmen." in text
    assert "The Beads of the Dead start to glow" not in json.dumps(
        variants["visiting-the-tomb-of-rashiliyia-open-tomb-exit"]
    )
    rest = variants["visiting-the-tomb-of-rashiliyia-using-rashiliyias-remains-on-the-dolmen"]
    assert rest[0]["text"].startswith("You carefully place Rashiliyia's remains")
    assert rest[3]["text"] == "Without warning the spirit of Rashiliyia disappears."
    # Mosol Rei, Yanni Salika and Vigroy (5392, 5502-5535, 5695-5698).
    mosol = json.dumps(dialogues["Mosol Rei"])
    assert "Mosol leads you into the village and walks back out into the jungle." in mosol
    assert "Mosol leaves you by the gate" not in mosol
    yanni = json.dumps(dialogues["Yanni Salika"])
    assert "Yanni looks through your items..." in yanni and '{"npc": "give you a quote?"}' in yanni
    assert "Yanni won't sell you items that you've already got stored elsewhere." in yanni
    vigroy = json.dumps(dialogues["Vigroy"])
    assert "The player is transported to Brimhaven" in vigroy


def test_tree_gnome_village_capture_source_is_pinned():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    page = json.loads((config.DATA_PATH / "dialogues" / "quest-pages.json").read_text())[
        "Transcript:Tree Gnome Village"
    ]
    source = sources["Tree Gnome Village"]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Tree Gnome Village", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Tree Gnome Village", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Tree Gnome Village", "\n" + page["wikitext"], source, page["revision"])


def test_tree_gnome_village_follows_the_revision_242_capture():
    dialogues = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = dialogues["Tree Gnome Village"]["variants"]
    # Bolren's guide-out line ends with a full stop (local 1001802 tick 931).
    start = json.dumps(variants["tree-gnome-king"])
    assert "try your best to return the orb.\"" in start
    # Montai's menu lists the wood first (tick 1056).
    menu = next(step for step in variants["battlefield-commander-montai"] if step.get("type") == "choice")
    assert [option["text"] for option in menu["options"]] == [
        "Ok, I'll gather some wood.", "Sorry, I no longer want to be involved.",
    ]
    # The chest's box (tick 1567).
    chest = json.dumps(variants["into-the-stronghold-upon-opening-the-chest-containing-the-orb-of-protection"])
    assert "Inside you find the gnomes' stolen orb of protection." in chest


def test_the_corsair_curse_capture_lines_add_what_the_wiki_lacks():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["The Corsair Curse"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:The Corsair Curse"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("The Corsair Curse", page["wikitext"], source, page["revision"])
    lines = raw.splitlines()
    # Four lines the capture sends are added; the Wiki's own lines are all kept.
    assert len(lines) == len(page["wikitext"].splitlines()) + 4
    greeting = lines.index("* '''Captain Tock:''' Ahoy, young [lad/lass].")
    assert lines[greeting + 1].startswith("* '''Captain Tock:''' Ahoy, young [lad/lass]. Might ye")
    # The apology is the player's, after Tess's question, as the capture has it (ticks 5653-5655).
    tess = lines.index(
        "** '''Chief Tess:''' He skinny man who climb down vine the other day, yah? He big fool. You see what he stole?"
    )
    assert lines[tess + 1] == "** '''Player:''' Arsen says he's very sorry for stealing from you. Here it is..."
    assert "** '''Chief Tess:''' Arsen says he's very sorry" not in raw
    colin = lines.index("* '''Cabin Boy Colin:''' What?")
    assert lines[colin - 1].endswith("That was a wet ogre.")
    besides = next(i for i, line in enumerate(lines) if line.startswith("** '''Ithoi the Navigator:''' Besides,"))
    assert lines[besides + 1] == "** {{topt|Maybe because the Captain's thinking of firing you.}}"
    # The Wiki's wording stays where the capture words it differently (Tock's "good [lad/lass]").
    assert "ye've found my ship - good [lad/lass]." in raw
    assert raw == apply_capture_lines("The Corsair Curse", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("The Corsair Curse", "\n" + page["wikitext"], source, page["revision"])
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["The Corsair Curse"]
    start = exported["variants"]["the-cursed-crew-talking-to-captain-tock"]
    assert start[0]["text"] == "Ahoy, young [lad/lass]."
    assert start[2]["options"][1]["steps"][4]["prompt"] == "Start The Corsair Curse quest?"


def test_tai_bwo_wannai_trio_follows_the_captures():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Tai Bwo Wannai Trio"]
    structure = json.loads(
        (config.DATA_PATH / "dialogues" / "runtime-bindings.json").read_text(encoding="utf-8")
    )["Tai Bwo Wannai Trio"]["structure"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Tai Bwo Wannai Trio"
    ]
    assert source["revision"] == structure["revision"] == page["revision"]
    structured = update.apply_structure_annotations(
        "Tai Bwo Wannai Trio", page["wikitext"], structure, page["revision"]
    )
    raw = apply_capture_lines("Tai Bwo Wannai Trio", structured, source, page["revision"])
    assert raw == apply_capture_lines("Tai Bwo Wannai Trio", structured, source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Tai Bwo Wannai Trio", "\n" + structured, source, page["revision"])
    # Lubufu's four topics are one menu, as live shows it (local 1001562 tick 5658).
    assert "* {{topt|Talk about Karambwan...}}" in raw.splitlines()
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Tai Bwo Wannai Trio"]
    variants, branches = exported["variants"], exported["branches"]
    again = variants["talking-to-lubufu-talking-to-lubufu-again"]
    assert [option["text"] for option in again[3]["options"]] == [
        "Talk about him...", "Talk about Karambwan...", "Talk about something else...", "Leave",
    ]
    # Timfraku's first menu: "Trufitus sent me." and "Ask about Village." only once Jungle Potion is done.
    first = next(step for step in branches["jump-68ca096f234c6328"] if step.get("type") == "choice")
    assert [option["text"] for option in first["options"]] == [
        "Why should I leave?", "Right, I'm going then.", "Trufitus sent me.", "Ask about Village.",
    ]
    assert [option.get("condition") for option in first["options"]][2:] == [
        "If the player has completed Jungle Potion:", "If the player has completed Jungle Potion:",
    ]
    news = json.dumps(first["options"][2]["steps"])
    assert news.index("Then it must be true.") < news.index("Timfraku appears to concentrate very deeply.")
    again = variants["starting-off-talking-to-timfraku-again-before-jungle-potion"]
    assert again[0]["text"] == "You again! Only a fool would ignore my instructions."
    # Lubufu: the player's question, the bait offer's condition and the third ask (ticks 5624, 5705, 5855).
    assert variants["talking-to-lubufu"][1]["options"][2]["steps"][0] == {"player": "Who are you?"}
    assert "If the player has asked Lubufu what he does with his Karambwan:" in json.dumps(variants)
    delivered = json.dumps(variants["talking-to-lubufu-talking-to-lubufu-after-delivering-raw-karambwanji"])
    assert delivered.index("fewer than three times") < delivered.index("My, you're keen") < delivered.index(
        "Lubufu appears to think for a moment."
    ) < delivered.index("How would you feel about becoming my apprentice?")
    # Tiadeche: his attempt message, and his talk once he has trapped one (ticks 6234, 6700).
    assert "Tiadeche attempts to use the Karambwan vessel." in json.dumps(variants["talking-to-tiadeche-talking-to-tiadeche-again"])
    trapped = variants["talking-to-tiadeche-talking-to-tiadeche-after-he-traps-a-karambwan"]
    assert trapped[0] == {"player": "Can we return to the village now?"}
    # The Wiki's wording stays where the captures word a line differently.
    assert "Roving adventurer, please accept my eternal gratitude!" in json.dumps(exported)
    assert json.dumps(exported).count("Well, hand it here then.") >= 2


def test_zogre_flesh_eaters_capture_lines_add_what_the_wiki_lacks():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Zogre Flesh Eaters"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Zogre Flesh Eaters"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Zogre Flesh Eaters", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Zogre Flesh Eaters", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Zogre Flesh Eaters", "\n" + page["wikitext"], source, page["revision"])
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Zogre Flesh Eaters"]
    variants = exported["variants"]
    # Grish answers "What are Zogres?" with two lines (capture ticks 121-122).
    zogres = json.dumps(variants["getting-started-talking-to-grish"])
    assert zogres.index("Da Zogres are da bigun nasties") < zogres.index("Dem zogries commin from da under dirt")
    # The prism sale once Sithik has had the potion (ticks 1750-1760).
    sale = variants["investigating-b-vahn-use-the-black-prism-on-zavistic-rarve-after-giving-sithik-the-potion"]
    assert sale[0]["text"] == "You show the black prism to Zavistic."
    assert [option["text"] for option in sale[3]["options"]] == [
        "Sell it to Zavistic for 2000", "Take it to Yanni for a greater reward.",
    ]
    assert sale[3]["options"][0]["steps"][-1]["text"] == "You sell the black prism for 2000 coins."
    # Zavistic's Magic Guild option has a body (ticks 1009-1025).
    evidence = json.dumps(variants["investigating-b-vahn-talking-to-zavistic-rarve-after-gathering-evidence"])
    assert "Sure, go ahead, ask away." in evidence
    # Uglug Nar refuses a balm before the cure is known (ticks 765-771).
    balm = variants["defeating-the-zogres-use-relicym-s-balm-on-uglug-nar"]
    assert balm[2]["text"] == "If the player has not learned how to cure the disease:"
    assert balm[2]["steps"][-1] == {"type": "end"}
    assert balm[-1]["text"] == "You sell the potion and get 650 coins in return."


def test_cabin_fever_capture_lines_add_what_the_wiki_lacks():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Cabin Fever"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Cabin Fever"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Cabin Fever", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Cabin Fever", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Cabin Fever", "\n" + page["wikitext"], source, page["revision"])
    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Cabin Fever"]["variants"]
    # The start prompt and Bill's line after naming his ship (capture ticks 350, 428-433).
    start = json.dumps(variants["starting-the-quest"])
    assert '"prompt": "Start the Cabin Fever quest?"' in start
    assert '"text": "Yes."' in start and '"text": "No."' in start
    assert start.index("she's at the east dock.") < start.index("I'm all ready te get underway")
    assert start.index("I'm all ready te get underway") < start.index("ye'll not regret it Cap'n!")
    # The Wiki's own wording stays where the capture words a line differently.
    assert "Yes, I am a [man/woman] of my word." in start and "Yes, I keep my word." not in start
    assert "lily-like" in start
    # The four lines Bill adds once the holes are fixed (ticks 1219-1228), in live's order.
    fixed = json.dumps(variants["sort-out-the-leaks-after-all-the-holes-have-been-fixed"])
    order = [
        "Good work [lad/lass].",
        "I'd think ye was a born pirate.",
        "those cowardly dogs seem a little too scared to swing over.",
        "Why not pay them a visit and go plunder their hold?",
        "Gadzooks...",
        "Look, just go below their decks and search their hold for Plunder.",
        "Come back here and drop it in the chest in the hold.",
        "it may take a while for the stuff to reappear.",
        "Aye aye Cap'n! One plunderin' comin' right up!",
    ]
    assert [fixed.index(line) for line in order] == sorted(fixed.index(line) for line in order)


def test_the_hand_in_the_sand_follows_the_capture_where_the_wiki_markup_does_not():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["The Hand in the Sand"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:The Hand in the Sand"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("The Hand in the Sand", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("The Hand in the Sand", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("The Hand in the Sand", "\n" + page["wikitext"], source, page["revision"])
    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["The Hand in the Sand"]["variants"]
    # The start prompt (capture tick 7264).
    start = variants["talking-to-bert"][3]["options"][1]["steps"][-1]
    assert start["prompt"] == "Start The Hand in the Sand quest?"
    assert [option["text"] for option in start["options"]] == ["Yes.", "No."]
    # The bell before Zogre Flesh Eaters (ticks 7398-7474): the ringing lines, then the hand.
    zavistic = variants["talking-to-zavistic-rarve"]
    bell = zavistic[0]
    assert bell["text"] == "Speaking to Zavistic Rarve via the bell:"
    assert [branch["text"] for branch in bell["steps"]] == [
        "If the player has completed Zogre Flesh Eaters:",
        "If the player has not completed Zogre Flesh Eaters:",
    ]
    assert bell["steps"][1]["steps"][0]["text"].startswith("What are you doing ringing that bell?!")
    assert [step["text"] for step in zavistic[1:]] == [
        "Speaking to Zavistic Rarve inside the guild:",
        "If the player does not have the beer soaked hand in their inventory:",
        "If the player has the beer soaked hand in their inventory:",
    ]
    assert zavistic[-1]["steps"][0]["text"] == "You wave the hand at the wizard."
    # The player asks each question before Sandy answers (ticks 8313, 8334).
    questions = variants["the-truth-serum-talking-to-sandy-afterwards"][1]["steps"][2]["options"]
    for option in questions[:3]:
        assert option["steps"][0] == {"player": option["text"]}
    # One greeting before the runes and sand; the forgotten-items line is its condition's (ticks 8578-8593).
    runes = variants["returning-back-to-zavistic-with-the-magical-orb-talking-to-zavistic-rarve-again"]
    assert len(runes) == 1
    forgot = runes[0]["steps"][0]["options"][1]["steps"][0]
    assert forgot["text"] == "If the player doesn't have the required items:"
    assert forgot["steps"][-1] == {"type": "end"}
    assert runes[0]["steps"][1] == {"player": "I've brought what you wanted, what are you going to do?"}
    # The Wiki's own wording stays where the capture words a line differently.
    assert "You pour the serum in Sandy's coffee, the a little while later watch him drink it." in json.dumps(variants)


def test_rum_deal_capture_lines_add_what_the_wiki_lacks():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Rum Deal"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Rum Deal"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Rum Deal", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Rum Deal", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Rum Deal", "\n" + page["wikitext"], source, page["revision"])
    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Rum Deal"]["variants"]
    # The start prompt (the Pirate Pete page's, capture ticks 153 and 173).
    start = variants["setting-out-talking-to-pirate-pete"]
    menu = next(step for step in start if step.get("type") == "choice")
    assert menu["prompt"] == "Start the Rum Deal quest?"
    assert [option["text"] for option in menu["options"]] == ["Yes.", "No."]
    text = json.dumps(start)
    assert text.index("Err...Barrelor!") < text.index("Yes, the mighty, fearsome, tall, deadly, oaken, round demon Barrelor the Destroyer.")
    assert text.index("Trapped Pit of Barrelor.") < text.index("Wanna give it a shot?")
    # The meeting's three lines the Wiki lacks (ticks 388, 396, 447).
    meeting = json.dumps(variants["setting-out-meeting-captain-braindeath"])
    for line in ("When ye arrived ye took a nasty knock to the head", "Well, fer a price, at any rate.",
                 "Seems they lost their fightin' spirit after the first few days."):
        assert line in meeting
    # The stagnant water used on Braindeath (ticks 1629-1633).
    used = variants[
        "stagnant-water-talking-to-captain-braindeath-before-pouring-in-the-stagnant-in-the-hopper"
        "-using-the-bucket-of-stagnant-water-on-captain-braindeath"
    ]
    assert used[0] == {"player": "What exactly do you want me to do with this?"}
    # The sluglings line the Wiki joins is two boxes (ticks 1709-1710).
    sluglings = json.dumps(variants["sluglings-talking-to-captain-braindeath-after-using-the-water-on-the-hopper"])
    assert "super-secret ingredients!\", " in sluglings or "super-secret ingredients!\"" in sluglings
    assert "ingredients! Yer not" not in sluglings
    # The Wiki's own wording stays where the capture words a line differently.
    assert "beseiged" in meeting


def test_pirate_pete_dock_lift_continues_into_the_lift_menu():
    # The dock branch's "{{tact|continue}}" carries on into the lift menu the island branch holds
    # (runtime-bindings navigation anchor); without it the dock offer ended at "Interested?".
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Pirate Pete"]
    dock = next(step for step in exported["variants"]["standard-dialogue"]
                if step.get("type") == "condition" and "dock north of Port Phasmatys" in step.get("text", ""))
    jump = dock["steps"][-1]
    assert jump["type"] == "jump" and jump["reference"] == "continue"
    branch = exported["branches"][jump["steps"][0]["branch"]]
    menu = branch[0]
    assert menu["type"] == "choice"
    assert [option["text"] for option in menu["options"]][:2] == ["Okay!", "Not now"]


def test_candle_seller_haggled_purchase_reaches_the_coin_check():
    # Both "All right, you win, I'll buy a candle." answers end in a bare "{{tact|above}}": the sale
    # under "Yes please." (runtime-bindings navigation anchors, resumed after that line so it is not
    # said twice). Unresolved, the consumer guessed another option and no candle was sold (tsps#6698).
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())

    def purchase_jumps(nodes, found):
        for node in nodes:
            for option in node.get("options", []):
                steps = option.get("steps", [])
                if option.get("text") == "All right, you win, I'll buy a candle.":
                    found.append(steps)
                purchase_jumps(steps, found)
            purchase_jumps(node.get("steps", []), found)
        return found

    def sale(record, steps, seen=()):
        assert steps[0] == {"player": "All right, you win, I'll buy a candle."}
        jump = steps[1]
        for _ in range(3):
            assert jump["type"] == "jump" and "reference" not in jump
            branch = record["branches"][jump["steps"][0]["branch"]]
            if branch[0].get("type") != "jump":
                return branch
            jump = branch[0]
        raise AssertionError("purchase jump never reaches the sale")

    for name, variant in (
        ("Candle seller", "standard-dialogue"),
        ("Death to the Dorgeshuun", "a-tour-of-lumbridge-candle-seller"),
    ):
        record = exported[name]
        answers = purchase_jumps(record["variants"][variant], [])
        assert len(answers) == 2, name
        for steps in answers:
            branch = sale(record, steps)
            assert [step.get("text") for step in branch] == [
                "If the player does not have 1000 coins:",
                "If the player has at least 1000 coins:",
            ], name
            assert "Here you go then." in json.dumps(branch[1])


def test_murder_mystery_capture_lines_add_what_the_wiki_lacks():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )["Murder Mystery"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:Murder Mystery"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("Murder Mystery", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Murder Mystery", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Murder Mystery", "\n" + page["wikitext"], source, page["revision"])
    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Murder Mystery"]["variants"]
    # The accusation menus: the guard asks again, then the box before "Great work." (capture ticks 233-560).
    guard = json.dumps(variants["getting-started-talking-to-the-guard-after-starting-the-quest"])
    assert guard.count("Oh really? Which one?") == 6
    assert guard.count("You tell the guard who you suspect of the crime.") == 12
    assert guard.index("You tell the guard who you suspect") < guard.index("Great work.")
    # The Wiki's own Hobbes branch stays.
    assert "Hobbes the butler. The butler ALWAYS did it." in guard
    # The thread question needs the thread, except Frank's (tick 575: Bob's menu without it).
    for name in ("anna", "bob", "carol", "david", "elizabeth"):
        menu = variants[f"questioning-the-inhabitants-talking-to-{name}"][2]["options"]
        assert menu[2]["condition"] == "If the player has the criminal's thread:"
    frank = variants["questioning-the-inhabitants-talking-to-frank"]
    assert "condition" not in frank[3]["options"][2]
    # Elizabeth and Frank on the blue thread (ticks 1036, 1331-1333).
    elizabeth = json.dumps(variants["questioning-the-inhabitants-talking-to-elizabeth"])
    assert "If the criminal's thread is blue:" in elizabeth and "If the criminal's thread isn't blue:" in elizabeth
    assert elizabeth.index("Looks like Blue thread to me.") < elizabeth.index("I suppose it does. So what?")
    assert "You're not very good at this whole investigation thing are you?" in elizabeth
    assert "same colour anyway." in json.dumps(frank)
    # Gossip's three hints are one random pick (ticks 819, 826; the Wiki's own is the first).
    gossip = variants["questioning-the-inhabitants-talking-to-gossip"][2]["options"][3]["steps"]
    assert gossip[-1]["type"] == "random" and len(gossip[-1]["options"]) == 3
    assert gossip[-1]["options"][0]["steps"][0]["text"].startswith("Well, I don't know if it's related")
    # Declining the flypaper (tick 1420).
    sacks = variants["gathering-suspect-evidence-searching-the-sacks"][1]["options"][1]["steps"]
    assert sacks[0]["text"] == "You leave the paper in the sack."
    # The salesman straight to his menu once he has named the buyers (ticks 1895-1906), every option resolved.
    for variant in (
        "visiting-the-poison-salesman-talking-to-the-poison-salesman-after-learning-who-bought-the-poison",
        "visiting-the-poison-salesman-talking-to-the-poison-salesman-after-learning-who-bought-the-poison-if-the-player-also-has-progress-in-fremennik-trials",
    ):
        text = json.dumps(variants[variant])
        assert text.count('"type": "call"') == 4 and '"reference"' not in text
    # The thread box before the servants' clothes (ticks 1076, 1369).
    some = json.dumps(variants["presenting-the-evidence-talking-to-the-guard-with-some-but-not-all-evidence"])
    assert some.index("You show the guard the thread you found on the window.") < some.index(
        "All the servants dress in black"
    )
    # The Wiki's "her" stays for every murderer (the captures say "him" for a son: a recorded difference).
    hand_in = json.dumps(variants["presenting-the-evidence-talking-to-the-guard-with-all-evidence"])
    assert "hold her here" in hand_in and "hold him here" not in hand_in
    # The courtyard guard after the quest (tick 2383).
    outside = json.dumps(variants["post-quest-talking-to-the-guard-outside-the-mansion-after-the-quest"])
    assert "Seems awfully quiet up at the house" in outside
    assert "Nothing right now, we have it all under control." in outside


def test_watchtower_capture_lines_add_what_the_wiki_lacks():
    source = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    assert "Ogre guard" not in source  # the Watchtower page now has the guards' own sections
    source = source["Watchtower"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())["Transcript:Watchtower"]
    assert source["revision"] == page["revision"] == 15399934
    raw = apply_capture_lines("Watchtower", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("Watchtower", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("Watchtower", "\n" + page["wikitext"], source, page["revision"])
    variants = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Watchtower"]["variants"]
    # The wizard's fingernails branch stays in his talk (the new section moved below it).
    wizard = variants["searching-for-evidence-talking-to-the-watchtower-wizard"]
    assert [step.get("id") for step in wizard if step.get("type") == "condition"] == ["pBFHsX", "BoocKJ", "Q3Ag5X"]
    assert [step["text"] for step in variants[
        "searching-for-evidence-using-evidence-other-than-the-fingernails-on-the-watchtower-wizard"]][0] == "Let me see..."
    # The north-west guard: the player's claim before the guard asks (capture tick 2311).
    carrying = next(step for step in variants["entering-gu-tanoth-city-guard"] if step.get("id") == "7ZK2kb")
    assert carrying["steps"][0] == {"player": "I've got a proof of friendship right here!"}
    # Skavid 4, "Gor cur" / "Ar" (ticks 3083-3096), and every skavid's messages and wrong-word loop.
    skavid4 = variants["skavid-search-learning-skavid-skavid-4"]
    assert skavid4[0]["text"] == "Gor cur..."
    assert skavid4[1] == {"type": "message", "text": "The skavid is trying to communicate...", "id": skavid4[1]["id"]}
    for number in (1, 2, 3, 4):
        menu = next(step for step in variants[f"skavid-search-learning-skavid-skavid-{number}"] if step.get("type") == "choice")
        assert all(option.get("steps") for option in menu["options"]), number
        texts = json.dumps(menu)
        assert "It seems the skavid understood you." in texts and "It seems that was the wrong reply." in texts
    # The Wiki's own wording stays; the capture's "kind one" is now the Wiki's too.
    assert "Thank you, kind one." in json.dumps(variants["skavid-search-scared-skavid"])


def test_auguste_capture_lines_add_the_what_motivates_you_option():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    lines = [
        {"player": "What motivates you to do all of this?"},
        {"npc": "Well..."},
        {"npc": "What we leave behind is not as important as how we've lived."},
        {"player": "Wise words."},
        {"npc": "That's what I think, anyway."},
        {"type": "end"},
    ]
    for name, cache in (("Enlightened Journey", "quest-pages"), ("Auguste", "wiki-pages")):
        page = json.loads((config.DATA_PATH / f"dialogues/{cache}.json").read_text())[f"Transcript:{name}"]
        source = sources[name]
        assert source["revision"] == page["revision"]
        raw = apply_capture_lines(name, page["wikitext"], source, page["revision"])
        assert raw == apply_capture_lines(name, page["wikitext"], source, page["revision"])
        with pytest.raises(ValueError, match="Stale dialogue capture source"):
            apply_capture_lines(name, "\n" + page["wikitext"], source, page["revision"])
    exported = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())

    def menu(variant):
        choice = next(step for step in variant if step.get("type") == "choice")
        return {option["text"]: option for option in choice["options"]}

    def flat(steps):
        return [
            {"npc": step["text"]} if step.get("type") == "line" else step for step in steps
        ]

    # Right after the quest in Taverley (capture ticks 2146-2174, the option picked at 2170).
    options = menu(exported["Enlightened Journey"]["variants"][
        "landing-in-taverley-talking-to-auguste-again-before-he-is-replaced-with-assistant-stan"])
    assert list(options)[2:] == ["Could you tell me how to make an origami balloon?", "What motivates you?"]
    # The quest export drops the closing end, as it does for the sibling "No." option.
    assert flat(options["What motivates you?"]["steps"]) == lines[:-1]
    assert flat(options["No."]["steps"]) == [{"player": "No."}]
    # Auguste's own menus on Entrana (tick 2984): straight after the origami option in both.
    variants = exported["Auguste"]["variants"]
    initial = menu(variants["initial-dialogue-after-enlightened-journey"])
    assert list(initial)[2:4] == ["Could you tell me how to make an origami balloon?", "What motivates you?"]
    # The menu closes the variant, so its options drop the closing end (as "No." does).
    assert initial["What motivates you?"]["steps"] == lines[:-1]
    assert initial["No."]["steps"] == [{"player": "No."}]
    subsequent = menu(variants["subsequent-dialogues-after-enlightened-journey"])
    assert list(subsequent)[2:4] == list(initial)[2:4]
    (jump,) = subsequent["What motivates you?"]["steps"]
    (call,) = jump["steps"]
    assert exported["Auguste"]["branches"][call["branch"]] == lines


def test_auguste_hand_in_menu_returns_to_the_item_menu():
    # After each hand-in or refusal live shows the item menu again, minus what was handed in
    # (capture ticks 757, 765, 769, 774), not "Do you have anything for me?".
    quest = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Enlightened Journey"]

    def jumps(node):
        if isinstance(node, dict):
            if node.get("type") == "jump" and "reference" in node:
                yield node["reference"]
            for value in node.values():
                yield from jumps(value)
        elif isinstance(node, list):
            for value in node:
                yield from jumps(value)

    def hand_in(steps):
        top = next(step for step in steps if step.get("type") == "choice")
        option = next(o for o in top["options"] if o["text"] == "Yes, I want to give you some items.")
        return next(step for step in option["steps"] if step.get("type") == "choice")

    items = hand_in(quest["variants"]["preparing-for-the-expedition"])
    assert [option["text"] for option in items["options"]] == ["Dye.", "Sandbags.", "Silk.", "Bowl.", "Never mind."]
    references = list(jumps(items))
    assert references.count("other") == 12 and "previous" not in references
    # The five last-hand-in "above" jumps resolve to the basket line (see the test below).
    assert references.count("continues") == 2 and "above" not in references
    shared = [name for name, steps in quest["branches"].items() if "Here's the bowl." in json.dumps(steps)]
    assert shared
    for name in shared:
        assert list(jumps(quest["branches"][name])) == references


def test_auguste_last_hand_in_and_basket_talk_open_with_his_line():
    quest = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Enlightened Journey"]
    branches = quest["branches"]
    basket = "You just need to build the basket and I can finish the balloon! How are you getting on with the willow?"
    willow = ["I have lost my willow sapling. Can I buy a replacement?", "What do I do again?", "Fine thanks."]

    def resolve(steps):
        # Follow single-call jumps to the steps they play.
        while len(steps) == 1 and steps[0].get("type") == "jump" and steps[0].get("steps"):
            (call,) = steps[0]["steps"]
            steps = branches[call["branch"]]
        return steps

    def conditions(node):
        if isinstance(node, dict):
            if node.get("type") == "condition" and node.get("text") == "If all the materials are finally handed in:":
                yield node
            for value in node.values():
                yield from conditions(value)
        elif isinstance(node, list):
            for value in node:
                yield from conditions(value)

    # The last material handed in (capture ticks 850-857, the sandbags last): "That's the last
    # of it!", the basket line, then the willow menu, in every material's branch.
    found = list(conditions(quest["variants"]["preparing-for-the-expedition"]))
    assert len(found) == 6
    for condition in found:
        first, *rest = condition["steps"]
        assert (first["speaker"], first["text"]) == ("Auguste", "That's the last of it!")
        rest = resolve(rest)
        assert rest[0]["text"] == basket
        assert [option["text"] for option in rest[1]["options"]] == willow
        again = resolve(next(o for o in rest[1]["options"] if o["text"] == "What do I do again?")["steps"])
        assert again[0] == {"player": "What do I do again?"}  # ticks 882 and 1443
    # Talks after all the materials, before planting (ticks 869, 889, 973, 1436, 1448).
    talk = quest["variants"][
        "preparing-for-the-expedition-talking-to-him-before-planting-his-sapling-but-after-delivering-all-the-required-materials"]
    assert (talk[0]["speaker"], talk[0]["text"]) == ("Auguste", basket)
    assert [option["text"] for option in talk[1]["options"]] == willow
    # Every willow menu's "What do I do again?" plays the player's line first, then Auguste's.
    for name in ("preparing-for-the-expedition-talking-to-him-before-planting-his-sapling-but-after-delivering-all-the-required-materials",
                 "preparing-for-the-expedition-talking-to-him-after-planting-his-sapling-and-handing-in-all-the-ingredients"):
        menu = next(step for step in quest["variants"][name] if step.get("type") == "choice")
        again = resolve(next(o for o in menu["options"] if o["text"] == "What do I do again?")["steps"])
        assert again[0] == {"player": "What do I do again?"}, name
        assert again[1]["text"].startswith("Use the willow sapling I gave you"), name
    # The item-help branch has no such line.
    trouble = next(o for o in next(step for step in quest["variants"]["preparing-for-the-expedition"] if step.get("type") == "choice")["options"]
                   if o["text"] == "I'm having some trouble finding some of the items.")
    assert trouble["steps"][0] == {"player": "I'm having some trouble finding some of the items."}
    assert "What do I do again?" not in json.dumps(trouble)


def test_auguste_replace_items_option_holds_every_reclaim_condition():
    bindings = json.loads((config.DATA_PATH / "dialogues/runtime-bindings.json").read_text(encoding="utf-8"))
    page = json.loads((config.DATA_PATH / "dialogues/wiki-pages.json").read_text())["Transcript:Auguste"]
    structure = bindings["Auguste"]["structure"]
    assert structure["revision"] == page["revision"]
    # The Wiki writes the cap's first line at depth 1 under its depth-2 condition (line 59).
    structured = update.apply_structure_annotations("Auguste", page["wikitext"], structure, page["revision"])
    assert structured.splitlines()[58] == "*** '''Auguste:''' You still seem to have your cap."
    with pytest.raises(ValueError, match="Stale dialogue structure annotation"):
        update.apply_structure_annotations("Auguste", "\n" + page["wikitext"], structure, page["revision"])
    auguste = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())["Auguste"]
    initial = auguste["variants"]["initial-dialogue-after-enlightened-journey"]
    # One menu, nothing left hanging after it.
    assert initial[-1]["type"] == "choice" and [step.get("type") for step in initial].count("choice") == 1
    options = {option["text"]: option for option in initial[-1]["options"]}
    assert list(options)[-2:] == ["Could you replace some items for me?", "Could you combine my cap and goggles?"]
    replace = options["Could you replace some items for me?"]["steps"]
    assert [(step["type"], step["text"], step["steps"][0]["npc"]) for step in replace] == [
        ("condition", "If the bomber cap has not been lost:", "You still seem to have your cap."),
        ("condition", "If the bomber cap has been lost but there is no free inventory space:",
         "You don't have enough free space for your cap."),
        ("condition", "If the bomber cap has been lost:", "Here's your cap. Try to keep better track of it."),
        ("condition", "If the bomber jacket has not been lost:",
         "You don't need a new jacket; you still have your original one."),
        ("condition", "If the bomber jacket has been lost but there is no free inventory space:",
         "You don't have enough free space for your jacket."),
        ("condition", "If the bomber jacket has been lost:", "Here's your jacket, to keep you warm during flight."),
    ]
    assert replace[0]["id"] == "bOybQz"
    assert [step["steps"][1].get("reference", step["steps"][1]["type"]) for step in replace] == [
        "continues", "continues", "continues", "continues", "end", "continues"]
    # The subsequent menu's "same as above" plays the same six conditions.
    subsequent = auguste["variants"]["subsequent-dialogues-after-enlightened-journey"][-1]["options"]
    (jump,) = next(o for o in subsequent if o["text"] == "Could you replace some items for me?")["steps"]
    (call,) = jump["steps"]
    assert [step["text"] for step in auguste["branches"][call["branch"]]] == [step["text"] for step in replace]


def test_gertrudes_cat_follows_the_revision_242_capture():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    corrections = json.loads(
        (config.DATA_PATH / "dialogues" / "corrections.json").read_text(encoding="utf-8")
    )
    for name, cache, title in (
        ("Gertrude's Cat", "quest-pages", "Transcript:Gertrude's Cat"),
        ("Gertrude", "wiki-pages", "Transcript:Gertrude"),
    ):
        # Source inputs over the cached revision, not edits of the generated record.
        assert name not in corrections
        source = sources[name]
        page = json.loads((config.DATA_PATH / f"dialogues/{cache}.json").read_text())[title]
        assert source["revision"] == page["revision"]
        lines = page["wikitext"].splitlines()
        for fix in source["lines"]:
            assert hashlib.sha256(lines[fix["line"] - 1].encode()).hexdigest() == fix["sha256"]
        raw = apply_capture_lines(name, page["wikitext"], source, page["revision"])
        assert raw == apply_capture_lines(name, page["wikitext"], source, page["revision"])
        with pytest.raises(ValueError, match="Stale dialogue capture source"):
            apply_capture_lines(name, page["wikitext"], source, page["revision"] + 1)

    records = json.loads(
        (config.DOCS_PATH / "npc-dialogues.json").read_text(),
        object_hook=lambda node: {k: v for k, v in node.items() if k not in ("speaker_ids", "id")},
    )
    variants = records["Gertrude's Cat"]["variants"]
    words = lambda steps: [step.get("player") or f"{step.get('speaker', step.get('type'))}: {step.get('text')}" for step in steps]
    # The quest starts as the player agrees, before Gertrude's thanks (tick 63).
    agree = variants["starting-off"][7]["options"][0]["steps"]
    assert agree[0] == {"player": "Well, I suppose I could."}
    assert agree[1]["hook"] == "quest:gertrude-s-cat:start"
    # Clicking Shilop: he alone asks for and refuses the coins (ticks 148-240).
    shilop = variants["talking-to-shilop-and-wilough"]
    assert words(shilop[:6])[1] == "Shilop: I didn't mean to take it! I just forgot to pay."
    pay = shilop[6]["options"][1]["steps"]
    assert words(pay)[3:6] == ["Shilop: 100 coins should cover it.", "100 coins! Why should I pay you?",
        "Shilop: You shouldn't, but I won't help otherwise. I never liked that cat anyway, so what do you say?"]
    # Paying Shilop: he gives both directions, "I play at", and the player's "Fluffs ?" (recording 1001963, ticks 9151-9178).
    assert words(pay[-1]["options"][1]["steps"])[1:] == ["action: You give the lad 100 coins.",
        "There you go, now where did you see Fluffs ?",
        "Shilop: I play at an abandoned lumber mill to the north east. Just beyond the Jolly Boar Inn. I saw Fluffs running around in there.",
        "Anything else?", "Shilop: Well, you'll have to find the broken fence to get in. I'm sure you can manage that."]
    # Clicking Wilough: Shilop chips in, Wilough defends him, no apostrophe in the menu (ticks 173-274).
    wilough = variants["talking-to-shilop-and-wilough-talking-to-wilough"]
    assert words(wilough)[3] == "Shilop: I might be able to help. Fluffs followed me to our secret play area and I haven't seen her since."
    menu = wilough[6]["options"]
    assert [option["text"] for option in menu][2] == "Well never mind, it's Fluffs loss."
    assert words(menu[0]["steps"])[1:] == ["Shilop: W..wh..what?! Y..you wouldn't! A young lad like me!",
        "Wilough: If you want to hurt my brother you'll first have to get by me!",
        "message: You decide it's best not to hurt the boy."]
    paid = menu[1]["steps"][-1]["options"][1]["steps"]
    assert words(paid)[1:] == ["action: You give the lad 100 coins.", "There you go, now where did you see Fluffs?",
        "Shilop: We play at an abandoned lumber mill to the north east. Just beyond the Jolly Boar Inn. I saw Fluffs running around in there.",
        "Anything else?", "Wilough: Well, you'll have to find the broken fence to get in. I'm sure you can manage that."]
    assert words(variants["talking-to-shilop-and-wilough-talking-to-wilough-again"])[1].startswith("Wilough: Weren't you listening?")
    assert words(variants["talking-to-shilop-and-wilough-talking-to-them-again"])[1].startswith("Shilop: Weren't you listening?")
    assert words(variants["finding-fluffs-talking-to-wilough-again"])[1:5] == ["Wilough: You think you're tough do you?",
        "Pardon?", "Wilough: I can beat anyone up!", "Shilop: He can you know!"]
    # Message boxes, as live shows them.
    assert variants["finding-fluffs-pick-up-fluffs"][-1] == {"type": "message", "text": "Maybe the cat is thirsty?"}
    assert variants["making-seasoned-sardines-returning-the-kitten-to-fluffs"][-1] == {
        "type": "message", "text": "Fluffs has run off home with her offspring."}
    finish = words(variants["finishing-up"])
    assert "message: Gertrude gives you a hug." in finish and "message: Gertrude gives you a kitten." in finish
    assert "action: ... and some food!" in finish
    assert variants["after-the-quest-pick-up-fluffs"] == [{"player": "Oh, it looks like Fluffs has returned. I'd better leave her alone."}]
    # Gertrude refuses another kitten while one is still being raised (ticks 883-884).
    kittens = records["Gertrude"]["variants"]["standard-dialogue-on-pay-to-play-worlds"][4]["options"][0]["steps"]
    assert kittens[1]["type"] == "condition" and kittens[1]["text"] == "While already owning a kitten:"
    assert kittens[1]["steps"][0]["npc"].startswith("Aren't you still raising that other kitten?")


def test_the_golem_capture_lines_and_the_curators_fossil_island_menu():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    source = sources["The Golem"]
    page = json.loads((config.DATA_PATH / "dialogues/quest-pages.json").read_text())[
        "Transcript:The Golem"
    ]
    assert source["revision"] == page["revision"]
    raw = apply_capture_lines("The Golem", page["wikitext"], source, page["revision"])
    assert raw == apply_capture_lines("The Golem", page["wikitext"], source, page["revision"])
    with pytest.raises(ValueError, match="Stale dialogue capture source"):
        apply_capture_lines("The Golem", "\n" + page["wikitext"], source, page["revision"])
    records = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    variants = records["The Golem"]["variants"]
    # The start prompt (capture tick 26).
    start = variants["talking-to-the-golem-to-start-the-quest"]
    menu = next(step for step in start if step.get("type") == "choice")
    assert menu["prompt"] == "Start The Golem quest?"
    assert [option["text"] for option in menu["options"]] == ["Yes.", "No."]
    # Elissa's first two menus end with "Sorry, I need to go." (ticks 340, 369, 380, 382).
    for name in (
        "talking-to-elissa-in-the-digsite",
        "talking-to-elissa-in-the-digsite-talking-to-elissa-again-after-learning-where-the-notes-are",
    ):
        options = next(step for step in variants[name] if step.get("type") == "choice")["options"]
        assert options[-1] == {"text": "Sorry, I need to go.", "steps": [{"player": "Sorry, I need to go."}]}
    letter = json.dumps(variants["talking-to-elissa-in-the-digsite"])
    assert "I wrote that letter to my late husband" in letter and "AI wrote" not in letter
    assert "That was a great city as well" in letter
    # The curator's Fossil Island option borrows his page's body and condition (tick 558-568).
    for name in (
        "visiting-the-varrock-museum-talking-to-curator-haig-in-the-varrock-museum",
        "visiting-the-varrock-museum-talking-to-curator-haig-after-losing-the-statuette",
    ):
        options = next(step for step in variants[name] if step.get("type") == "choice")["options"]
        fossil = options[0]
        assert fossil["text"] == "Talk about Fossil Island."
        assert fossil["condition"] == "After Bone Voyage:"
        assert fossil["steps"][0] == {"player": "I've got some questions regarding Fossil Island."}
        sub = next(step for step in fossil["steps"] if step.get("type") == "choice")
        assert [option["text"] for option in sub["options"]] == [
            "What can I do with fossils I find on Fossil Island?",
            "Nevermind.",
        ]
    # The curator's own page: the Fossil Island sub-menu is under its option, not the main menu.
    bindings = json.loads(
        (config.DATA_PATH / "dialogues" / "runtime-bindings.json").read_text(encoding="utf-8")
    )
    curator_page = json.loads((config.DATA_PATH / "dialogues/wiki-pages.json").read_text())[
        "Transcript:Curator Haig Halen"
    ]
    structure = bindings["Curator Haig Halen"]["structure"]
    assert structure["revision"] == curator_page["revision"]
    standard = records["Curator Haig Halen"]["variants"]["standard-dialogue"]
    main = next(step for step in standard if step.get("type") == "choice")["options"]
    assert [option["text"] for option in main][:2] == [
        "Talk about Fossil Island.",
        "I found a strange relic while salvaging...",
    ]
    # The Wiki's own wording stays where the capture words a line differently.
    assert "Damage... severe... Task... incomplete..." in json.dumps(start)


def test_creature_of_fenkenstrain_follows_the_revision_243_capture():
    sources = json.loads(
        (config.DATA_PATH / "dialogues" / "capture-sources.json").read_text(encoding="utf-8")
    )
    corrections = json.loads(
        (config.DATA_PATH / "dialogues" / "corrections.json").read_text(encoding="utf-8")
    )
    for name, cache, title in (
        ("Creature of Fenkenstrain", "quest-pages", "Transcript:Creature of Fenkenstrain"),
        ("Gardener Ghost", "wiki-pages", "Transcript:Gardener Ghost"),
        ("Lord Rologarth", "wiki-pages", "Transcript:Lord Rologarth"),
    ):
        # Source inputs over the cached revision, not edits of the generated record.
        assert name not in corrections
        source = sources[name]
        page = json.loads((config.DATA_PATH / f"dialogues/{cache}.json").read_text())[title]
        assert source["revision"] == page["revision"]
        lines = page["wikitext"].splitlines()
        for fix in source["lines"]:
            assert hashlib.sha256(lines[fix["line"] - 1].encode()).hexdigest() == fix["sha256"]
        raw = apply_capture_lines(name, page["wikitext"], source, page["revision"])
        assert raw == apply_capture_lines(name, page["wikitext"], source, page["revision"])
        with pytest.raises(ValueError, match="Stale dialogue capture source"):
            apply_capture_lines(name, page["wikitext"], source, page["revision"] + 1)

    records = json.loads(
        (config.DOCS_PATH / "npc-dialogues.json").read_text(),
        object_hook=lambda node: {k: v for k, v in node.items() if k not in ("speaker_ids", "id")},
    )
    variants = records["Creature of Fenkenstrain"]["variants"]
    branches = records["Creature of Fenkenstrain"]["branches"]
    words = lambda steps: [step.get("player") or f"{step.get('speaker', step.get('type'))}: {step.get('text')}" for step in steps]

    def flat(steps):
        out = []
        for step in steps:
            if step.get("type") == "call":
                out.extend(flat(branches[step["branch"]]))
            else:
                out.append(step)
        return out

    # The interview: "What job?" is the third option and the later menus have no full stops (ticks 321-371).
    interview = variants["dr-fenkenstrain-talking-to-dr-fenkenstrain"]
    menu = interview[1]["options"]
    assert [option["text"] for option in menu] == ["Yes.", "No.", "What job?"]
    assert words(menu[2]["steps"])[:5] == ["What job do you mean, sir?",
        "Dr Fenkenstrain: Oh, doesn't anybody read signposts anymore???", "What signpost?",
        "Dr Fenkenstrain: The signpost in the middle of the village nearby! Oh never mind.",
        "Dr Fenkenstrain: I need a new butler. Would you like to apply?"]
    one_word = menu[0]["steps"][4]["options"]
    assert [option["text"] for option in one_word] == ["Stunning", "Awe-inspiring", "Breathtaking", "Braindead"]
    assert [option["text"] for option in one_word[3]["steps"][2]["options"]] == ["Combat", "Magic", "Cooking", "Grave-digging"]
    # The gardener: the option's own words, once (ticks 552-604).
    gardener = variants["decapitated-head-talking-to-the-gardener-ghost"][0]["options"]
    assert [option["steps"][0]["player"] for option in gardener] == [
        "Can you tell me anything about Fenkenstrain?", "What happened to your head?", "What's your name?"]
    # Every part carried, arms first, then "Oh bother!" (ticks 1390-1400).
    parts = variants["talking-to-dr-fenkenstrain-with-the-body-parts"][0]["options"][0]["steps"]
    conditions = [step for step in parts if step.get("type") == "condition"]
    assert [step["text"] for step in conditions][:4] == ["If the player has the arms:", "If the player has the legs:",
        "If the player has the torso:", "If the player has the decapitated head with the brain:"]
    assert all(step["steps"][-1].get("type") != "end" for step in conditions[:4])
    assert "Dr Fenkenstrain: Oh bother! I haven't got a needle or thread!" in words(conditions[4]["steps"])
    # No Wiki editor's name; the second talk after the conductor (ticks 1863, 1894-1896).
    after = words(variants["talking-to-dr-fenkenstrain-after-using-the-conductor"])
    assert after[1] == "Dr Fenkenstrain: Yes, I'm afraid it did, [player name] - all too well."
    assert words(variants["talking-to-dr-fenkenstrain-after-using-the-conductor-talking-to-dr-fenkenstrain-again"]) == [
        "Dr Fenkenstrain: So have you destroyed it?!!?", "Not yet.", "Dr Fenkenstrain: Please, hurry - save me!!!!"]
    rologarth = records["Lord Rologarth"]["variants"]["after-creature-of-fenkenstrain"]
    assert words(rologarth)[2].startswith("Rologarth: I saw him climb up into the Tower to hide. It doesn't")
    ghost = json.dumps(records["Gardener Ghost"]["variants"]["after-creature-of-fenkenstrain"])
    assert "just gettin' on with it regardless" in ghost and "Good for you ... err ... mate." in ghost
