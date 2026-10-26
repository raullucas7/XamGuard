"""Window tests: a hidden window, a fake hosts file, buttons pressed from code."""

import tkinter as tk

import pytest

from xamguard import admin, gui, hostfileservice as h


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    path = tmp_path / "hosts"
    path.write_text("127.0.0.1 localhost\n")
    monkeypatch.setattr(h, "HOST_PATH", str(path))
    monkeypatch.setattr(h, "dnsflush", lambda: None)
    return path


@pytest.fixture(scope="session")
def tk_root():
    """One hidden window for all tests. Making a new one each time randomly failed
    with "Can't find a usable init.tcl"."""
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tkinter can't open a window here: {error}")
    root.withdraw()  # hidden
    yield root
    root.destroy()


@pytest.fixture
def make_app(hosts, tk_root):
    apps = []

    def make(admin_rights=True):
        app = gui.XamGuardApp(tk_root, admin_rights=admin_rights)
        apps.append(app)
        return app

    yield make

    for app in apps:
        app.destroy()  # clears this test's widgets, keeps the window


def shown(app):
    """What the list box shows."""
    return list(app.listbox.get(0, "end"))


# ---------- splitinput ----------

@pytest.mark.parametrize("text, expected", [
    ("youtube.com", ["youtube.com"]),
    ("a.com, b.com", ["a.com", "b.com"]),
    ("a.com b.com   c.com", ["a.com", "b.com", "c.com"]),
    (" a.com ,, b.com , ", ["a.com", "b.com"]),
    ("", []),
    ("   ", []),
])
def test_splitinput(text, expected):
    assert gui.splitinput(text) == expected


# ---------- startup ----------

def test_empty_list_shows_a_placeholder_row(make_app):
    app = make_app()
    assert app.sites == []
    assert shown(app) == [gui.PLACEHOLDER]


def test_sites_blocked_before_launch_are_shown_at_startup(make_app):
    """Old bug: the app forgot sites that were still blocked."""
    h.block(["youtube.com", "twitter.com"])
    app = make_app()
    assert shown(app) == ["twitter.com", "youtube.com"]


# ---------- blocking ----------

def test_block_button_blocks_and_updates_the_list(make_app, hosts):
    app = make_app()
    app.site_text.set("https://www.youtube.com/watch?v=1, twitter.com")

    app.block_button.invoke()

    assert shown(app) == ["twitter.com", "youtube.com"]
    assert h.list_blocked() == ["twitter.com", "youtube.com"]
    assert app.site_text.get() == ""  # entry box is cleared
    assert app.status_text.get().startswith("Blocked:")


def test_blocking_an_invalid_site_shows_an_error_and_changes_nothing(make_app, hosts):
    before = hosts.read_text()
    app = make_app()
    app.site_text.set("good.com, not_a_site")

    app.block_button.invoke()

    assert "not a valid website" in app.status_text.get()
    assert hosts.read_text() == before
    assert app.site_text.get() == "good.com, not_a_site"  # kept so the user can fix it


def test_blocking_nothing_asks_for_a_site(make_app, hosts):
    before = hosts.read_text()
    app = make_app()

    app.block_button.invoke()

    assert "Type a site" in app.status_text.get()
    assert hosts.read_text() == before


def test_blocking_an_already_blocked_site_says_so(make_app):
    h.block(["youtube.com"])
    app = make_app()
    app.site_text.set("youtube.com")

    app.block_button.invoke()

    assert "already blocked" in app.status_text.get()


# ---------- unblocking ----------

def test_unblock_selected_removes_only_the_selected_site(make_app):
    h.block(["a.com", "b.com"])
    app = make_app()
    app.listbox.selection_set(0)  # a.com

    app.unblock_button.invoke()

    assert shown(app) == ["b.com"]
    assert h.list_blocked() == ["b.com"]
    assert app.status_text.get() == "Unblocked: a.com"


def test_unblock_with_nothing_selected_asks_to_select(make_app):
    h.block(["a.com"])
    app = make_app()

    app.unblock_button.invoke()

    assert "Select one or more sites" in app.status_text.get()
    assert h.list_blocked() == ["a.com"]


def test_placeholder_row_cannot_be_unblocked(make_app, hosts):
    before = hosts.read_text()
    app = make_app()
    app.listbox.selection_set(0)  # the grey "No sites are blocked" row

    app.unblock_button.invoke()

    assert "Select one or more sites" in app.status_text.get()
    assert hosts.read_text() == before


# ---------- without administrator rights ----------

def test_without_admin_rights_buttons_are_disabled_and_nothing_is_written(make_app, hosts):
    before = hosts.read_text()
    app = make_app(admin_rights=False)
    app.site_text.set("youtube.com")

    assert app.block_button.instate(["disabled"])
    assert app.unblock_button.instate(["disabled"])

    app.on_block()  # same as pressing Enter

    assert "administrator" in app.status_text.get()
    assert hosts.read_text() == before


def test_without_admin_rights_the_list_is_still_readable(make_app):
    h.block(["youtube.com"])
    app = make_app(admin_rights=False)
    assert shown(app) == ["youtube.com"]


def test_restart_as_admin_closes_this_window_only_if_windows_agrees(make_app, monkeypatch):
    app = make_app(admin_rights=False)
    closed = []
    monkeypatch.setattr(app.root, "destroy", lambda: closed.append(True))

    monkeypatch.setattr(admin, "relaunch_as_admin", lambda: False)  # user clicked "No" on UAC
    app.on_elevate()
    assert closed == []
    assert "not granted" in app.status_text.get()

    monkeypatch.setattr(admin, "relaunch_as_admin", lambda: True)  # user clicked "Yes"
    app.on_elevate()
    assert closed == [True]


def test_is_admin_returns_a_plain_bool():
    # not testing relaunch_as_admin, it would pop a real UAC prompt
    assert isinstance(admin.is_admin(), bool)
