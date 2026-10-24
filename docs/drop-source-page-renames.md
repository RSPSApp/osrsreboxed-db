# Monster page renames in drop exports

The raw monster wikitext cache is incremental. Old titles survive a Wiki rename
and must not be exported alongside the current category-listed page. Drop loading
now filters using `data/monsters/monsters-wiki-page-titles.json`, with exact title
membership. Separate currently listed encounters remain separate even if their
NPC IDs overlap. Missing/empty listings abort before writing output.

Verified against original Wiki wikitext on 2026-10-24:

| Old title | Current source |
| --- | --- |
| [Shellbane Gryphon](https://oldschool.runescape.wiki/w/Shellbane_Gryphon?action=raw) | redirect to Shellbane gryphon |
| [Manta ray (Sailing)](https://oldschool.runescape.wiki/w/Manta_ray_(Sailing)?action=raw) | redirect to Manta ray (monster) |
| [Mogre (Sailing)](https://oldschool.runescape.wiki/w/Mogre_(Sailing)?action=raw) | redirect to Mogre (sea) |
| [Scorpion (Sailing)](https://oldschool.runescape.wiki/w/Scorpion_(Sailing)?action=raw) | redirect to Scorpion, Level 1 |
| [Snake (Varlamore)](https://oldschool.runescape.wiki/w/Snake_(Varlamore)?action=raw) | redirect to Snake, section 2 |
| [Superior venator](https://oldschool.runescape.wiki/w/Superior_venator?action=raw) | redirect to Blood-starved venator |
| [Hazeel Cultist](https://oldschool.runescape.wiki/w/Hazeel_Cultist?action=raw) | now Infobox NPC, Talk-to; page records removal of attackability |

No source-cache text or generated JSON was manually repaired. Regeneration from
the existing cached inputs excludes 32 obsolete pages: 1,659 to 1,627 scanned,
1,112 to 1,105 tables and 3,092 to 3,086 NPC mappings. Removed NPC mappings are
1207, 12048, 12096, 12097, 12098 (cultists) and 15221 (old manta variant).
Other surviving table contents are unchanged except `shellbane_gryphon`, which now
holds the current lowercase page's 128-slot table formerly suffixed `_2`. NPC
14860 references that single current table rather than choosing the stale
13-slot table first. The existing quest page remains an input; it has no drop
table to export. No assumption that all monsters have only one table is added.

Two complete dumps from unchanged inputs matched byte for byte (including shared
tables and unresolved items). 21 focused loader, parser and generated schema/
reference checks passed. The pre-fix loader failed both new loader regressions.
Independent source review found no important issue.

This repairs stale page selection, not Wiki revision freshness or every drop-rate
mechanic. The retained current-title wikitext is the repository's existing capture;
no claim is made that every cached page reflects today's Wiki revision.
