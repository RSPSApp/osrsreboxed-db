import json
import copy

import pytest

import config
from scripts.dialogues import update
from scripts.dialogues.hooks import annotate, enrich_records, walk
from scripts.dialogues.bindings import apply_bindings


def record(name, raw):
    value = update.gameplay_npc(name, update.parse_npc(name, raw))
    value["source"] = {"page": "Transcript:" + name, "revision": 1}
    return value


def follow(record, steps, visiting=frozenset()):
    result = []
    for node in steps:
        if node.get("type") == "call" and node["branch"] not in visiting:
            result.extend(
                follow(
                    record,
                    record["branches"][node["branch"]],
                    visiting | {node["branch"]},
                )
            )
        elif node.get("type") == "jump" and node.get("steps"):
            result.extend(follow(record, node["steps"], visiting))
        else:
            result.append(node)
    return result


def test_nested_menu_does_not_swallow_outer_options_or_drop_same_depth_speech():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect}}
* {{topt|Outer}}
** {{tselect}}
*** {{topt|Inner}}
*** '''X:''' Inner reply.
*** {{topt|Another inner}}
**** {{tact|end}}
* {{topt|Another outer}}
** '''X:''' Outer reply.
""",
    )
    menu = value["variants"]["standard-dialogue"][0]
    assert [option["text"] for option in menu["options"]] == ["Outer", "Another outer"]
    inner = menu["options"][0]["steps"][0]
    assert [option["text"] for option in inner["options"]] == ["Inner", "Another inner"]
    assert inner["options"][0]["steps"] == [{"npc": "Inner reply."}]


def test_same_depth_option_bodies_stay_with_their_choice_until_the_next_option():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect|Select an option}}
* {{topt|Wrong}}
* {{tact|A random incorrect dialogue from below is shown.}}
* {{tact|end}}
* {{topt|Right}}
* '''Player:''' Right.
* '''X:''' Continue the conversation.
* {{tselect}}
* {{topt|Continue}}
** '''X:''' Nested answer.
""",
    )
    menu = value["variants"]["standard-dialogue"][0]
    assert [option["text"] for option in menu["options"]] == ["Wrong", "Right"]
    assert [step["type"] for step in menu["options"][0]["steps"]] == ["action", "end"]
    right_steps = menu["options"][1]["steps"]
    assert right_steps[0] == {"player": "Right."}
    assert right_steps[1] == {"npc": "Continue the conversation."}
    assert value["variants"]["standard-dialogue"][1]["type"] == "choice"
    assert value["variants"]["standard-dialogue"][1]["options"][0]["steps"][0] == {"npc": "Nested answer."}


def test_matching_player_echo_does_not_swallow_the_next_parent_option():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect|Select an option}}
* {{topt|Yes}}
* '''Player:''' Yes.
* '''X:''' The answer is yes.
* {{topt|No}}
* '''Player:''' No.
* '''X:''' The answer is no.
* {{tact|end}}
""",
    )
    menu = value["variants"]["standard-dialogue"][0]
    assert [option["text"] for option in menu["options"]] == ["Yes", "No"]
    assert menu["options"][0]["steps"] == [{"player": "Yes."}, {"npc": "The answer is yes."}]
    assert menu["options"][1]["steps"] == [{"player": "No."}, {"npc": "The answer is no."}, {"type": "end"}]


def test_unrelated_outer_menu_after_completed_menu_stays_a_sibling():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect|First question}}
* {{topt|Yes}}
** '''Player:''' Yes.
** '''X:''' First answer.
* {{topt|No}}
** '''Player:''' No.
** '''X:''' Second answer.
* {{tselect|A separate question}}
* {{topt|Continue}}
** '''X:''' New conversation.
""",
    )
    steps = value["variants"]["standard-dialogue"]
    assert steps[0]["type"] == "choice"
    assert [option["text"] for option in steps[0]["options"]] == ["Yes", "No"]
    assert steps[1]["type"] == "choice"
    assert steps[1]["prompt"] == "A separate question"


def test_making_history_dron_quiz_options_are_grouped_from_canonical_wiki_source():
    pages = json.loads((config.DATA_PATH / "dialogues" / "quest-pages.json").read_text())
    raw = pages["Transcript:Making History"]["wikitext"]
    parsed = update.parse_npc("Making History", raw)
    steps = parsed["variants"]["talking-to-dron-talking-to-dron-again"]["steps"]

    def find_prompt(nodes):
        for node in nodes:
            if node.get("type") == "line" and node.get("text") == "When are kittens best devoured?":
                return nodes, node
            found = find_prompt(node.get("steps", []))
            if found:
                return found
            for option in node.get("options", []):
                found = find_prompt(option.get("steps", []))
                if found:
                    return found
        return None

    siblings, _ = find_prompt(steps)
    menu_index = next(i for i, node in enumerate(siblings) if node.get("type") == "choice" and node.get("options", [{}])[0].get("text") == "Tea")
    menu = siblings[menu_index]
    assert [option["text"] for option in menu["options"]] == ["Tea", "Lunch"]
    assert [step["type"] for step in menu["options"][0]["steps"]] == ["action", "end"]
    lunch_steps = menu["options"][1]["steps"]
    assert lunch_steps[0] == {"type": "line", "speaker": "Player", "text": "Lunch."}
    assert lunch_steps[1]["text"] == "What do I usually eat for tea?"
    assert siblings[menu_index + 1]["type"] == "choice"


def test_poem_warning_and_editorial_notes_preserve_game_text():
    value = record(
        "X",
        """==Report==
<poem>
Designation: Ally
Race: Siren
</poem>
* Before starting this quest, be aware that your combat level is too low.
* '''Player:''' I know!{{^|This is an editorial note.}}
""",
    )
    steps = value["variants"]["report"]
    assert steps[0] == {"type": "message", "text": "Designation: Ally\nRace: Siren"}
    assert steps[1]["type"] == "message"
    assert steps[2] == {"player": "I know!"}
    with pytest.raises(ValueError, match="Unclosed poem"):
        record("X", "==Report==\n<poem>\nDon't drop me.")

    value = record(
        "X",
        "==Report==\n* {{tcond|If ready:}}\n** '''X:''' Outputting now.\n<poem>\nNested report\n</poem>\n** {{tact|end}}",
    )
    assert value["variants"]["report"][0]["steps"][1] == {
        "type": "message",
        "text": "Nested report",
    }


def test_annotated_option_becomes_a_condition():
    node = update.parse_step(
        "{{topt|Travel.}} {{Colour|blue|(only after [[The Golem]])}}", [], 1
    )
    assert node == {
        "type": "option",
        "text": "Travel.",
        "condition": "If the player has completed The Golem:",
    }
    issues = []
    node = update.parse_step(
        "{{topt|cond|With a ring equipped:|[Charm] Pick one.}}", issues, 2
    )
    assert node == {
        "type": "option",
        "text": "[Charm] Pick one.",
        "condition": "With a ring equipped:",
    }
    assert issues[0]["reason"] == "Recovered positional option condition"


def test_guarded_one_option_menus_lift_with_original_ids_and_shared_continuation():
    pages = json.loads((config.DATA_PATH / "dialogues" / "quest-pages.json").read_text())
    page = pages["Transcript:Ethically Acquired Antiquities"]
    name = "Ethically Acquired Antiquities"
    variants = [
        "clues-in-civitas-illa-fortis-talking-to-a-trader-crewmember",
        "clues-in-civitas-illa-fortis-talking-to-a-trader-crewmember-after-declining-doing-the-favour",
    ]
    parsed = update.parse_npc(name, page["wikitext"], set())
    expected_ids = {}
    for variant in variants:
        steps = copy.deepcopy(update.gameplay_npc(name, parsed)["variants"][variant])
        annotate(steps, f"Transcript:{name}#{variant}", {})
        expected_ids[variant] = {
            node["text"]: node["id"]
            for node in walk(steps)
            if node.get("type") == "condition"
            and node.get("text") in (
                "If the player hasn't completed One Small Favour:",
                "If the player has completed One Small Favour:",
            )
        }

    value = record(name, page["wikitext"])
    value["source"] = {"page": "Transcript:" + name, "revision": page["revision"]}
    enrich_records({}, {name: value}, {}, update.clean)
    for variant in variants:
        option = next(
            node for node in walk(value["variants"][variant])
            if node.get("type") == "choice"
            and any(child.get("text") == "Have you seen a man with a case?" for child in node.get("options", []))
        ).get("options")
        case_option = next(child for child in option if child.get("text") == "Have you seen a man with a case?")
        menu = next(child for child in case_option["steps"] if child.get("type") == "choice")
        assert [child["text"] for child in menu["options"]] == [
            "Sure. What do you need?",
            "As long as it is just the one favour...",
            "No thanks." if "after-declining" in variant else "Not right now.",
        ]
        accepted = menu["options"][:2]
        conditions = [
            "If the player hasn't completed One Small Favour:",
            "If the player has completed One Small Favour:",
        ]
        for choice, condition in zip(accepted, conditions):
            assert choice["condition"] == condition
            assert choice["condition_id"] == expected_ids[variant][condition]
            assert choice["id"]
        completed = follow(value, accepted[0]["steps"])
        assert any(
            node.get("text", "").startswith("We've been meaning to get our old sails stitched up")
            for node in completed
        )
        assert sum(
            node.get("text", "").startswith("We've been meaning to get our old sails stitched up")
            for node in completed
        ) == 1


def test_other_guarded_single_option_menus_are_not_mistaken_for_a_decline_menu():
    pages = json.loads((config.DATA_PATH / "dialogues" / "quest-pages.json").read_text())
    page = pages["Transcript:Garden of Tranquillity"]
    name = "Garden of Tranquillity"
    value = record(name, page["wikitext"])
    enrich_records({}, {name: value}, {}, update.clean)
    steps = value["variants"]["talking-to-kragen-talking-to-kragen-again"]
    menu = steps[0]
    assert menu["type"] == "choice" and not menu["options"]
    assert [step["type"] for step in steps[1:4]] == ["condition", "condition", "choice"]
    assert not any(node.get("condition_id") for node in walk(steps))


def test_shared_reply_is_scoped_to_the_speaking_participant_and_keeps_effect_id():
    npcs = {
        name: record(
            name,
            f"==Standard dialogue==\n* {{{{topt|Trade.}}}}\n** '''{name}:''' {name}'s shop.\n** {{{{tact|opens={name}'s Shop}}}}",
        )
        for name in ["Alice", "Bob"]
    }
    quest = record(
        "A quest",
        """{{Transcript list|Alice|Bob}}
==Talking==
* '''Alice:''' Hello.
* {{topt|quest=No|Trade.}}
""",
    )
    pages = {
        name: {"wikitext": "{{Infobox NPC|name=" + name + "|id=" + str(i) + "}}"}
        for i, name in enumerate(npcs, 1)
    }
    enrich_records(npcs, {"A quest": quest}, pages, update.clean)
    option = quest["variants"]["talking"][1]["options"][0]
    assert option["steps"][0]["speaker"] == "Alice"
    assert option["steps"][0]["text"] == "Alice's shop."
    original = npcs["Alice"]["variants"]["standard-dialogue"][0]["options"][0]["steps"][
        -1
    ]
    assert option["steps"][-1]["id"] == original["id"]
    assert not any("_shared" in node for node in walk(quest["variants"]["talking"]))


def test_ambiguous_shared_reply_is_not_guessed():
    npc = record(
        "Alice",
        "==Before==\n* {{topt|Trade.}}\n** '''Alice:''' Before.\n==After==\n* {{topt|Trade.}}\n** '''Alice:''' After.",
    )
    quest = record(
        "A quest",
        "{{Transcript list|Alice}}\n==Talking==\n* '''Alice:''' Hello.\n* {{topt|quest=no|Trade.}}",
    )
    enrich_records({"Alice": npc}, {"A quest": quest}, {}, update.clean)
    assert not quest["variants"]["talking"][1]["options"][0].get("steps")


def test_shared_reply_can_bind_an_ambiguous_option_to_its_original_source_variant():
    npc = record(
        "Alice",
        "==West port==\n* {{topt|Travel.}}\n** '''Alice:''' Going east.\n==East port==\n* {{topt|Travel.}}\n** '''Alice:''' Going west.",
    )
    quest = record(
        "A quest",
        "{{Transcript list|Alice}}\n==Talking==\n* '''Alice:''' Hello.\n* {{topt|quest=no|Travel.}}",
    )
    binding = {
        "A quest": {
            "shared_options": {"Travel.": {"page": "Alice", "variant": "east-port"}}
        }
    }
    enrich_records({"Alice": npc}, {"A quest": quest}, {}, update.clean, binding)
    option = quest["variants"]["talking"][1]["options"][0]
    assert [(line.get("speaker"), line.get("text")) for line in option["steps"]] == [
        ("Alice", "Going west.")
    ]
    assert option["steps"][0]["id"].startswith("Transcript:Alice#east-port/")
    with pytest.raises(ValueError, match="Stale shared dialogue binding"):
        quest = record(
            "A quest",
            "{{Transcript list|Alice}}\n==Talking==\n* '''Alice:''' Hello.\n* {{topt|quest=no|Travel.}}",
        )
        binding["A quest"]["shared_options"]["Travel."]["variant"] = "missing"
        enrich_records({"Alice": npc}, {"A quest": quest}, {}, update.clean, binding)


def test_npc_option_anchor_resolves_a_differently_named_above_reference_before_sharing():
    npc = record(
        "Alice",
        "==West port==\n* {{topt|I would like to go east.}}\n** '''Player:''' East, please.\n** '''Alice:''' Sailing east.\n==East port==\n* {{topt|Travel.}}\n** {{topt|Go east.}}\n*** {{tact|above}}",
    )
    quest = record(
        "A quest",
        "{{Transcript list|Alice}}\n==Talking==\n* '''Alice:''' Hello.\n* {{topt|quest=no|Travel.}}",
    )
    bindings = {
        "Alice": {
            "shared_options": {
                "Go east.": {
                    "page": "Alice",
                    "variant": "west-port",
                    "option": "I would like to go east.",
                }
            }
        }
    }
    enrich_records({"Alice": npc}, {"A quest": quest}, {}, update.clean, bindings)
    for record_, variant, at in [(npc, "east-port", 0), (quest, "talking", 1)]:
        travel = record_["variants"][variant][at]["options"][0]
        east = travel["steps"][0]["options"][0]
        assert any(node.get("player") == "East, please." for node in east["steps"])


def test_below_uses_the_matching_line_tail_and_quoted_references_use_source_text():
    value = record(
        "A quest",
        """==Talking==
* {{tselect}}
* {{topt|First}}
** '''Player:''' First.
** {{tact|below}}
* {{topt|Second}}
** '''Player:''' Second.
** '''Other:''' Shared reply.
** {{tact|Continues below from "The final..."}}
* {{topt|Third}}
** '''Other:''' Different opening.
** '''Other:''' Shared reply.
** '''Other:''' The final speech.
** {{qact|The NPC departs.}}
* {{topt|Fourth}}
** '''Other:''' Shared reply.
** {{tact|above}}
""",
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    options = value["variants"]["talking"][0]["options"]
    assert follow(value, options[0]["steps"])[1]["text"] == "Shared reply."
    assert follow(value, options[1]["steps"])[2]["text"] == "The final speech."
    assert follow(value, options[3]["steps"])[1]["text"] == "The final speech."


def test_continues_after_an_npc_answer_still_owed_replays_that_answer():
    # Shield of Arrav: the Player asks to join and the wiki says the talk
    # "Continues after 'How unusual...'". Katrine's "How unusual..." answers
    # that request, so it plays first (rsprox submission 1705).
    value = record(
        "A quest",
        """==Talking==
* {{tselect}}
* {{topt|Join}}
** '''Player:''' I want to join.
** {{tact|Continues after "How unusual..."}}
* {{topt|Hints}}
** '''Player:''' Give me hints.
** '''Other:''' Why would I?
** '''Player:''' I could join in return?
** '''Other:''' How unusual... Say we are who you think.
** '''Player:''' I don't know.
* {{topt|Ask}}
** '''Player:''' Who are you?
** '''Other:''' Well, what do you want?
** {{tact|Continues after "So, what do you want with us"}}
* {{topt|Leave}}
** '''Player:''' Bye.
** '''Other:''' So, what do you want with us?
** '''Player:''' Nothing.
""",
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    options = value["variants"]["talking"][0]["options"]
    joined = follow(value, options[0]["steps"])
    assert [n.get("text", n.get("player")) for n in joined] == [
        "I want to join.",
        "How unusual... Say we are who you think.",
        "I don't know.",
    ]
    # The branch already said its own version of the anchor: resume past it.
    asked = follow(value, options[2]["steps"])
    assert [n.get("text", n.get("player")) for n in asked] == [
        "Who are you?",
        "Well, what do you want?",
        "Nothing.",
    ]


def test_continues_after_a_quoted_line_tail_finds_the_branch_that_goes_on():
    # Shield of Arrav: Katrine's "Hmm... So, say we were the Black Arm Gang..." is the
    # anchor for "Continues above after 'Say we were...'"; the jumping branches end on
    # their own "...say we were..." lines, which must not count as the anchor.
    value = record(
        "A quest",
        """==Talking==
* {{tselect}}
* {{topt|Secret}}
** '''Player:''' I won't say.
** '''Other:''' Hmm... Fine. So, say we were them, what would you want?
** {{tselect}}
** {{topt|Join}}
*** '''Player:''' I want to join.
** {{topt|Leave}}
*** '''Player:''' Nothing.
* {{topt|Tramp}}
** '''Player:''' The tramp told me.
** '''Other:''' Anyway, say we were them, what would you want?
** {{tact|Continues above after "Say we were them, what would you want?"}}
* {{topt|Everyone}}
** '''Player:''' Everyone knows.
** '''Other:''' I see... say we were them, what would you want?
** {{tact|Continues above after "Say we were them, what would you want?"}}
""",
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    options = value["variants"]["talking"][0]["options"]
    for option in options[1:]:
        steps = follow(value, option["steps"])
        assert steps[-1].get("type") == "choice"
        assert [o["text"] for o in steps[-1]["options"]] == ["Join", "Leave"]
        assert not any(
            "Hmm... Fine." in str(n.get("text", "")) for n in steps
        ), "the jumping branch already said its own version of the line"


def test_named_section_navigation_keeps_menu_cycles_as_calls():
    value = record(
        "X",
        """==Standard dialogue==
* '''X:''' Hello.
* {{tact|Follow-up options}}
==Follow-up options==
* {{tselect}}
* {{topt|Again}}
** {{tact|Follow-up options}}
""",
    )
    enrich_records({"X": value}, {}, {}, update.clean)
    assert value["variants"]["standard-dialogue"][-1] == {
        "type": "call",
        "branch": "follow-up-options",
    }
    assert value["branches"]["follow-up-options"][0]["options"][0]["steps"][0] == {
        "type": "call",
        "branch": "follow-up-options",
    }


def test_repeated_speech_in_another_section_requires_a_unique_continuation():
    raw = """==First==
* '''Player:''' What did he search for?
* '''Machine:''' Repeat last search.
==Again==
* '''Player:''' What did he search for?
* {{tact|above}}
"""
    value = record("A quest", raw)
    enrich_records({}, {"A quest": value}, {}, update.clean)
    assert follow(value, value["variants"]["again"])[1]["text"] == "Repeat last search."

    value = record(
        "A quest",
        raw.replace(
            "==Again==",
            "==Another==\n* '''Player:''' What did he search for?\n* '''Machine:''' Something else.\n==Again==",
        ),
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    assert value["variants"]["again"][-1]["reference"] == "above"

    value = record(
        "A quest", raw.replace("'''Machine:''' Repeat last search.", "{{tact|above}}")
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    assert value["variants"]["again"][-1]["reference"] == "above"

    value = record(
        "A quest",
        raw.replace("Repeat last search.", "Repeat last search.\n* {{tact|above}}"),
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    assert value["variants"]["again"][-1]["reference"] == "above"


def test_continues_inside_conditions_resumes_the_enclosing_option():
    value = record(
        "A quest",
        """==Starting==
* {{tselect}}
* {{topt|Anything I can help with?}}
** {{tcond|If the player is inexperienced:}}
*** '''Guide:''' You are new to this.
*** {{tact|continues}}
** {{tcond|If the player is experienced:}}
*** '''Guide:''' You have done this before.
*** {{tact|continues}}
** {{tbox|Be prepared.}}
** {{tselect|Start the quest?}}
** {{topt|Yes.}}
*** '''Guide:''' Good luck.
*** {{tact|end}}
** {{topt|No.}}
*** {{tact|end}}
* {{topt|What is the banner for?}}
** '''Guide:''' It advertises our group.
** {{tselect}}
** {{topt|Join the group.}}
*** {{tact|end}}
** {{topt|No thanks.}}
*** {{tact|end}}
""",
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    steps = value["variants"]["starting"][0]["options"][0]["steps"]
    for condition in steps[:2]:
        assert condition["type"] == "condition"
        line, continuation = condition["steps"]
        assert line["type"] == "line"
        assert continuation["reference"] == "continues"
        assert "steps" not in continuation
    assert steps[-1]["prompt"] == "Start the quest?"


def test_continues_at_the_end_of_an_option_can_reuse_a_shared_followup_menu():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect}}
* {{topt|First reply.}}
** '''X:''' First introduction.
** {{tact|continues}}
* {{topt|Second reply.}}
** '''X:''' Second introduction.
** {{tselect}}
** {{topt|A shared follow-up.}}
*** '''X:''' The next reply.
*** {{tact|end}}
""",
    )
    enrich_records({"X": value}, {}, {}, update.clean)
    first = value["variants"]["standard-dialogue"][0]["options"][0]
    continued = follow(value, first["steps"])
    assert continued[-1]["options"][0]["text"] == "A shared follow-up."


def test_fairytale_start_continues_reach_the_source_start_prompt():
    pages = json.loads((config.DATA_PATH / "dialogues" / "quest-pages.json").read_text())
    name = "Fairytale I - Growing Pains"
    page = pages["Transcript:" + name]
    value = record(name, page["wikitext"])
    value["source"]["revision"] = page["revision"]
    enrich_records({}, {name: value}, {}, update.clean)
    starting = value["variants"]["starting-the-quest"]
    help_option = next(
        node for node in walk(starting)
        if node.get("text") == "Anything I can help with?"
    )
    farming = [
        node for node in help_option["steps"]
        if node.get("type") == "condition" and "Farming" in node["text"]
    ]
    assert len(farming) == 2
    for condition in farming:
        line, continuation = condition["steps"]
        assert line["type"] == "line"
        assert continuation["reference"] == "continues"
        assert "steps" not in continuation
    start = next(node for node in help_option["steps"] if node.get("type") == "choice")
    assert start["prompt"] == "Start the Fairytale I - Growing Pains quest?"
    assert [option["text"] for option in start["options"]] == ["Yes.", "No."]
    assert start["options"][0]["hook"] == "quest:fairytale-i-growing-pains:start"


def test_repeated_section_conditions_share_the_explicit_continuation():
    value = record(
        "A quest",
        """==First report==
* {{tcond|If First report was the last report read:}}
** '''Guide:''' We can leave now.
** {{qact|The guide departs.}}
==Second report==
* {{tcond|If Second report was the last report read:}}
** {{tact|above}}
""",
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    original = value["variants"]["first-report"][0]["steps"]
    repeated = follow(value, value["variants"]["second-report"][0]["steps"])
    assert repeated == original


def test_explicit_followup_rule_omits_the_topic_just_selected():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect}}
* {{topt|Tell me about the fleet.}}
** '''X:''' A fine fleet.
** {{tact|Follow-up options}}
* {{topt|Ask some questions.}}
** '''X:''' Ask away.
** {{tact|Follow-up options}}
==Follow-up options==
After a topic ends, the topic just asked about is left out.
* {{tselect}}
* {{topt|Tell me about the fleet.}}
** {{tact|above}}
* {{topt|Ask some questions.}}
** {{tact|above}}
* {{topt|Goodbye.}}
** {{tact|end}}
""",
    )
    enrich_records({"X": value}, {}, {}, update.clean)
    menu = value["branches"]["follow-up-options-without-tellmeaboutthefleet"][0]
    assert [option["text"] for option in menu["options"]] == [
        "Ask some questions.",
        "Goodbye.",
    ]
    assert follow(value, menu["options"][0]["steps"])[0]["npc"] == "Ask away."
    assert not any(node.get("type") == "unavailable" for node in walk(menu["options"]))


def test_same_reply_is_disambiguated_by_its_enclosing_menu():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect}}
* {{topt|Pay from bank}}
** '''X:''' Bank.
* {{topt|No thanks, keep your money.}}
** '''X:''' Bank refusal.
* {{tselect}}
* {{topt|Yes, okay.}}
** '''X:''' Fine paid.
* {{topt|No thanks, keep your money.}}
** '''X:''' Jail refusal.
==At the door==
* {{tselect}}
* {{topt|Yes, okay.}}
** {{tact|above}}
* {{topt|No thanks, keep your money.}}
** {{tact|above}}
""",
    )
    enrich_records({"X": value}, {}, {}, update.clean)
    refusal = value["variants"]["at-the-door"][0]["options"][1]
    assert follow(value, refusal["steps"])[0]["npc"] == "Jail refusal."


def test_named_and_unnamed_versions_of_the_same_shop_reply_are_equivalent():
    npc = record(
        "Alice",
        """==Before==
* {{topt|Trade.}}
** '''Alice:''' Of course.
** {{tact|(Shop interface opens.)}}
==After==
* {{topt|Trade.}}
** '''Alice:''' Of course.
** {{tact|opens=Alice's Shop}}
""",
    )
    quest = record(
        "A quest",
        "{{Transcript list|Alice}}\n==Talking==\n* '''Alice:''' Hello.\n* {{topt|quest=no|Trade.}}",
    )
    enrich_records({"Alice": npc}, {"A quest": quest}, {}, update.clean)
    assert (
        quest["variants"]["talking"][1]["options"][0]["steps"][-1]["target"]
        == "Alice's Shop"
    )


def test_navigation_does_not_compile_a_loop_without_a_player_step():
    value = record(
        "X",
        """==Standard dialogue==
* '''X:''' First.
* {{tact|Continues after "Second."}}
* '''X:''' Second.
* {{tact|Continues after "First."}}
""",
    )
    enrich_records({"X": value}, {}, {}, update.clean)
    assert not value.get("branches")
    assert not any(
        node.get("type") == "call"
        for node in walk(value["variants"]["standard-dialogue"])
    )


def test_runtime_resume_bindings_use_source_suffixes_and_update_indexes():
    data = {
        "records": {
            "X": {
                "steps": [
                    {"type": "action", "id": "anchor"},
                    {"player": "Reaction."},
                    {"npc": "Resume here."},
                    {"type": "action", "id": "travel", "action": "teleport"},
                ]
            }
        },
        "authoring": {
            "Transcript:X": {"sections": {"standard-dialogue": ["Standard dialogue"]}}
        },
        "index": {"1": [{"page": "Transcript:X", "variants": ["standard-dialogue"]}]},
    }
    apply_bindings(
        data,
        {
            "X": {
                "effects": {"travel": {"target": "A place"}},
                "variants": {
                    "resume": {
                        "variant": "standard-dialogue",
                        "after": "anchor",
                        "skip_player": True,
                    }
                },
            }
        },
    )
    assert data["records"]["X"]["variants"]["resume"] == [
        {"npc": "Resume here."},
        {"type": "action", "id": "travel", "action": "teleport", "target": "A place"},
    ]
    assert data["index"]["1"][0]["variants"] == ["standard-dialogue", "resume"]
    with pytest.raises(ValueError, match="Stale dialogue effect binding"):
        apply_bindings(
            data, {"X": {"effects": {"missing": {"target": "Another place"}}}}
        )
    with pytest.raises(ValueError, match="Stale dialogue resume binding"):
        apply_bindings(
            data,
            {
                "X": {
                    "variants": {
                        "missing": {"variant": "standard-dialogue", "after": "missing"}
                    }
                }
            },
        )


def test_below_shared_by_every_later_option_continues_after_the_menu():
    # Making History: each of Jorral's "three people" answers ends {{tact|below}},
    # the last one included, and live then shows the menu that follows them
    # (RSProx capture 20261111T015053-5ab63b4, ticks 189-195), not the next answer.
    value = record(
        "A quest",
        """==Talking==
* '''Jorral:''' There are three people that may be able to help:
* {{tselect|Select an option}}
* {{topt|A trader in Ardougne}}
** '''Jorral:''' A silver trader.
** '''Player:''' OK, I'll see what he has to say.
** {{tact|below}}
* {{topt|A ghost in Port Phasmatys}}
** '''Jorral:''' A ghost.
** '''Player:''' I'll track him down.
** {{tact|below}}
* {{topt|A warrior in Rellekka}}
** '''Jorral:''' A warrior.
** '''Player:''' That sounds simple enough.
** {{tact|below}}
* {{tselect|Select an option}}
* {{topt|What's the story so far?}}
** '''Player:''' What's the story so far?
* {{topt|Got to go, bye!}}
** '''Player:''' Got to go, bye!
""",
    )
    enrich_records({}, {"A quest": value}, {}, update.clean)
    options = value["variants"]["talking"][1]["options"]
    for option in options:
        spoken = [node.get("text", node.get("npc", node.get("player"))) for node in follow(value, option["steps"])]
        others = [other["steps"][0]["text"] for other in options if other is not option]
        assert not set(spoken) & set(others), (option["text"], spoken)
        assert option["steps"][-1].get("reference") == "below"


def test_random_draw_wording_becomes_a_counted_random_and_keeps_its_followups_apart():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect|Select an option}}
* {{topt|Start}}
** '''X:''' Intro.
** {{tact|A random dialogue is selected, three times, non-repeating, from the following:}}
** {{topt|Dialogue 1}}
*** '''X:''' Question one.
** {{topt|Dialogue 2}}
*** '''X:''' Question two.
** {{tact|After the first question is answered:}}
*** '''X:''' That was the first.
** {{tact|After the third question is answered:}}
*** '''X:''' That was the third.
* {{topt|Leave}}
** '''X:''' Bye.
""",
    )
    menu = value["variants"]["standard-dialogue"][0]
    assert [option["text"] for option in menu["options"]] == ["Start", "Leave"]
    steps = menu["options"][0]["steps"]
    assert steps[0] == {"npc": "Intro."}
    draw = steps[1]
    assert draw["type"] == "random"
    assert (draw["count"], draw["non_repeating"]) == (3, True)
    assert [option["text"] for option in draw["options"]] == ["Dialogue 1", "Dialogue 2"]
    # The follow-ups are siblings after the draw, not the last alternative's body.
    assert all(option["steps"] == [{"npc": text}] for option, text in zip(
        draw["options"], ["Question one.", "Question two."]
    ))
    assert [(step["type"], step["text"]) for step in steps[2:]] == [
        ("condition", "After the first question is answered:"),
        ("condition", "After the third question is answered:"),
    ]


def test_other_random_wording_is_not_read_as_a_counted_draw():
    value = record(
        "X",
        """==Standard dialogue==
* {{tselect|Select an option}}
* {{topt|Start}}
** {{tact|A random dialogue is selected from the following:}}
** {{topt|One}}
*** '''X:''' One.
""",
    )
    steps = value["variants"]["standard-dialogue"][0]["options"][0]["steps"]
    assert all("count" not in step for step in steps)


def test_myreque_curpile_quiz_is_three_random_questions_and_refusal_is_a_menu_option():
    page = json.loads(
        (config.DATA_PATH / "dialogues" / "quest-pages.json").read_text(encoding="utf-8")
    )["Transcript:In Search of the Myreque"]
    bindings = json.loads(
        (config.DATA_PATH / "dialogues" / "runtime-bindings.json").read_text(encoding="utf-8")
    )["In Search of the Myreque"]["structure"]
    raw = update.apply_structure_annotations(
        "In Search of the Myreque", page["wikitext"], bindings, page["revision"]
    )
    variant = update.parse_npc("In Search of the Myreque", raw)["variants"][
        "convincing-curpile-fyod-talking-to-curpile-fyod"
    ]
    menu = next(step for step in variant["steps"] if step["type"] == "choice")
    # void's Curpile menu: the refusal is option 2 of the initial menu, not a question.
    assert [option["text"] for option in menu["options"]] == [
        "I've come to help the Myreque. I've brought weapons.",
        "I don't have to answer to you!",
        "No reason!",
        "I'm lost. Can you show me the way out?",
        "I have to go.",
    ]
    steps = menu["options"][0]["steps"]
    draw = next(step for step in steps if step["type"] == "random")
    assert (draw["count"], draw["non_repeating"]) == (3, True)
    assert [option["text"] for option in draw["options"]] == [f"Dialogue {n}" for n in range(1, 7)]
    assert all(option["steps"][-1]["type"] == "choice" for option in draw["options"])
    after = [step for step in steps if step["type"] == "condition" and "question is answered" in step["text"]]
    assert [step["text"] for step in after] == [
        "After the first question is answered:",
        "After the second question is answered:",
        "After the third question is answered:",
    ]
    results = [step["text"] for step in after[2]["steps"] if step["type"] == "condition"]
    assert len(results) == 4 and "three out of three" in results[3]
    # The refusal branch keeps its own lines and the punch note.
    refusal = menu["options"][1]["steps"]
    assert [step.get("text") for step in refusal if step["type"] == "line"][-1].startswith("You do if")


def test_condition_guarding_one_option_after_a_menu_joins_that_menu():
    value = record(
        "The Lady of the Lake",
        """==After completing [[Merlin's Crystal]]==
* '''The Lady of the Lake:''' Good day to you.
* {{topt|Who are you?}}
** '''Player:''' Who are you?
** {{tact|end}}
* {{topt|Good day.}}
** '''Player:''' Good day.
* {{tcond|If the player does not have [[Excalibur]] in their bank or inventory:}}
** {{topt|I seek the sword Excalibur.}}
*** '''Player:''' I seek the sword Excalibur.
*** '''The Lady of the Lake:''' 500 gold coins ought to do it.
""",
    )
    enrich_records({}, {"The Lady of the Lake": value}, {}, update.clean)
    steps = value["variants"]["after-completing-merlin-s-crystal"]
    menu = next(step for step in steps if step.get("type") == "choice")
    assert [option["text"] for option in menu["options"]] == ["Who are you?", "Good day.", "I seek the sword Excalibur."]
    guarded = menu["options"][2]
    assert guarded["condition"] == "If the player does not have Excalibur in their bank or inventory:"
    assert guarded["condition_id"]
    assert follow(value, guarded["steps"])[0]["player"] == "I seek the sword Excalibur."
    # Nothing of the condition is left after the menu.
    assert not any(step.get("type") == "condition" for step in steps)
