# Exclude stale monster pages from drop exports

Use the existing monster category title listing as the authoritative set of pages,
as the shop pipeline already does. The raw text cache is incremental and retains
old titles after renames. The Wiki's `Shellbane_Gryphon?action=raw` now redirects
to `Shellbane gryphon`; only the latter occurs in the category listing.

1. Add failing loader regressions in `test/test_drops_dump.py`: exclude an obsolete
   title, retain separate currently listed encounters sharing NPC IDs, and refuse
   missing/empty listings instead of silently exporting stale data or no drops.
2. Filter `load_monster_wikitext` in `scripts/drops/update.py` against the listing.
   Preserve case and page identities. Do not deduplicate by NPC ID or name.
3. Regenerate the three drop exports using unchanged source inputs. Audit all
   removed tables and compare two complete dumps byte for byte. Run drop tests.
4. Review and publish the source PR; import generated artifacts into an isolated
   TSPS branch, test, publish, and integrate selectively into the local game.
   Keep all Claude boss, quest, client and plugin files untouched.

Scope: drop ingestion only; no generic Wiki fetch/monster-builder refactor, no
manual changes to source caches or generated JSON. A current listing does not
prove the cached contents are the latest revision; refreshing those is separate.
