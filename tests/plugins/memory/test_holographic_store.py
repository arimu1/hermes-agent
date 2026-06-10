"""Tests for the holographic memory store's entity resolution (#43394).

`_resolve_entity` previously used LIKE for the "exact" name match, so `_`
and `%` in entity names acted as wildcards (linking facts to the wrong
entity) and the intended case-insensitive semantics depended on LIKE's
ASCII folding. These tests pin the fixed behaviour: literal matching of
wildcard characters, case-insensitive name/alias resolution, and no
duplicate entity rows for case variants.
"""

import pytest

from plugins.memory.holographic.store import MemoryStore


@pytest.fixture()
def store():
    s = MemoryStore(db_path=":memory:")
    yield s


def _entity_names(store):
    rows = store._conn.execute("SELECT name FROM entities").fetchall()
    return [row["name"] for row in rows]


class TestResolveEntityExactMatch:
    def test_underscore_is_not_a_wildcard(self, store):
        # LIKE wildcards live in the *queried* name: resolving "test_entity"
        # used to match a stored "testXentity" via the `_` wildcard
        id_a = store._resolve_entity("testXentity")
        id_b = store._resolve_entity("test_entity")
        assert id_a != id_b
        assert sorted(_entity_names(store)) == ["testXentity", "test_entity"]

    def test_percent_is_not_a_wildcard(self, store):
        # Resolving "100%" used to match any stored name starting with "100"
        id_a = store._resolve_entity("100x")
        id_b = store._resolve_entity("100%")
        assert id_a != id_b
        assert sorted(_entity_names(store)) == ["100%", "100x"]

    def test_name_with_wildcards_resolves_to_itself(self, store):
        id_a = store._resolve_entity("test_entity")
        assert store._resolve_entity("test_entity") == id_a

    def test_case_insensitive_no_duplicate_rows(self, store):
        id_a = store._resolve_entity("Apple")
        assert store._resolve_entity("APPLE") == id_a
        assert store._resolve_entity("apple") == id_a
        assert _entity_names(store) == ["Apple"]


class TestResolveEntityAliasMatch:
    def _add_entity_with_aliases(self, store, name, aliases):
        cur = store._conn.execute(
            "INSERT INTO entities (name, aliases) VALUES (?, ?)", (name, aliases)
        )
        store._conn.commit()
        return cur.lastrowid

    def test_alias_match_still_works(self, store):
        eid = self._add_entity_with_aliases(store, "Guido van Rossum", "BDFL,Guido")
        assert store._resolve_entity("BDFL") == eid
        assert store._resolve_entity("Guido") == eid

    def test_alias_with_underscore_matches_literally(self, store):
        eid = self._add_entity_with_aliases(store, "Test Framework", "test_fw")
        assert store._resolve_entity("test_fw") == eid

    def test_alias_wildcard_in_query_does_not_false_match(self, store):
        self._add_entity_with_aliases(store, "Test Framework", "testXfw")
        # `_` must not act as a single-char wildcard against alias "testXfw"
        new_id = store._resolve_entity("test_fw")
        rows = store._conn.execute(
            "SELECT entity_id FROM entities WHERE name = ?", ("Test Framework",)
        ).fetchone()
        assert new_id != rows["entity_id"]


class TestAddFactEntityLinking:
    def test_fact_links_to_correct_entity_with_underscore_name(self, store):
        store.add_fact('"test_entity" is a framework', category="tech")
        store.add_fact('"testXentity" is unrelated', category="tech")
        names = sorted(_entity_names(store))
        assert "test_entity" in names
        assert "testXentity" in names
