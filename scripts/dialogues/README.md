# NPC and quest dialogue exports

Build with `python -m scripts.dialogues.update`. The collector fetches the wiki's
**NPC dialogue** and **Quest transcript** categories, follows explicit transcript
links, and fetches NPC identity pages named by transcripts. Cached revisions are
reused; `--refresh` fetches them again. `--offline` rebuilds only from cached sources.
A failed download does not publish a partial gameplay export. Explicitly missing
wiki pages remain cached and unresolved; use `--refresh` to retry them.

## Files

- `docs/npc-dialogues.json`: all NPC and quest/reference conversations, keyed by transcript title without `Transcript:`.
- `docs/npc-dialogues-minified.json`: identical aggregate data without formatting whitespace or a trailing newline; Unicode stays literal UTF-8 and dialogue text is preserved.
- `docs/npc-dialogue-index.json`: NPC ID -> candidate transcript pages and variants.
- `data/dialogues/wiki-pages.json`, `quest-pages.json`, `npc-pages.json`: source wikitext and revision IDs.
- `data/dialogues/corrections.json`: remaining content/capture corrections, with source commits and checked input fingerprints.
- `data/dialogues/runtime-bindings.json`: source-node resume points, effect parameters and cache-backed NPC identity bindings; contains no copied dialogue.
- `data/dialogues/authoring-index.json`: source revisions, participant identities and section descriptions, keyed by transcript page.
- `docs/dialogue-manifest.json`: transcript page -> one independently loadable file under `docs/dialogues/`.
- `data/dialogues/review-issues.json`: missing content, unresolved navigation and parser diagnostics.
- `data/dialogues/inferred-actions.txt`: inferred and unimplemented actions for review.

The NPC-ID index uses the existing wiki infobox ID extractor. Quest participants
come from `Transcript list`, and their spoken names are matched only within those
explicit participant pages. NPCs sharing a short name are never globally merged.
An absent ID mapping is unresolved identity, not permission to guess a name match.
The index lists candidates, not a quest-state-aware routing decision.

## Record shapes and natural endings

When the only variant is `standard-dialogue` and it is the selected default,
the record uses `steps` directly:

```json
{"steps": [{"npc": "Hello."}]}
```

Otherwise it keeps `variants` and `default`. A sole post-quest
variant with `default: null` is not flattened. Both shapes can have `branches`.
The flat form still represents the implicit variant `standard-dialogue` in the
NPC-ID and authoring indexes.
Resolve a variant as follows:

```js
const steps = record.steps !== undefined
  ? (variant === 'standard-dialogue' ? record.steps : undefined)
  : record.variants[variant];
```

A bare `end` is omitted only at a provable tail position with no subsequent local
or enclosing steps. The runner closes when the root conversation queue is exhausted.
Explicit ends still terminate the entire conversation, including parent continuations.
Ends with reasons (e.g. members-only), hooks or other metadata remain explicit.
Pruning happens before sharing branches, so an end needed at any call site is
not removed by treating a shared branch as a standalone conversation.
Variants are root/transfer entrypoints, not subroutines with implicit return tails;
only `call` nodes return to a caller's remaining steps.

## Hooking a quest

For Cook (NPC 4626), look up `npc-dialogue-index.json["4626"]`. One candidate is
`Transcript:Cook's Assistant`, variant `starting-off`. Load that from
`npc-dialogues.json["Cook's Assistant"].variants["starting-off"]`.
Its Yes option carries:

```json
{"hook": "quest:cook-s-assistant:start", "quest": "Cook's Assistant"}
```

Bind that hook to the quest plugin's acceptance handler. Run it **after the player
selects the option and its condition passes, before playing its steps**. The
handler checks requirements and sets the persisted stage. Rejection stops the
branch. It must be idempotent: the NPC and quest transcripts can describe the
same acceptance, and an explicit start action may repeat it.

Standalone explicit `X is started` actions become `action: "quest_start"` with
the same hook. These prose-derived markers retain `action_source: "text"` for
review. Acceptance hooks are emitted only for exact Yes choices under explicit
`Start ...?` prompts naming a collected quest. We do not infer acceptance from
arbitrary speech or automatically grant items/XP.

Bind entry conditions by transcript page and variant name; no separate entrypoint
ID is needed. For a condition node or conditional option, use
`condition:<node ID>`. This key is derived, not repeated in the JSON.
Condition prose remains in the runtime data. Unbound conditions block the branch;
selecting a default does not make its entry condition automatically true.

IDs remain on conditions, effects and references. Menus, unconditional options,
ordinary speech and end nodes have none; named quest hooks need no extra ID.
IDs are 6-character URL-safe hashes of the previous
source-addressed identity, so unrelated insertions still do not rename branches.
Editing a node's text, renaming a section or inserting identical siblings can
change affected IDs. Semantic `quest:...:start` hooks remain unchanged.

Generated nodes use the IDs described above. Reviewed corrections also preserve
semantic IDs (for example `sheep-shearer:finish-handover`), repeated bindings for
the same effect, and nodes without an ID that the consumer handles through prose
or context. Consumers must treat IDs as optional opaque strings. Corrected records
can use named branches that call other local branches; menu continuations can
deliberately return to an earlier menu. The generated-source compactor still rejects collisions between different source
IDs. Copies of the same source body retain the same binding IDs.

The authoring index retains source revisions, original section paths, participants
and NPC identities. It is not needed during playback; use the NPC-ID index for
routing. This compact format replaces the earlier long IDs and stored condition
keys; update node-level bindings when migrating. IDs are scoped to their conversation (branch IDs use their local branch table).
The exporter rejects collisions rather than silently aliasing nodes. Existing
16-character node bindings must migrate; named quest hooks are unchanged.
No quest stage rules are inferred.

## Shared branches and selective loading

Byte-for-byte identical terminal step lists can be stored once in a record's
`branches` table. A step `{"type":"call","branch":"<ID>"}` means: play that
local branch **then resume the remaining caller steps**. It is not a wiki jump.
Automatically deduplicated terminal bodies have identical conditions/effects/IDs.
Explicit wiki navigation also produces named branches, which can call other local
branches or return to a menu. Execute calls lazily; do not recursively expand the
whole graph before playback. Calls inherit the same player and speaker context as inline steps.
Do not treat a call as a dialogue end or skip it. Tiny repeats stay inline when a
reference would cost more bytes. Unresolved wiki navigation is unchanged.

For selective loading, fetch the manifest once, then only the selected page:

```js
const manifest = await fetch('/dialogue-manifest.json').then(r => r.json());
const file = manifest["Transcript:Cook's Assistant"];
const dialogue = await fetch('/' + file).then(r => r.json());
const opening = dialogue.steps ?? dialogue.variants[dialogue.default];
```

The server can similarly read the manifest and load only the selected JSON file.
NPC-ID index entries identify candidate pages and variants; the plugin selects the
right one from quest state. Explicit cross-page references use the same manifest.
Each shard is identical to its aggregate record and includes its own shared branches.
The readable and minified aggregate exports are available for bulk consumers.
These and the shards are alternative delivery formats; publishing all duplicates
storage. Every build writes `npc-dialogues-minified.json` beside the readable
aggregate, including when `--out` selects another directory. The generator removes
stale hash-named shards on rebuild.

## References and defaults

Explicit transcript links retain `type: "reference"`, `target` (page), `section`,
`page_available` and `resolved`. An unambiguous section match also gets the target’s `variant` name.
A page-only reference is **not** resolved to its default: e.g. an NPC's Yes branch
must not replay the quest's opening menu. A plugin can handle that reference node
by ID and route to the appropriate stage. Repeated-line anchors, exact quoted references, matching conditions in repeated
sections and unique same-option bodies resolve to local branch calls. Named
section references also become calls. Ambiguous references and history-dependent
`previous`, `other` and `initial` navigation retain their original jump markers.
Across sections, repeated speech resolves only to a unique substantive continuation.
Shared nonquest replies are imported only from the explicitly named participant
and only when the speaking NPC and response are unambiguous.

Defaults recognise `Pre-quest`, starting sections and conditional openings.
Post-quest-only records remain `default: null`. Default selection is a heading
heuristic, never a substitute for quest-state checks. Canonical variant keys are
preserved, rather than renaming the selected one to `standard`.

## Runner compatibility

This extends the earlier NPC-only format. Consumers must use each record's
`default` value rather than hardcode `standard`, and support explicit speakers
(`type: "line"`, `speaker`, `text`) in multi-NPC quest conversations. Scoped NPC
self-speech is still `{"npc":"..."}`, player speech `{"player":"..."}`. Explicit
`{{overhead|...}}` speech keeps its normal shape and may add
`"presentation": "overhead"`; that is the only presentation value and it does not
change the speaker, text or control flow.
Choices/random alternatives have nested `options` and `steps`. Message, missing,
unavailable, condition and reference nodes must not silently disappear.

`open_shop.target` is an exact key in `shops-items-by-shop.json`; `open_interface`
is not a shop ID. `receive`, `give`, teleport and other effects may still carry
prose instead of structured game IDs/amounts. Bind effects by node ID in the quest
plugin; don't execute prose. `action_source: "text"` identifies inferred actions.

Schemas: `data/schemas/schema-dialogues.json`, `schema-npc-dialogue-index.json`,
`schema-dialogue-manifest.json` and `schema-dialogue-authoring.json`.
Python record types: `osrsreboxed.dialogues.DialogueRecord` and `FlatDialogueRecord`.
Run `python -m pytest test/test_dialogues_export.py test/test_dialogue_hooks.py test/test_dialogue_corrections.py`.

## Preserving the TSPS fixes (issue #700)

The [TSPS #700 audit](https://github.com/RSPSApp/tsps/issues/700) compared the complete
history of `server/data/definitions/npc-dialogues.json` through `d874f7897` with an
offline rebuild. Both exports contained 3,282 conversations, with 23 differences.
Slayer-master updates and most earlier nested-menu repairs were already covered.

The dumper now handles these source features generally:

- Sibling and nested menus, without swallowing options belonging to an outer menu;
  same-depth speech beneath a nested selection stays with its preceding option.
- `<poem>` reports as multiline messages, plain quest warnings, editorial footnotes,
  and quest prerequisites written alongside a dialogue-option template.
- Nonquest responses copied from the speaking participant's NPC transcript, with
  explicit speakers and the original effect IDs. Conflicting quest-state variants
  remain unresolved rather than choosing a response arbitrarily.
- Quoted continuations, repeated-line tails, shared section conditions, unique
  repeated options and explicit named-section navigation. Calls retain the graph
  instead of duplicating every reachable path or following menu cycles at build time.
- Explicit source instructions that a follow-up menu omits the topic just selected.
  The enclosing source option determines which choice is omitted.

Only Rug Merchant and Shantay were refreshed from the live wiki for this change:
revisions **15375814** and **15375813**, respectively. Their source text, menu
nesting and destination prerequisites now come from those cached revisions.

| Original manual correction | Current treatment |
| --- | --- |
| A Night at the Theatre | All 22 crystal-shop replies come from the NPC transcript; shop actions inherit the resolved NPC source target. |
| Desert Treasure II | Archive reports come from poem markup; Banikan continuations use source anchors and repeated section conditions. |
| Legends' Quest | Menu grouping and source continuation resolution. |
| Misthalin Mystery | Shared Lacey cutscene tails resolved from repeated speech. |
| Murder Mystery | Editorial footnote stripped by the cleaner. |
| Tai Bwo Wannai Trio | Shared follow-up menus resolved from the source. |
| The Restless Ghost | Shared skull-recovery continuation resolved from the source. |
| Vampyre Slayer | Plain warning parsed as a message, retaining the previous placeholder's binding ID. |
| The Ides of Milk | Resume binding selects the original source suffix; no duplicated conversation text. |
| Rug Merchant | Refreshed source, annotated prerequisites and explicit follow-up-menu instructions. |
| Shantay | Refreshed source, resolved fine/jail references and a source-based arrest resume binding. |
| Prince Ali Rescue | Shared-dialogue machinery works generally, but Ned has conflicting quest-state responses. The existing rope branch remains a guarded content correction. |
| Shield of Arrav | Recruitment navigation is generated. Only the captured greeting absent from the relevant source variant remains a correction. |
| Demon Slayer, Getting Ahead, Kovac, Meat and Greet, Sheep Shearer, The Corsair Curse, The Garden of Death, X Marks the Spot | Retain captured wording, menu/timing changes or gameplay conditions the source does not supply. |
| Prospector Percy, While Guthix Sleeps | Retain the remaining mixed content/gameplay fixes; Silif's repeated armour and follow-up conversation now comes from source navigation. |

This removes conversation-text patches for **11 records**, and reduces other
patches. The remaining correction file also preserves capture-only records; its fingerprints
check the actual new parser output, rather than a snapshot of the former parser.

`runtime-bindings.json` keeps TSPS entrypoint names (`arrested` and the Ides of
Milk resume), the Port Sarim jail teleport target and the cache-backed Mysterious
Vampyre index entry. Resume entries identify an existing variant and action ID;
the build finds and copies its suffix, updates authoring sections and indexes,
and fails when an anchor is missing or ambiguous. No dialogue wording is stored
in this file. Ordinary dialogue/effect IDs continue to come from source annotation.

Reviewed `navigation` annotations identify a source jump, its expected reference
and the source node to continue after, before navigation resolution/compaction.
They contain no replacement dialogue and fail on missing, duplicate or changed
anchors. The Restless Ghost has one: its bare `above` after "Nope. I just know..."
resumes after "Well, to be honest... I'm not sure." in the same transcript.
The source does not uniquely identify that target, so this remains an explicit,
reviewed interpretation rather than an automatic parser inference.

The normal command applies runtime bindings and the remaining corrections after compaction
and before publishing aggregates, shards, indexes or diagnostics. A corrected
record or edited path that no longer matches stops publication with
`Stale dialogue correction`. Review source changes before rebasing a correction;
do not just accept a new fingerprint. The original correction commits remain linked
in the correction file. Parser diagnostics describe the source before corrections.

General Montoya and Record Keeper are capture-only inputs preserved from TSPS
commit `7a3e4ea0a` (release-day RSProx 241.1; provenance links are in the correction
file). Their `base_sha256: null` requires that the Wiki parser has no record yet.
If a later fetch supplies one, the dump stops for review instead of overwriting
the Wiki record. Their named runtime hooks, cache NPC identities, authoring
metadata and shards are exported together. Capture metadata uses `source.capture`
rather than inventing a Wiki revision.

Never hand-edit any generated JSON, including during merge conflict resolution.
Fix source collection, parsing or reviewed source inputs here, regenerate the
exports, and verify that a second build from unchanged inputs is identical.

PR 715's five quest-flow repairs no longer use output-subtree corrections.
Contact!'s guards remain after both quiz menus as in the Wiki; TSPS evaluates
them when reached, after choices/actions have run. Doric's long acceptance label
matches a unique complete Player utterance (allowing article/punctuation/case
differences). Persten's nested continuation resolves to its enclosing option
body; her short Yes uses the complete menu in the immediately following section.
Colin's `below` links the shared tail of complementary sibling conditions,
excluding the alternate Player reply. The Ghost's repeated long option is matched
without case differences; its other ambiguous marker uses the annotation above.
Existing exact navigation matches take precedence, preserving their source IDs
and dialogue. No global nearest-Yes/No or partial-utterance guess is added.

The same refresh preserves the cache-bound Uzer Evil Dave ids 913/1987 and world
Sarius id 15839 in `runtime-bindings.json`. These name their precise transcript
variants; they do not globally merge NPCs sharing a name.

To regenerate and validate:

```sh
python -m scripts.dialogues.update --offline
python -m pytest test/test_dialogue*.py
```

Generated-content tests check the recovered shop replies, archive/departure flow,
cutscene continuations, resume points, destination prerequisites and follow-up menus.
Export tests validate schemas, all shards, binding IDs and index references.
Copy the aggregate and NPC index into TSPS together, and run its dialogue/quest
checks before adopting a refreshed dump.

Source: https://oldschool.runescape.wiki/ — game dialogue copyright Jagex;
wiki content CC BY-NC-SA 3.0, additional terms at
https://meta.weirdgloop.org/w/Licensing. Retain `docs/npcs-dialogues.LICENSE`
when redistributing the dialogue data.
