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


class FakeClock:
    """a clock we move by hand"""

    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_app(hosts, tk_root, clock):
    apps = []

    def make(admin_rights=True):
        app = gui.XamGuardApp(tk_root, admin_rights=admin_rights, clock=clock)
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


# ---------- timed blocks ----------

@pytest.mark.parametrize("seconds, expected", [
    (0, "0:00"),
    (-5, "0:00"),
    (0.2, "0:01"),  # rounds up, never shows 0:00 early
    (59, "0:59"),
    (60, "1:00"),
    (1450, "24:10"),
    (3599, "59:59"),
    (3600, "1:00:00"),
    (3725, "1:02:05"),
])
def test_formatremaining(seconds, expected):
    assert gui.formatremaining(seconds) == expected


def test_the_for_box_offers_every_duration(make_app):
    app = make_app()
    assert list(app.length_box["values"]) == list(gui.DURATIONS)
    assert app.length_text.get() == "Until I unblock"


def test_block_for_a_while_shows_a_countdown(make_app, clock):
    app = make_app()
    app.site_text.set("youtube.com")
    app.length_text.set("25 minutes")

    app.block_button.invoke()

    assert shown(app) == ["youtube.com   (25:00 left)"]
    assert h.list_blocked_until() == {"youtube.com": clock.now + 25 * 60}
    assert app.status_text.get() == "Blocked for 25 minutes: youtube.com"


def test_default_block_has_no_end_time(make_app):
    app = make_app()
    app.site_text.set("a.com")

    app.block_button.invoke()

    assert shown(app) == ["a.com"]
    assert h.list_blocked_until() == {"a.com": None}
    assert app.status_text.get() == "Blocked: a.com"


def test_tick_counts_down(make_app, clock):
    h.block(["a.com"], until=clock.now + 90)
    app = make_app()
    assert shown(app) == ["a.com   (1:30 left)"]

    clock.advance(30)
    app.tick()

    assert shown(app) == ["a.com   (1:00 left)"]


def test_tick_unblocks_a_site_when_its_time_is_up(make_app, clock):
    h.block(["a.com"], until=clock.now + 60)
    h.block(["keep.com"])
    app = make_app()

    clock.advance(60)  # exactly the end
    app.tick()

    assert shown(app) == ["keep.com"]
    assert h.list_blocked() == ["keep.com"]
    assert app.status_text.get() == "Time's up. Unblocked: a.com"


def test_blocks_that_ended_while_the_app_was_closed_are_cleared_at_startup(make_app, clock):
    h.block(["a.com"], until=clock.now - 10)
    h.block(["keep.com"])

    app = make_app()

    assert shown(app) == ["keep.com"]
    assert h.list_blocked() == ["keep.com"]
    assert "Time's up" in app.status_text.get()


def test_blocks_that_have_not_ended_survive_a_restart(make_app, clock):
    h.block(["a.com"], until=clock.now + 600)
    app = make_app()  # "restart"
    assert shown(app) == ["a.com   (10:00 left)"]


def test_without_admin_rights_expired_blocks_are_left_alone(make_app, hosts, clock):
    h.block(["a.com"], until=clock.now + 5)
    before = hosts.read_text()
    app = make_app(admin_rights=False)

    clock.advance(10)
    app.tick()

    assert hosts.read_text() == before
    assert shown(app) == ["a.com   (time's up)"]


def test_tick_keeps_the_selected_row(make_app, clock):
    h.block(["a.com", "b.com"], until=clock.now + 600)
    app = make_app()
    app.listbox.selection_set(1)  # b.com

    clock.advance(1)
    app.tick()

    assert app.selected_sites() == ["b.com"]


def test_unblocking_does_not_select_the_next_site(make_app):
    h.block(["a.com", "b.com"])
    app = make_app()
    app.listbox.selection_set(0)  # a.com

    app.unblock_button.invoke()

    assert shown(app) == ["b.com"]
    assert app.selected_sites() == []


def test_a_timed_site_can_be_unblocked_early(make_app, clock):
    h.block(["a.com"], until=clock.now + 600)
    app = make_app()
    app.listbox.selection_set(0)

    app.unblock_button.invoke()

    assert h.list_blocked() == []


def test_the_tick_is_cancelled_when_the_frame_is_destroyed(make_app, tk_root):
    app = make_app()
    job = app._tick_job

    def pending():
        return tk_root.tk.splitlist(tk_root.tk.call("after", "info"))

    assert job in pending()
    app.destroy()
    assert job not in pending()


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
