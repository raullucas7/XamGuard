"""Saved loadouts (named sets of sites and apps) in a small SQLite file."""

import os
import sqlite3
import time

from . import appblocker, hostfileservice

# init tables using IF NOT EXISTS to prevent crash on restart
LOADOUTS = """
CREATE TABLE IF NOT EXISTS loadouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
"""

SITES = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE
);
"""

APPS = """
CREATE TABLE IF NOT EXISTS apps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_name TEXT NOT NULL UNIQUE
);
"""

# Junction table mapping sites to specific loadouts
LOADOUT_SITES = """
CREATE TABLE IF NOT EXISTS loadout_sites (
    loadout_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    FOREIGN KEY(loadout_id) REFERENCES loadouts(id) ON DELETE CASCADE,
    FOREIGN KEY(site_id) REFERENCES sites(id) ON DELETE CASCADE,
    PRIMARY KEY(loadout_id, site_id)
);
"""

# Junction table mapping apps to specific loadouts
LOADOUT_APPS = """
CREATE TABLE IF NOT EXISTS loadout_apps (
    loadout_id INTEGER NOT NULL,
    app_id INTEGER NOT NULL,
    FOREIGN KEY(loadout_id) REFERENCES loadouts(id) ON DELETE CASCADE,
    FOREIGN KEY(app_id) REFERENCES apps(id) ON DELETE CASCADE,
    PRIMARY KEY(loadout_id, app_id)
);
"""

# apps that are blocked right now. a loadout is the recipe, this is what's cooking.
# until = unix time it ends, NULL = stays blocked until you unblock it
APP_BLOCKS = """
CREATE TABLE IF NOT EXISTS app_blocks (
    process_name TEXT NOT NULL PRIMARY KEY,
    until INTEGER
);
"""

SCHEMA = [LOADOUTS, SITES, APPS, LOADOUT_SITES, LOADOUT_APPS, APP_BLOCKS]


def default_path():
    """The database file: %LOCALAPPDATA%\\XamGuard\\xamguard.db (folder made if missing)."""
    folder = os.environ.get("XAMGUARD_DATA_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "XamGuard"
    )
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "xamguard.db")


def stored_name(text):
    """The name an app would be stored under. Doesn't complain, so you can always unblock."""
    try:
        return appblocker.normalizeapp(text)
    except ValueError:
        return text.strip().lower()


class Database:
    def __init__(self, path=None):
        """path=":memory:" gives a throwaway database (the tests use it)."""
        self.conn = sqlite3.connect(default_path() if path is None else path)
        self.conn.execute("PRAGMA foreign_keys = ON")  # sqlite ignores foreign keys unless asked

        with self.conn:
            for query in SCHEMA:
                self.conn.execute(query)

    def close(self):
        self.conn.close()

    def loadout_names(self):
        rows = self.conn.execute("SELECT name FROM loadouts ORDER BY name COLLATE NOCASE")
        return [name for (name,) in rows]

    def get_loadout(self, name):
        """{'name', 'sites', 'apps'}, or None if there's no loadout with that name."""
        row = self.conn.execute(
            "SELECT id, name FROM loadouts WHERE name = ?", (name.strip(),)
        ).fetchone()
        if row is None:
            return None

        loadout_id, stored_name = row
        sites = self.conn.execute(
            "SELECT sites.url FROM sites"
            " JOIN loadout_sites ON loadout_sites.site_id = sites.id"
            " WHERE loadout_sites.loadout_id = ? ORDER BY sites.url",
            (loadout_id,),
        )
        apps = self.conn.execute(
            "SELECT apps.process_name FROM apps"
            " JOIN loadout_apps ON loadout_apps.app_id = apps.id"
            " WHERE loadout_apps.loadout_id = ? ORDER BY apps.process_name",
            (loadout_id,),
        )
        return {
            "name": stored_name,
            "sites": [url for (url,) in sites],
            "apps": [process for (process,) in apps],
        }

    def save_loadout(self, name, sites, apps=(), old_name=None):
        """Create the loadout, or replace what's in it. old_name renames it at the same time.

        returns the name as stored. ValueError on a bad name or site, and then nothing changes.
        """
        name = name.strip()
        if not name:
            raise ValueError("Give the loadout a name.")

        # check everything before touching the database
        cleaned = [hostfileservice.normalizedomain(site) for site in sites if site.strip()]
        sites = sorted(hostfileservice.plainsites(cleaned))
        apps = sorted({appblocker.normalizeapp(app) for app in apps if app.strip()})

        try:
            with self.conn:  # one transaction: all of it happens, or none of it
                row = self.conn.execute(
                    "SELECT id FROM loadouts WHERE name = ?", ((old_name or name).strip(),)
                ).fetchone()

                if row is None:
                    if old_name:
                        raise ValueError(f"There's no loadout called '{old_name}'.")
                    loadout_id = self.conn.execute(
                        "INSERT INTO loadouts (name) VALUES (?)", (name,)
                    ).lastrowid
                else:
                    loadout_id = row[0]
                    self.conn.execute("UPDATE loadouts SET name = ? WHERE id = ?", (name, loadout_id))

                self.conn.execute("DELETE FROM loadout_sites WHERE loadout_id = ?", (loadout_id,))
                self.conn.execute("DELETE FROM loadout_apps WHERE loadout_id = ?", (loadout_id,))

                for url in sites:
                    self.conn.execute("INSERT OR IGNORE INTO sites (url) VALUES (?)", (url,))
                    self.conn.execute(
                        "INSERT INTO loadout_sites (loadout_id, site_id)"
                        " SELECT ?, id FROM sites WHERE url = ?",
                        (loadout_id, url),
                    )
                for process in apps:
                    self.conn.execute("INSERT OR IGNORE INTO apps (process_name) VALUES (?)", (process,))
                    self.conn.execute(
                        "INSERT INTO loadout_apps (loadout_id, app_id)"
                        " SELECT ?, id FROM apps WHERE process_name = ?",
                        (loadout_id, process),
                    )

                self._drop_unused()
        except sqlite3.IntegrityError:
            raise ValueError(f"A loadout called '{name}' already exists.")

        return name

    def delete_loadout(self, name):
        """True if it existed. The links go with it (ON DELETE CASCADE)."""
        with self.conn:
            deleted = self.conn.execute(
                "DELETE FROM loadouts WHERE name = ?", (name.strip(),)
            ).rowcount
            self._drop_unused()
        return deleted > 0

    # ---------- apps that are blocked right now ----------

    def block_apps(self, names, until=None):
        """Start blocking the apps. Returns the ones newly added.

        until: unix time to unblock at, or None to stay blocked until you unblock it. An app
        that's already blocked keeps its first end time. ValueError on a bad or protected
        name, and then nothing is added.
        """
        names = sorted({appblocker.normalizeapp(name) for name in names if name.strip()})
        ends = None if until is None else int(until)

        added = []
        with self.conn:
            for name in names:
                cursor = self.conn.execute(
                    "INSERT OR IGNORE INTO app_blocks (process_name, until) VALUES (?, ?)",
                    (name, ends),
                )
                if cursor.rowcount:  # 0 means it was already there and got ignored
                    added.append(name)
        return added

    def app_blocks_until(self):
        """{app: unblock time in unix seconds, or None if you have to unblock it}"""
        rows = self.conn.execute(
            "SELECT process_name, until FROM app_blocks ORDER BY process_name"
        )
        return dict(rows.fetchall())

    def unblock_apps(self, names):
        """Returns the ones that really were blocked. 'spotify' finds 'spotify.exe'."""
        removed = []
        with self.conn:
            for name in sorted({stored_name(text) for text in names if text.strip()}):
                cursor = self.conn.execute(
                    "DELETE FROM app_blocks WHERE process_name = ?", (name,)
                )
                if cursor.rowcount:
                    removed.append(name)
        return removed

    def unblock_expired_apps(self, now=None):
        """Unblock the timed apps whose time is up. Returns their names."""
        now = time.time() if now is None else now
        with self.conn:
            rows = self.conn.execute(
                "SELECT process_name FROM app_blocks"
                " WHERE until IS NOT NULL AND until <= ? ORDER BY process_name",
                (now,),
            ).fetchall()
            self.conn.execute(
                "DELETE FROM app_blocks WHERE until IS NOT NULL AND until <= ?", (now,)
            )
        return [name for (name,) in rows]

    def _drop_unused(self):
        # sites and apps are shared between loadouts, so only drop the ones nobody uses
        self.conn.execute("DELETE FROM sites WHERE id NOT IN (SELECT site_id FROM loadout_sites)")
        self.conn.execute("DELETE FROM apps WHERE id NOT IN (SELECT app_id FROM loadout_apps)")
