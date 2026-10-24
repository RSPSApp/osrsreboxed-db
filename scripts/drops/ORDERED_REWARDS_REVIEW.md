# Ordered Forgotten Four rewards

The canonical Wiki overview on Duke Sucellus, The Leviathan, The Whisperer and Vardorvis states a replacement chain: tradeable uniques, orb, first-only tablet, quartz, supply bundle, then resources. The parser validates that structural contract and the published unique distribution rather than matching NPC IDs. Source material is the checked-in monster Wiki page-text cache.

Jagex's [Desert Treasure II tweaks and drop rates](https://secure.runescape.com/m=news/desert-treasure-ii---tweaks-and-drop-rates?oldschool=1) establishes that failed accesses always reach resources. The cached resource rows total 78/100 and contain no Nothing outcome. We infer the conditional resource distribution by retaining their integer relative weights and setting the accessed pool denominator to their sum (78). Each row retains `published_rarity` and declares `weight_basis: conditional_pool`. This is an explicit inference from the guaranteed fallback, not a newly asserted absolute per-kill rate. No missing resource item or Nothing outcome is invented.

A unique-table hit chooses one of 24 slots: nine vestige progress, nine chromium ingot, three boss weapon component and one for each Virtus piece. Vestige progress awards one gold ring, then two gold rings, then the vestige, resetting on the third hit. State is per player and canonical boss table.

Pets roll independently. The four clue tiers are one exclusive tertiary group with total access 1/40. Supplies resolve as one bundle. Existing perfect-kill resource quantity conditions remain executable by the consumer.

Tablet and quartz pre-first-receipt scaling is unresolved. Tablet executes the documented 1/25 base. Quartz executes 1/200 before 300 recorded kills, the documented 1/50 endpoint at 300 or more recorded kills before first receipt, and 1/200 after first receipt. No intermediate interpolation is invented. The provider queries the canonical Combat Achievements count as recorded when rewards roll, without adding a guessed current-kill offset. First receipt is persisted from rewards only; ownership does not infer historic receipts. The runtime validates state before RNG and commits only after the complete reward outcome resolves, failing closed when the provider or saved state is invalid.

Validation: corpus and schema regressions cover all four tables; whole exports run twice from the same inputs must match byte-for-byte. The import preserves all 3,092 NPC mappings and 1,112 tables, changing only the four tables above.
