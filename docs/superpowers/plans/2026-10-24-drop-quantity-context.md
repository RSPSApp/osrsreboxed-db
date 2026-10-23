# Conditional drop quantity prerequisite implementation plan

> **For agentic workers:** Execute inline using superpowers:executing-plans.

**Goal:** Export executable source-listed quantities and conditions for the TSPS quantity consumer and Vardorvis perfect-kill producer.

**Architecture:** Extend the existing drop parser, resolved entries, and schema on upstream master. Parse alternatives rather than concatenate digits; type only explicit page/row statements. Preserve source-declared dropped-together pairs during complete regeneration, without adopting unrelated reward, clue, roll, or mapping changes from local branches.

**Tech Stack:** Python, mwparserfromhell, pytest, JSON Schema.

**Spec:** `scripts/drops/QUANTITY_CONTEXT.md` records the contract and source evidence.

## Global constraints

- Never manually modify generated JSON; regenerate from canonical source.
- Repeat generation from unchanged inputs must be byte-identical.
- Preserve NPC records, table identities, and unrelated rates; any corrected loot mapping must follow explicit source versions and be disclosed.
- Work only in this isolated worktree; other agents own clue and consumer work.

## Review focus

- Quantity comments must not become digits; leading-zero comma tokens remain unresolved.
- Conditional quantities require explicit source statements, not arithmetic inference.
- A rarity bounty footnote must not become a quantity condition.
- Paired rows require the same named drop-group footnote, subsection, and rate; triples stay separate.
- Complete regeneration must not silently remove upstream mappings, Nex bundles, or reward rows.

## Tasks

- [x] Establish baseline: full pytest and complete cached-input export; record any pre-existing drift.
- [x] Add and run failing quantity/condition/bundle tests against upstream source.
- [x] Adapt the relevant parser/schema code narrowly; run the focused regressions and existing drop tests.
- [x] Generate the complete artifact twice, compare bytes, inspect every semantic difference from baseline and committed upstream output; add corpus preservation guards.
- [x] Run full pytest, review source/artifact diffs, record evidence, and prepare separate source/data commits for one canonical prerequisite PR.

## Execution ledger

- Base: fresh `origin/master` 41cecd6fc3167844ba057b09c49f2594f3813ca8.
- Ruling: execution was explicitly assigned by the orchestrator; proceed without a second plan approval.
- Ruling: use workspace-local Python dependencies with the bundled Python 3.12 interpreter; WindowsApps aliases are unavailable.
- Baseline: 151 passed, one pre-existing dialogue fingerprint failure, three sandbox temporary-directory fixture errors. Explicit workspace basetemp removes the environment errors.
- Ruling: quantity-note parsing selects typed amounts only; do not widen the old generic quest classifier. An activity-note regression proves generic eligibility stays unchanged.
- Independent review: unresolved source rows could create false adjacency; mismatched partner eligibility could disappear. Six new regressions reproduced both failures, then passed after source-run identity and eligibility checks.
- Ruling: a complete import must retain explicit pre-roll denominators. Add a narrow serializer repair with exact decimal source ratios, not the older broad roll-metadata refactor. Integer pool slots remain unreduced.
- Final deterministic pair: `.runtime/upstream-review/drop-context-release-a` and `-b`; npc-drops SHA-256 `5fe1ca11fde74497fb3f6b0a50fa30fe00a60d3f3245619fed1ef8cf9fd4aa8f`. Complete machine comparison and exact cross-multiplication evidence: `.runtime/upstream-review/drop-context-final-comparison.json` in the parent workspace.
- Preservation: 3,092 NPC records and 1,112 canonical table identities retained; 85 changed tables consist only of quantities, paired-slot arithmetic, and exact pre-roll metadata. The older TSPS import has 87 differing tables. See `scripts/drops/QUANTITY_CONTEXT.md` for consumer requirements and corrected quest mappings.
- Ruling after downstream integration failure: canonical Amoxliatl's inherited quest loot is wrong, not a preservation target. Honor uniformly explicit post-quest headers, carry excluded NPC IDs through parser/spec to aggregator, and keep empty records rather than losing IDs. Source also explicitly excludes Vorkath's Dragon Slayer II versions. Add real source/cache and inherited-version regressions before implementation; regenerate twice and reclassify mappings. No hand edit or NPC-specific override.
- Final mapping review clear: parser/spec exclusion metadata only retains record existence and never erases tables independently assigned by another source table. Real Amoxliatl/Vorkath and inherited-variant regressions pass. Exactly three canonical mappings become empty; against TSPS only the two Vorkath quest mappings change, while Amoxliatl now matches its existing quest exclusion.
- Final full pytest against release bytes: 241 passed, one unchanged While Guthix Sleeps fingerprint failure (`test/test_dialogue_hooks.py::test_generated_exports`), 124.47 seconds. No sandbox fixture errors with workspace basetemp. Black-compatible formatting and whitespace checks pass. Source and generated data are committed separately in one canonical prerequisite PR; the known baseline dialogue failure is disclosed rather than changing another agent's domain.
