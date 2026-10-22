import json

import config
from scripts.dialogues import fetch as fetch_module
from scripts.dialogues import update
from scripts.dialogues.hooks import enrich_records


def test_fetch_discovers_miniquest_transcript_category(monkeypatch):
    queried = []
    downloaded = []

    class FakeTitles:
        def __init__(self, api, categories):
            self.category = categories[0]
            queried.append(self.category)

        def extract_page_titles(self):
            pass

        def __iter__(self):
            titles = {
                "NPC dialogue": ["Transcript:Bob"],
                "Quest transcript": ["Transcript:Quest"],
                "Miniquest transcript": ["Transcript:His Faithful Servants"],
            }
            return iter(titles[self.category])

    class FakeText:
        def __init__(self, api, prefix):
            self.session = object()

    def fake_download(names, path, session, refresh=False, with_categories=False):
        downloaded.append((set(names), path))
        return {name: {"wikitext": ""} for name in names}

    monkeypatch.setattr(fetch_module, "WikiPageTitles", FakeTitles)
    monkeypatch.setattr(fetch_module, "WikiPageText", FakeText)
    monkeypatch.setattr(fetch_module, "download", fake_download)
    monkeypatch.setattr(fetch_module, "save", lambda *args, **kwargs: None)

    fetch_module.fetch()

    assert "Miniquest transcript" in queried
    assert any(
        "Transcript:His Faithful Servants" in names and path == fetch_module.QUEST_CACHE
        for names, path in downloaded
    )


CLAIM_LATER = "giving-the-strange-icon-if-the-player-claims-the-lamp-or-map-later"


def test_inline_anchor_prefixes_real_npc_speech():
    node = update.parse_step(
        "{{anchor|given-the-icon}}'''Strange Old Man:''' You did it!", [], 1
    )
    assert node == {
        "type": "line",
        "speaker": "Strange Old Man",
        "text": "You did it!",
        "_anchors": ["given-the-icon"],
    }


def test_trailing_verified_navbox_is_ignored():
    nav = update.parse_npc(
        "His Faithful Servants",
        "==Standard dialogue==\n* '''Strange Old Man:''' Hi.\n"
        "{{His Faithful Servants}}",
    )
    assert not any(
        node.get("type") == "unparsed"
        for node in nav["variants"]["standard-dialogue"]["steps"]
    )


def test_page_named_nonnavigation_template_stays_unavailable():
    nonnav = update.parse_npc(
        "Bob", "==Standard dialogue==\n* '''Bob:''' Hi.\n{{Bob}}"
    )
    assert nonnav["variants"]["standard-dialogue"]["steps"][-1] == {
        "type": "unparsed",
        "raw": "{{Bob}}",
    }


def test_bulleted_or_parameterized_nav_lookalike_is_not_discarded():
    for footer in ("* {{His Faithful Servants}}", "{{His Faithful Servants|x}}"):
        parsed = update.parse_npc(
            "His Faithful Servants",
            "==Standard dialogue==\n* '''Strange Old Man:''' Hi.\n" + footer,
        )
        assert parsed["variants"]["standard-dialogue"]["steps"][-1]["type"] == (
            "unparsed"
        ), footer


def test_unknown_template_stays_unavailable():
    unknown = update.parse_npc(
        "Bob", "==Standard dialogue==\n* '''Bob:''' Hi.\n{{Mystery}}"
    )
    assert unknown["variants"]["standard-dialogue"]["steps"][-1] == {
        "type": "unparsed",
        "raw": "{{Mystery}}",
    }


def test_duplicate_anchor_target_leaves_the_jump_unresolved():
    raw = (
        "==First==\n"
        "* {{anchor|duplicate}}'''Bob:''' One.\n"
        "* {{anchor|duplicate}}'''Bob:''' Two.\n"
        "==Second==\n"
        "* {{tact|above|duplicate}}\n"
    )
    record = update.gameplay_npc("Bob", update.parse_npc("Bob", raw))
    enrich_records({"Bob": record}, {}, {}, update.clean)
    jump = record["variants"]["second"][0]
    assert jump["type"] == "jump"
    assert jump["reference"] == "above"
    assert "steps" not in jump



def test_cached_full_hfs_page_parses_claim_later_reclaim_nodes():
    pages = json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text()
    )
    page = pages["Transcript:His Faithful Servants"]
    assert "==Giving the strange icon==" in page["wikitext"]
    assert "===If the player claims the lamp or map later===" in page["wikitext"]

    record = update.gameplay_npc(
        "His Faithful Servants",
        update.parse_npc("His Faithful Servants", page["wikitext"]),
    )
    assert record["default"] == "starting-out-talking-to-the-strange-old-man"
    claims = [key for key in record["variants"] if key.endswith(CLAIM_LATER)]
    assert claims == [CLAIM_LATER]

    steps = record["variants"][CLAIM_LATER]
    assert steps[:6] == [
        {
            "type": "line",
            "speaker": "Strange Old Man",
            "text": "This is for you. Take it! Take it!",
        },
        {
            "type": "condition",
            "text": "If the player has not claimed the lamp nor the map:",
            "steps": [
                {
                    "type": "message",
                    "text": "The Strange Old Man has given you a lamp and a map.",
                },
                {"type": "jump", "reference": "continues"},
            ],
        },
        {
            "type": "condition",
            "text": "If the player has not claimed the lamp:",
            "steps": [
                {
                    "type": "message",
                    "text": "The Strange Old Man has given you a lamp.",
                },
                {"type": "jump", "reference": "continues"},
            ],
        },
        {
            "type": "condition",
            "text": "If the player has not claimed the map:",
            "steps": [
                {
                    "type": "message",
                    "text": "The Strange Old Man has given you a map.",
                },
                {"type": "jump", "reference": "continues"},
            ],
        },
        {"player": "Thanks."},
        {
            "type": "choice",
            "options": [
                {
                    "text": "Can you tell me more about the brothers?",
                    "steps": [{"type": "jump", "reference": "above"}],
                },
                {
                    "text": "I wanted to ask you about warnings.",
                    "steps": [{"type": "jump", "reference": "above"}],
                },
                {
                    "text": "I'll leave you to it then...",
                    "steps": [
                        {"player": "I'll leave you to it then..."},
                        {"type": "end"},
                    ],
                },
            ],
        },
    ]


def hfs_source_record():
    pages = json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text()
    )
    record = update.gameplay_npc(
        "His Faithful Servants",
        update.parse_npc(
            "His Faithful Servants", pages["Transcript:His Faithful Servants"]["wikitext"]
        ),
    )
    enrich_records({}, {"His Faithful Servants": record}, {}, update.clean)
    return record


def test_hfs_above_anchor_branches_resume_the_anchored_line_and_reward():
    record = hfs_source_record()
    reward = "The Strange Old Man gives you a lamp and a map."
    for variant, expected in [
        (
            "giving-the-strange-icon-if-the-player-gives-the-strange-old-man-the-icon",
            "You did it! Now for me.",
        ),
        (
            "giving-the-strange-icon-if-the-strange-old-man-destroyed-the-icon",
            "Yes! Needed it for him, but not to keep! His friend asked him to protect it, "
            "but he made a new plan, a better plan!",
        ),
    ]:
        jump = next(
            node
            for node in record["variants"][variant]
            if node.get("type") == "jump"
        )
        branch = record["branches"][jump["steps"][0]["branch"]]
        assert branch[0].get("text") == expected, variant
        messages = [
            node.get("text") for node in branch if node.get("type") == "message"
        ]
        assert messages.count(reward) == 1, variant


def test_generated_hfs_record_has_no_unavailable_placeholders():
    record = hfs_source_record()

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get("steps", []))
            yield from walk(node.get("options", []))
            if node.get("type") == "call":
                yield from walk(record["branches"][node["branch"]])

    assert not any(
        node.get("type") == "unavailable"
        for steps in [
            *record["variants"].values(),
            *record.get("branches", {}).values(),
        ]
        for node in walk(steps)
    )


def test_generated_hfs_record_selects_one_claim_later_variant():
    data = json.loads((config.DOCS_PATH / "npc-dialogues.json").read_text())
    record = data["His Faithful Servants"]
    assert record["default"] == "starting-out-talking-to-the-strange-old-man"
    assert [key for key in record["variants"] if key.endswith(CLAIM_LATER)] == [
        CLAIM_LATER
    ]

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get("steps", []))
            yield from walk(node.get("options", []))

    messages = [
        node.get("text")
        for node in walk(record["variants"][CLAIM_LATER])
        if node.get("type") == "message"
    ]
    assert messages == [
        "The Strange Old Man has given you a lamp and a map.",
        "The Strange Old Man has given you a lamp.",
        "The Strange Old Man has given you a map.",
    ]
