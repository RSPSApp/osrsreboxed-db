import mwparserfromhell
import pytest

from builders.monsters.build_monster import BuildMonster


def parse_status(properties, version=None):
    builder = BuildMonster.__new__(BuildMonster)
    builder.monster_dict = {}
    builder.monster_name = "Status fixture"
    builder.wikitext_found_using = "name"
    builder.infobox_version_number = version
    builder.template = mwparserfromhell.parse(
        "{{Infobox Monster|" + properties + "}}"
    ).filter_templates()[0]
    builder.populate_monster_properties_from_wiki_data()
    return builder.monster_dict


@pytest.mark.parametrize(
    "properties, expected",
    [
        ("poisonresistance=0|venomresistance=Poison", (False, True)),
        ("poisonresistance=100|venomresistance=100", (True, True)),
        ("poisonresistance=200|venomresistance=200", (True, True)),
        ("poisonresistance=0|venomresistance=0", (False, False)),
        ("immunepoison=Yes|immunevenom=Yes", (True, True)),
        (
            "poisonresistance=0|venomresistance=0|immunepoison=Yes|immunevenom=Yes",
            (False, False),
        ),
    ],
)
def test_current_resistance_fields_and_legacy_aliases(properties, expected):
    result = parse_status(properties)
    assert (result["immune_poison"], result["immune_venom"]) == expected


def test_versioned_resistance_wins_over_shared_and_legacy_values():
    result = parse_status(
        "poisonresistance=100|venomresistance=100|"
        "poisonresistance2=0|venomresistance2=Poison|"
        "immunepoison2=Yes|immunevenom2=No",
        version=2,
    )
    assert result["immune_poison"] is False
    assert result["immune_venom"] is True


def test_partial_resistance_is_not_falsely_exported_as_full_immunity():
    result = parse_status("poisonresistance=50|venomresistance=25")
    assert result["immune_poison"] is False
    assert result["immune_venom"] is False


def test_dedicated_export_uses_canonical_builder_and_excludes_unresolved_source():
    from scripts.monsters.status_immunities import build_status_immunities

    class Monster:
        def __init__(self, key):
            self.key = key

        def preprocessing(self):
            return self.key != "9", "missing source"

        def populate_monster(self):
            self.monster_dict = {
                "id": int(self.key),
                "name": "Fixture",
                **parse_status("poisonresistance=0|venomresistance=Poison"),
            }

    class Source:
        def _get_entity_id_list(self):
            return ["10", "9", "2"]

        def _build_entity(self, key):
            return Monster(key)

    result = build_status_immunities(Source())
    assert result == {
        "schema_version": 1,
        "npcs": {
            "2": {"name": "Fixture", "immune_poison": False, "immune_venom": True},
            "10": {"name": "Fixture", "immune_poison": False, "immune_venom": True},
        },
    }


def test_status_export_writes_platform_independent_lf(tmp_path, monkeypatch):
    from scripts.monsters import status_immunities

    monkeypatch.setattr(
        status_immunities,
        "build_status_immunities",
        lambda: {"schema_version": 1, "npcs": {}},
    )
    output = tmp_path / "status.json"
    assert status_immunities.export_status_immunities(output) == 0
    assert output.read_bytes() == b'{\n  "schema_version": 1,\n  "npcs": {}\n}\n'
