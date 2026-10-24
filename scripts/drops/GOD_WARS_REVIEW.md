# God Wars variant tables and exact exclusive loot pools

## Scope and dependencies

This fixes source parsing/export for `{{GWDRDT}}`, its variant rare/gem/mega-rare tables, and the generals' mutually exclusive main loot. It depends on [canonical #14](https://github.com/RSPSApp/osrsreboxed-db/pull/14). The companion TSPS import depends on [TSPS #882](https://github.com/RSPSApp/tsps/pull/882) for the safe quantity/reward import. Neither prerequisite was merged when work started; their original commits are preserved as explicit branch ancestors. Review the God Wars commits separately from those prerequisites.

The original local branches had never become PRs. Their old integer coin remainders 29/30/34/42 are not the release model: they wrongly allocated omitted unique probability and rounded unique-table coins to ordinary coins.

## Source evidence

Inputs are the checked-in monster Wiki text and `data/drops/drop-tables-wiki-page-text.json`. The latter adds the cached [God Wars Dungeon-variant rare drop table](https://oldschool.runescape.wiki/w/God_Wars_Dungeon-variant_rare_drop_table) page; its existing regular Drop table source is byte-identical. This is cached-source evidence, not a claim of a fresh crawl.

- [Template:GWDRDT](https://oldschool.runescape.wiki/w/Template:GWDRDT) and the variant page specify 8/127 to the variant RDT and 2/127 to the variant gem table. The RDT can reach the gem and mega-rare tables; gem can reach mega-rare. Each variant table has 128 occupied slots. They differ from regular tables, including rune sword and coin-filled outcomes, and ring of wealth has no effect.
- The four general pages put uniques in main loot. For example, Graardor's three specific armour rates 1/381 together occupy 1/127; his hilt is 1/508 and three shard rates 1/762 sum to 1/254. Moving these into independent rolls preserves individual numbers but permits multiple exclusive loot outcomes.
- Graardor and Kree's unique-table Coins have a source rate 1.25/127. Integer rounding to 1/127 loses probability. The ordinary coin footnotes say their displayed rates include gem/RDT coins; Zilyana and K'ril additionally name unique-table coins.

## Exact pool arithmetic

The normalizer runs only for the structural pair of God Wars accesses and requires exactly one explicit inclusive-coin source footnote. It reads every main probability using `Fraction`, with no float rounding. The common denominator is LCM(127,381,508,762)=1,524. Thus each 1/381 unique becomes 4/1524, 1/508 becomes 3/1524, 1/762 becomes 2/1524, and unique Coins 1.25/127 become 15/1524. Variant accesses are 96/1524 and 24/1524. All remain one exclusive weighted main outcome; supply pairs remain bonuses of that outcome. Guaranteed, pre-roll, and tertiary behavior remains separate.

After subtracting all exact non-inclusive outcomes and shared accesses, ordinary coin weights are:

| General | Integer weight /1524 | Equivalent /127 | Source displayed inclusive rate |
|---|---:|---:|---:|
| Zilyana |330|27.5|31.2/127|
| Graardor |336|28|31.7/127|
| K'ril |396|33|36.7/127|
| Kree'arra |480|40|43.7/127|

This is checked against the nested source routes, rather than tuned to the displayed numbers. Let M=113/128, G=63/128+(1/128)M, and R=20/128+(20/128)G+(15/128)M. The accesses contribute 8R+2G=242461/65536≈3.699661 source slots/127. Adding this to the four direct coin rates reproduces their published one-decimal displays. `published_rarity` retains each normalized row's original source rate; the inclusive coin additionally has `weight_basis: remainder`.

Unsupported, assumed or unresolved main rates, a missing/ambiguous inclusive coin footnote, or an incoherent residual stop generation with source context. Ordinary/partial RDT or gem accesses do not activate this model. No NPC-ID or item-specific override is used. The world's optional rare multiplier still applies according to its existing independent-roll rules; these source-stated main uniques are correctly represented as main loot.

## Complete export verification

Against the verified prerequisite baseline, only four general tables, the direct shared-reference metadata, and three new variant subtables change. All 3,092 NPC mappings, 1,112 table identities, other tables, quantities, notes, bonuses, regular shared tables and unresolved output remain unchanged. Twenty-five formerly independent unique rows retain their exact marginal probabilities in the exclusive pool; the two unique coin fractions are restored. Source-only quest records 8058/8060/13686 remain empty; exact pre-rolls, Nex pairs, Mimic data and Bandit champion ownership data remain intact.

Two complete cached-input generations match byte-for-byte:

| Output | SHA-256 |
|---|---|
|npc-drops.json|`cecdb21e757007a75893b721ae9a81d283ba62c6cc409cfe808dd9af8120068f`|
|subtables.json|`70cfdff188712ed9321f6bfaed89de16e352b81ac7ffb2cb0dffbc13fa8203f3`|
|unresolved-items.json|`7abbfe34cb6e64fe38b75cba18e76ae14acacb1f7e678e21a30e838f4268537c`|

Regenerate with `python -m scripts.drops.update --out <directory>` and compare every output. No generated file is patched or hand-merged. Existing unrelated source approximations outside these four pools are not certified by this fix.

## Validation

The final canonical suite reports **358 passed, one pre-existing failure**: `test/test_dialogue_hooks.py::test_generated_exports` for While Guthix Sleeps' audited fingerprint. The baseline has the same failure. Workspace temporary directories avoid Windows sandbox fixture permissions; the reward-casket tests then pass without source changes. All drop/schema/corpus checks pass, including 59 focused God Wars/bundle regressions. Independent review of the corrected exact model is clear. The companion runtime probes pass and its full suite is recorded in the TSPS PR.
