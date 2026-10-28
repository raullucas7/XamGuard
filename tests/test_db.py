import sqlite3

import pytest

from xamguard import db


@pytest.fixture
def database():
    """A throwaway database that only exists in memory."""
    database = db.Database(":memory:")
    yield database
    database.close()


def count(database, table):
    return database.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------- setup ----------

def test_all_the_tables_are_created(database):
    rows = database.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    tables = {name for (name,) in rows}
    assert {"loadouts", "sites", "apps", "loadout_sites", "loadout_apps"} <= tables


def test_foreign_keys_are_really_enforced(database):
    # sqlite only checks these if PRAGMA foreign_keys = ON was run for the connection
    with pytest.raises(sqlite3.IntegrityError):
        database.conn.execute("INSERT INTO loadout_sites (loadout_id, site_id) VALUES (999, 999)")


def test_opening_twice_does_not_crash_or_wipe_anything(tmp_path):
    path = str(tmp_path / "x.db")
    first = db.Database(path)
    first.save_loadout("Study", ["a.com"])
    first.close()

    second = db.Database(path)  # tables already exist
    assert second.get_loadout("Study")["sites"] == ["a.com"]
    second.close()


def test_default_path_uses_the_data_dir_and_creates_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XAMGUARD_DATA_DIR", str(tmp_path / "data"))

    path = db.default_path()

    assert path == str(tmp_path / "data" / "xamguard.db")
    assert (tmp_path / "data").is_dir()


# ---------- saving and reading ----------

def test_save_then_get_returns_clean_sorted_names(database):
    stored = database.save_loadout(
        "Study",
        ["YouTube.com", "https://www.reddit.com/r/python", "twitter.com", "youtube.com"],
        apps=["Spotify.exe", " chrome ", "chrome"],
    )

    assert stored == "Study"
    assert database.get_loadout("Study") == {
        "name": "Study",
        "sites": ["reddit.com", "twitter.com", "youtube.com"],
        "apps": ["chrome.exe", "spotify.exe"],  # "chrome" got its .exe
    }


def test_unknown_loadout_is_none(database):
    assert database.get_loadout("Nope") is None


def test_names_are_not_case_sensitive(database):
    database.save_loadout("Study", ["a.com"])
    assert database.get_loadout("study")["name"] == "Study"
    assert database.get_loadout("  STUDY ")["sites"] == ["a.com"]


def test_names_come_back_sorted_ignoring_case(database):
    for name in ["banana", "Apple", "cherry"]:
        database.save_loadout(name, [])
    assert database.loadout_names() == ["Apple", "banana", "cherry"]


def test_saving_again_replaces_what_was_in_it(database):
    database.save_loadout("Study", ["a.com", "b.com"], apps=["x.exe"])
    database.save_loadout("Study", ["c.com"])

    assert database.get_loadout("Study") == {"name": "Study", "sites": ["c.com"], "apps": []}
    assert database.loadout_names() == ["Study"]


def test_saving_with_different_capitals_updates_the_same_loadout(database):
    database.save_loadout("Study", ["a.com"])
    database.save_loadout("study", ["b.com"])
    assert database.loadout_names() == ["study"]
    assert database.get_loadout("study")["sites"] == ["b.com"]


def test_an_empty_loadout_is_allowed(database):
    database.save_loadout("Empty", [])
    assert database.get_loadout("Empty")["sites"] == []


def test_blank_entries_are_ignored(database):
    database.save_loadout("Study", ["a.com", "", "   "], apps=["", " "])
    assert database.get_loadout("Study") == {"name": "Study", "sites": ["a.com"], "apps": []}


# ---------- bad input changes nothing ----------

def test_one_bad_site_saves_nothing_new(database):
    with pytest.raises(ValueError, match="not a valid website"):
        database.save_loadout("Fresh", ["good.com", "bad site"])
    assert database.loadout_names() == []
    assert count(database, "sites") == 0


def test_one_bad_site_leaves_an_existing_loadout_alone(database):
    database.save_loadout("Study", ["a.com"])

    with pytest.raises(ValueError):
        database.save_loadout("Study", ["good.com", "bad site"])

    assert database.get_loadout("Study")["sites"] == ["a.com"]


@pytest.mark.parametrize("name", ["", "   "])
def test_a_loadout_needs_a_name(database, name):
    with pytest.raises(ValueError, match="name"):
        database.save_loadout(name, ["a.com"])


def test_hostile_names_are_just_text(database):
    """Values go in through ? placeholders, so they can't run as SQL."""
    nasty = "Bob's'); DROP TABLE sites;--"
    database.save_loadout(nasty, ["a.com"])

    assert database.get_loadout(nasty)["sites"] == ["a.com"]
    assert count(database, "sites") == 1  # the table is still there


# ---------- renaming ----------

def test_rename_by_saving_with_old_name(database):
    database.save_loadout("Study", ["a.com"])

    stored = database.save_loadout("Focus", ["a.com", "b.com"], old_name="Study")

    assert stored == "Focus"
    assert database.loadout_names() == ["Focus"]
    assert database.get_loadout("Focus")["sites"] == ["a.com", "b.com"]
    assert database.get_loadout("Study") is None


def test_rename_to_a_name_that_exists_fails_and_changes_nothing(database):
    database.save_loadout("Alpha", ["a.com"])
    database.save_loadout("Beta", ["b.com"])

    with pytest.raises(ValueError, match="already exists"):
        database.save_loadout("alpha", ["c.com"], old_name="Beta")

    assert database.get_loadout("Alpha")["sites"] == ["a.com"]
    assert database.get_loadout("Beta")["sites"] == ["b.com"]


def test_rename_of_something_that_does_not_exist_fails(database):
    with pytest.raises(ValueError, match="no loadout called"):
        database.save_loadout("New", ["a.com"], old_name="Missing")
    assert database.loadout_names() == []


def test_changing_only_the_capitals_of_a_name_is_a_rename(database):
    database.save_loadout("study", ["a.com"])
    database.save_loadout("Study", ["a.com"], old_name="study")
    assert database.loadout_names() == ["Study"]


# ---------- deleting ----------

def test_delete_removes_the_loadout_and_its_links(database):
    database.save_loadout("Study", ["a.com"], apps=["x.exe"])

    assert database.delete_loadout("Study") is True

    assert database.get_loadout("Study") is None
    assert count(database, "loadout_sites") == 0
    assert count(database, "loadout_apps") == 0


def test_deleting_something_that_is_not_there_returns_false(database):
    assert database.delete_loadout("Nope") is False


def test_delete_keeps_sites_that_other_loadouts_still_use(database):
    database.save_loadout("One", ["x.com", "shared.com"])
    database.save_loadout("Two", ["shared.com"])

    database.delete_loadout("One")

    assert database.get_loadout("Two")["sites"] == ["shared.com"]
    rows = database.conn.execute("SELECT url FROM sites").fetchall()
    assert rows == [("shared.com",)]  # x.com was used by nobody, so it's gone


# ---------- apps inside a loadout ----------

def test_apps_in_a_loadout_are_cleaned_and_deduped(database):
    database.save_loadout("Study", [], apps=["Spotify", "spotify.exe", " STEAM "])
    assert database.get_loadout("Study")["apps"] == ["spotify.exe", "steam.exe"]


def test_a_protected_app_cannot_go_in_a_loadout_and_nothing_is_saved(database):
    with pytest.raises(ValueError, match="protected"):
        database.save_loadout("Study", ["a.com"], apps=["spotify", "explorer"])
    assert database.loadout_names() == []


# ---------- apps that are blocked right now ----------

def test_block_apps_returns_what_was_added_and_cleans_names(database):
    added = database.block_apps(["Spotify", "steam.exe", "SPOTIFY.EXE", ""])

    assert added == ["spotify.exe", "steam.exe"]
    assert database.app_blocks_until() == {"spotify.exe": None, "steam.exe": None}


def test_blocking_an_app_again_keeps_the_first_end_time(database):
    database.block_apps(["a.exe"], until=1000)

    assert database.block_apps(["a.exe"], until=9000) == []
    assert database.app_blocks_until() == {"a.exe": 1000}


def test_one_bad_app_name_adds_nothing(database):
    with pytest.raises(ValueError):
        database.block_apps(["spotify", "explorer"])
    assert database.app_blocks_until() == {}


def test_block_apps_stores_a_whole_number_for_the_end_time(database):
    database.block_apps(["a.exe"], until=1_000_300.7)
    assert database.app_blocks_until() == {"a.exe": 1000300}


def test_unblock_apps_returns_only_the_ones_that_were_blocked(database):
    database.block_apps(["a.exe", "b.exe"])

    assert database.unblock_apps(["A", "never-blocked", "  "]) == ["a.exe"]  # "A" finds a.exe
    assert database.app_blocks_until() == {"b.exe": None}


def test_unblocking_never_complains_about_a_name(database):
    assert database.unblock_apps(["explorer", "bad*name"]) == []


def test_unblock_expired_apps_removes_only_what_is_due(database):
    database.block_apps(["done.exe"], until=1000)
    database.block_apps(["later.exe"], until=5000)
    database.block_apps(["forever.exe"])

    assert database.unblock_expired_apps(now=2000) == ["done.exe"]
    assert database.app_blocks_until() == {"later.exe": 5000, "forever.exe": None}


def test_the_exact_end_second_counts_as_up_for_apps(database):
    database.block_apps(["a.exe"], until=1000)
    assert database.unblock_expired_apps(now=999) == []
    assert database.unblock_expired_apps(now=1000) == ["a.exe"]


def test_unblock_expired_apps_uses_the_real_clock_by_default(database):
    database.block_apps(["old.exe"], until=1)  # 1970
    database.block_apps(["far.exe"], until=9_999_999_999)  # year 2286
    assert database.unblock_expired_apps() == ["old.exe"]


def test_active_app_blocks_are_separate_from_loadouts(database):
    database.save_loadout("Study", [], apps=["spotify.exe"])
    database.block_apps(["spotify.exe"])

    database.delete_loadout("Study")

    assert database.app_blocks_until() == {"spotify.exe": None}  # still blocked right now


# ---------- persistence ----------

def test_app_blocks_survive_closing_and_reopening(tmp_path):
    path = str(tmp_path / "x.db")
    first = db.Database(path)
    first.block_apps(["spotify.exe"], until=5000)
    first.close()

    second = db.Database(path)
    assert second.app_blocks_until() == {"spotify.exe": 5000}
    second.close()


def test_an_older_database_gets_the_new_table_when_opened(tmp_path):
    """Your real database was made before app_blocks existed."""
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    for query in db.SCHEMA[:-1]:  # every table except the newest one
        old.execute(query)
    old.execute("INSERT INTO loadouts (name) VALUES ('we gotta lock in')")
    old.commit()
    old.close()

    database = db.Database(path)

    assert database.loadout_names() == ["we gotta lock in"]  # nothing was lost
    assert database.app_blocks_until() == {}  # and the new table works
    database.close()


def test_loadouts_survive_closing_and_reopening(tmp_path):
    path = str(tmp_path / "x.db")
    first = db.Database(path)
    first.save_loadout("Study", ["a.com"], apps=["x.exe"])
    first.close()

    second = db.Database(path)
    assert second.get_loadout("Study") == {"name": "Study", "sites": ["a.com"], "apps": ["x.exe"]}
    second.close()
