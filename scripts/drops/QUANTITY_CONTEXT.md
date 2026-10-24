# Source-listed quantity alternatives and paired drops

This additive export contract prepares the quantity consumer and Vardorvis perfect-kill context. It does not grade fights or implement Sailing bounties/Chasm sigils.

## Source evidence

The [DropsLine documentation](https://oldschool.runescape.wiki/w/Template:DropsLine/doc) defines commas as alternative quantity separators and forbids thousands separators. Evidence is the repository's checked-in `data/monsters/monsters-wiki-page-text.json`; it has no per-page capture timestamps, so this change does not claim a fresh Wiki crawl.

- Vardorvis, The Leviathan, The Whisperer, and Duke Sucellus explicitly describe the perfect-kill increase to standard loot. Their main rows list base/perfect amounts. The page statement, not arithmetic alone, enables the condition.
- Narwhal and Orca Dragon nails have quantity footnotes naming the bounty task. A similar sentence in a rarity footnote does not select a quantity.
- Lesser, Greater, and Black demon ashes have an explicit Chasm of Fire preferred-method note.
- Nex supplies share named group-d references saying the two items drop together. The same syntax supplies pairs on Commander Zilyana, K'ril Tsutsaroth, Kree'arra, Ammonite Crab, Chaos Fanatic, and Ancient Zygomite.

## Quantity contract

`quantity` remains a minimum/maximum pair: the first listed amount. `quantity_raw` retains the cleaned original expression. `quantity_alternatives` lists the source alternatives in order; later alternatives may have a typed `condition`. `quantity_selection` is `conditional` when a source rule is known and `unknown` otherwise. The exporter invents no distribution. Leading-zero comma tokens such as `1,000` remain unresolved instead of becoming an invented amount; editor comments are removed before quantity parsing.

The corpus has 116 alternatives: 99 `perfect_kill` (Vardorvis 25, Leviathan 25, Whisperer 25, Duke 24), two `bounty_task`, three `preferred_method`, and 12 unknown. Consumers decide the unknown distribution explicitly. Ordinary scalars/ranges and note eligibility retain their existing behavior. Quantity-note reading selects amounts only; it does not widen the unrelated generic quest/location note classifier.

## Paired drops

Only exactly two adjacent source rows in one subsection, at the same rate, sharing the named dropped-together reference and source eligibility, become one main-table slot. The partner becomes `bonus_drops` with its item, amount, and noted flag. Unresolved/filtered rows cannot turn a three-row run into a pair or join separated rows. Different conditions, unresolved partner quantities, and partner quantity alternatives remain separate because the compact bonus shape cannot represent them faithfully.

Source pairing changes these pool sizes: Nex 14 to 12; Zilyana 133 to 127; K'ril 136 to 127; Ammonite Crab 129 to 128; Chaos Fanatic 137 to 133. Kree'arra and Ancient Zygomite retain their pool denominators. Remaining weights stay unchanged; probability changes follow removal of duplicate partner slots. Scavenger beast's three-row run remains separate. No boss-specific correction table is used.

## Regeneration and preservation

Base: upstream `41cecd6fc3167844ba057b09c49f2594f3813ca8`. Complete runs over 1,659 cached pages preserve all 3,092 NPC records and 1,112 table identities. The source port changes 85 tables: the 116 alternative rows, four comment-bearing quantity rows (Hydra variants and Zulrah scales), seven bundled tables, and 114 pre-roll rates across 66 tables. No generic note change or unrelated main-table weight is introduced. Rows decrease from 16,551 to 16,541 because ten partner rows become bonuses.

Uniformly explicit `dropversion=Post-quest` table headers select the matching infobox versions rather than every NPC sharing the page. The excluded quest records remain present with empty `tables` arrays. This corrects three mappings: Amoxliatl quest guardian 13686 and Dragon Slayer II Vorkath states 8058/8060. Amoxliatl 13685 and post-quest Vorkath 8059/8061 keep their tables. The original Wiki structure explicitly declares those versions; cache IDs/combat levels agree. Other header families or mixed/missing version headers retain their previous inheritance behavior. Crocodile and Moss giant inherited variants have regression coverage. No NPC-specific override is used.

The pre-roll serializer previously lost the parsed denominator, making a complete canonical import lose TSPS's explicit Thermy 1/350 rate. It now exports each pre-roll's own source ratio. Twelve Hydra-family rows use decimal denominators: `1/181.1` becomes `10/1811`, `1/360.72` becomes `100/36072`, and `1/1800.72` becomes `100/180072`. The ratio is exact; integer source slots such as `4/540` remain unreduced so peer rows still share their source pool. Zero-denominator or over-one probabilities retain raw provenance without executable odds. No general main-table denominator algorithm is changed.

Two complete outputs match byte-for-byte:

| File | SHA-256 |
|---|---|
| `npc-drops.json` | `5fe1ca11fde74497fb3f6b0a50fa30fe00a60d3f3245619fed1ef8cf9fd4aa8f` |
| `subtables.json` | `8203ba99d9090808e27107bb432a2e2dd44f9868acdaff2f95a2e6a35c632a0c` |
| `unresolved-items.json` | `7abbfe34cb6e64fe38b75cba18e76ae14acacb1f7e678e21a30e838f4268537c` |

The latter two files are unchanged from the baseline. Regenerate with `python -m scripts.drops.update --out <directory>`, compare all three output files, and import the exact generated bytes. Generated output must never be patched or merged by hand.

## Existing differences from TSPS's older import

The final export differs in 87 tables from TSPS upstream `e7ff37b61`, not just the 85 changed against canonical base. Five canonical/base table discrepancies predate this source work: Nex's source pairing is repaired here and now exactly matches TSPS; Bandit champion already exports three inventory-conditional rows instead of TSPS's one; both Mimic NPC tables already contain only the guaranteed plank instead of 30 reward rows; canonical Thermy's occult necklace previously lacked an explicit `out_of`, now repaired by the generic pre-roll serializer. The Amoxliatl quest mapping now agrees with TSPS's existing empty mapping. Vorkath quest records 8058/8060 remain present but now correctly have no regular loot; these are the only two NPC mapping differences against that TSPS import.

A downstream complete import must verify its existing Mimic reward takeover, Bandit champion inventory eligibility, and exact pre-roll execution. These are consumer integration requirements, not claims that this parser change introduces those older canonical reward/eligibility differences. The data remains a source export with existing assumptions/unresolved items, not a certification of every current OSRS rate.

## Verification

Focused regressions cover source-listed quantities, unknown distributions, source conditions, unresolved and condition-mismatched bundles, integer and decimal pre-rolls, probability boundaries, malformed/unpublished rates, schema validation, and real generated corpus guards. Independent source review found the unresolved-adjacency and partner-eligibility cases; both were reproduced failing and then repaired.

Final full pytest: **241 passed, one pre-existing failure**, `test/test_dialogue_hooks.py::test_generated_exports` for the While Guthix Sleeps audited fingerprint. This change does not touch dialogue source or output. All drop/schema/corpus regressions pass. Black formatting and `git diff --check` pass. Use an explicit workspace `--basetemp` when sandbox temporary-directory permissions prevent pytest fixtures from initializing.
