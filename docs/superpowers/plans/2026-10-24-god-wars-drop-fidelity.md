# God Wars drop fidelity implementation plan

> **For agentic workers:** Execute inline using superpowers:executing-plans. Root assigns independent review before publication.

**Goal:** Publish the missing canonical and TSPS God Wars variant-table/coin-remainder fixes as separately tested PRs.

**Architecture:** Build from fresh upstream bases while explicitly integrating pending canonical #14 and TSPS #882 prerequisites. Port only source parsing/shared-page export and coin-remainder behavior from the old local God Wars branches, regenerate complete outputs twice, and import the exact bytes into TSPS. Preserve integer/exact pre-rolls, source quantity conditions, paired supplies, no-loot quest variants, and existing reward ownership.

**Tech stack:** Python/mwparserfromhell/pytest; TypeScript server with JavaScript plugin and Node tests.

**Spec:** `scripts/drops/GOD_WARS_REVIEW.md` records source evidence and the final contract.

## Constraints

- No manual edit, subtree copy, conflict hand-merge or post-generation patch to generated exports.
- No clue/client/live-game/save/deployment changes. Other agents own boss implementations.
- Preserve old branches and PR #14/#882 commits. Pending dependencies must be explicit in PR descriptions.
- Keep all non-God-Wars drop semantics unchanged against the verified prerequisite baseline; compare every export field, not just counts.
- Source identity and rates come from the checked-in Wiki corpus and cached shared-page text, never another server.

## Review focus

- Variant RDT/gem/mega-rare tables must resolve to variant keys, not regular equivalents.
- Every shared table slot must land; ring of wealth must not alter God Wars variants.
- Coin remainders require the source's inclusive GDT/RDT footnote and a coherent shared pool; unrelated coin rows stay published.
- Pair slots, exact pre-roll fractions and all quest-only empty NPC mappings must survive full regeneration.
- Current upstream and pending prerequisite changes must not be silently replaced with the older broad local dump.

## Tasks

- [x] Audit PRs in all states across upstreams/forks; check exact branch and commit ancestry.
- [x] Create clean upstream-based branches and preserve/integrate pending prerequisite commits.
- [x] Establish canonical/server baseline and save source/corpus evidence.
- [x] Port GWD regression tests first, observe missing-template/subtable/remainder failures, then adapt only required parser/export/schema/cache-input code.
- [x] Regenerate full output twice and classify all semantic changes against canonical prerequisite and TSPS prerequisite.
- [x] Extend the existing TSPS import preservation tests; prove runtime variant slots/wealth behavior and exact coin pools.
- [x] Run full canonical and TSPS suites/build, obtain independent review, resolve findings with failing regressions.
- [x] Commit/push and publish separately reviewed canonical and TSPS PRs, attach both.

## Audit and execution ledger

- 2026-10-24: no PR found for old `fix/gwd-rare-drop-table` in any state across RSPSApp/tsps, RSPSApp/osrsreboxed-db, or either UnhealthyKraken fork. Broad God Wars/gwd/coin-remainder searches find unrelated older content PRs only. GitHub does not know old local tip commits `77f32b605` and `7ff4b112`; neither is in upstream ancestry.
- Fresh canonical `origin/master`: `aecaa3c2` (clue-casket #13 merged). Fresh TSPS `origin/main`: `106b6f141`. Canonical #14 and TSPS #882 remain open.
- Ruling: create new branches from those fresh refs, then merge the original pending prerequisite commits instead of blindly publishing the old God Wars branch. This preserves reviewed ancestry and makes dependency scope explicit.
- Old God Wars source references: `e20375dd`, `1fff3dff`; generated reference commits `37df98b7`, `16e3bedc`; old TSPS imports `e6c84ac62`, `77f32b605`. These are references for a source-scoped port, not release artifacts.
- Important source finding: the old integer remainder29/30/34/42 is not correct. Main uniques at1/381,1/508,1/762 were moved into independent rolls; unique-table Coins1.25/127 were rounded to1/127. Their omitted probability was incorrectly awarded as ordinary coins. Exact variant coin routes contribute approximately3.6994 source slots/127; old remainders do not reproduce published blends31.2/31.7/36.7/43.7.
- Approved bounded correction: where BOTH God Wars variant accesses and the explicit inclusive coin footnote identify the source model, normalize every main source fraction into one exclusive integer pool. LCM(127,381,508,762)=1524; preserve exact marginal rates and published source metadata, keep guaranteed/pre-roll/tertiary paths separate, and fail closed with source context for unsupported or unresolved main rows. No NPC-specific overrides. Correct normal coin weights are330/1524,336/1524,396/1524,480/1524 (27.5/28/33/40 over127). Shared accesses are96/1524 and24/1524. Independent roll probes and exact coin-route rounding must establish behavior before publication.
- Final exact source coin-route contribution:242461/65536≈3.699661 source slots/127; exact computation, not the earlier rough decimal, is used by the proof. All four one-decimal published blends match.
- Final canonical verification:358 passed, one unchanged While Guthix Sleeps fingerprint failure. Reward-casket baseline TEMP permission failures disappear with a workspace temp directory; no clue source changes. Independent re-review of exact normalization and runtime probes is clear.
- Full export pair `gwd-exact-a`/`gwd-exact-b`: NPC SHA-256 `cecdb21e757007a75893b721ae9a81d283ba62c6cc409cfe808dd9af8120068f`; subtables `70cfdff188712ed9321f6bfaed89de16e352b81ac7ffb2cb0dffbc13fa8203f3`. Machine comparison in the parent workspace `.runtime/upstream-review/gwd-exact-comparison.json` proves only four tables/new variant subtables/direct refs change, with quantities/notes/pairs/mappings/other data preserved.
- TSPS runtime red-to-green probe:old model produced7 main drops under the deterministic kill; exact model produces one unique. All128slots of every variant table match with/without wealth. Twenty-six focused integration tests pass. Full server suite runs with isolated temporary fixtures and concurrency4 before its companion PR publishes.
- Publication complete: [canonical #15](https://github.com/RSPSApp/osrsreboxed-db/pull/15) and [TSPS #888](https://github.com/RSPSApp/tsps/pull/888) are open, non-draft, and attached. Original pending prerequisites #14/#882 remain explicit ancestors and links; old local branches are preserved.
- Final TSPS result: 4,945 passed, two disclosed environment failures (`browser-host-bridge.test.cjs:105` timing and `core-disconnect-guards.test.cjs:238` sandbox localhost EACCES). Both complete files pass 44/44 when re-run serial outside the sandbox against the same code/data. Player-save fixtures pass 28/28 with workspace TEMP. No God Wars/loot failure, and no false claim of a green full-suite run.
