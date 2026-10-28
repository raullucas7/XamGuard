"""Window tests: a hidden window, a fake hosts file, buttons pressed from code."""

import gc
import struct
import tkinter as tk

import pytest

from xamguard import admin, appblocker, db, gui, hostfileservice as h


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    path = tmp_path / "hosts"
    path.write_text("127.0.0.1 localhost\n")
    monkeypatch.setattr(h, "HOST_PATH", str(path))
    monkeypatch.setattr(h, "dnsflush", lambda: None)
    return path


class SweepRecorder:
    """Stands in for appblocker.sweep: remembers what it was asked to close, closes nothing."""

    def __init__(self):
        self.calls = []  # one entry per sweep: the names it was asked to close
        self.closes = []  # what to pretend it closed

    def __call__(self, blocked, *args, **kwargs):
        self.calls.append(sorted(blocked))
        return list(self.closes)


@pytest.fixture(autouse=True)
def sweeps(monkeypatch):
    """Every window test runs with this. The window sweeps for blocked apps, and a test
    must never close a real one (say, your actual Spotify), so sweeps go to a recorder."""
    recorder = SweepRecorder()
    monkeypatch.setattr(appblocker, "sweep", recorder)
    monkeypatch.setattr(appblocker, "running_apps", lambda *args, **kwargs: [])
    return recorder


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
def database():
    database = db.Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def make_app(hosts, tk_root, clock, database):
    apps = []

    def make(admin_rights=True, **options):
        options.setdefault("db", database)  # pass db=None to switch loadouts off
        app = gui.XamGuardApp(tk_root, admin_rights=admin_rights, clock=clock, **options)
        apps.append(app)
        return app

    yield make

    for app in apps:
        app.destroy()  # clears this test's widgets, keeps the window


def shown(app):
    """What the list box shows."""
    return list(app.listbox.get(0, "end"))


def open_editor(app):
    app.edit_button.invoke()
    return app.editor


def type_sites(editor, text):
    editor.sites_box.delete("1.0", "end")
    editor.sites_box.insert("1.0", text)


def sites_in(editor):
    return editor.sites_box.get("1.0", "end").split()


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


# ---------- loadouts: the main window ----------

def test_the_dropdown_lists_the_saved_loadouts(make_app, database):
    database.save_loadout("Study", ["a.com"])
    database.save_loadout("Gaming", ["b.com"])

    app = make_app()

    assert list(app.loadout_box["values"]) == ["Gaming", "Study"]
    assert app.loadout_text.get() == "Gaming"  # first one is picked
    assert not app.loadout_button.instate(["disabled"])


def test_with_no_loadouts_the_block_button_is_off_but_editing_is_on(make_app):
    app = make_app()

    assert app.loadout_text.get() == gui.NO_LOADOUTS
    assert app.loadout_button.instate(["disabled"])
    assert not app.edit_button.instate(["disabled"])


def test_block_loadout_blocks_every_site_in_it(make_app, database):
    database.save_loadout("Study", ["a.com", "b.com"])
    app = make_app()
    app.site_text.set("half typed")

    app.loadout_button.invoke()

    assert h.list_blocked() == ["a.com", "b.com"]
    assert shown(app) == ["a.com", "b.com"]
    assert app.status_text.get() == "Study loadout blocked: a.com, b.com"
    assert app.site_text.get() == "half typed"  # the entry box is left alone


def test_block_loadout_uses_the_for_time(make_app, database, clock):
    database.save_loadout("Study", ["a.com"])
    app = make_app()
    app.length_text.set("25 minutes")

    app.loadout_button.invoke()

    assert h.list_blocked_until() == {"a.com": clock.now + 25 * 60}
    assert app.status_text.get() == "Study loadout blocked for 25 minutes: a.com"


def test_block_loadout_when_everything_is_already_blocked(make_app, database):
    h.block(["a.com"])
    database.save_loadout("Study", ["a.com"])
    app = make_app()

    app.loadout_button.invoke()

    assert app.status_text.get() == "Everything in Study was already blocked."


def test_an_empty_loadout_has_nothing_to_block(make_app, database, hosts):
    before = hosts.read_text()
    database.save_loadout("Empty", [])
    app = make_app()

    app.loadout_button.invoke()

    assert "no sites" in app.status_text.get()
    assert hosts.read_text() == before


def test_blocking_a_loadout_needs_admin_rights(make_app, database, hosts):
    before = hosts.read_text()
    database.save_loadout("Study", ["a.com"])
    app = make_app(admin_rights=False)

    assert app.loadout_button.instate(["disabled"])
    app.on_block_loadout()  # in case something calls the handler anyway

    assert "administrator" in app.status_text.get()
    assert hosts.read_text() == before


def test_without_a_database_loadouts_are_off_but_blocking_still_works(make_app, hosts):
    app = make_app(db=None)

    assert app.loadout_text.get() == gui.LOADOUTS_OFF
    assert app.loadout_button.instate(["disabled"])
    assert app.edit_button.instate(["disabled"])

    app.on_block_loadout()
    assert "unavailable" in app.status_text.get()

    app.site_text.set("a.com")
    app.block_button.invoke()
    assert h.list_blocked() == ["a.com"]


def test_refreshing_keeps_the_pick_if_it_still_exists(make_app, database):
    database.save_loadout("Alpha", ["a.com"])
    database.save_loadout("Study", ["b.com"])
    app = make_app()
    app.loadout_text.set("Study")

    database.save_loadout("Zed", ["c.com"])
    app.refresh_loadouts()

    assert app.loadout_text.get() == "Study"
    assert list(app.loadout_box["values"]) == ["Alpha", "Study", "Zed"]


def test_refreshing_moves_off_a_loadout_that_was_deleted(make_app, database):
    database.save_loadout("Alpha", ["a.com"])
    database.save_loadout("Study", ["b.com"])
    app = make_app()
    app.loadout_text.set("Study")

    database.delete_loadout("Study")
    app.refresh_loadouts()

    assert app.loadout_text.get() == "Alpha"


# ---------- loadouts: the editor window ----------

def test_the_edit_button_opens_just_one_editor(make_app):
    app = make_app()

    first = open_editor(app)
    second = open_editor(app)

    assert first is second
    assert first.winfo_exists()


def test_the_editor_lists_the_saved_loadouts(make_app, database):
    database.save_loadout("Study", ["a.com"])
    database.save_loadout("Gaming", ["b.com"])

    editor = open_editor(make_app())

    assert list(editor.listbox.get(0, "end")) == ["Gaming", "Study"]


def test_creating_a_loadout_saves_it_cleaned_and_updates_the_dropdown(make_app, database):
    app = make_app()
    editor = open_editor(app)
    editor.name_text.set("Study")
    type_sites(editor, "youtube.com, https://www.reddit.com/r/python\ntwitter.com")

    editor.save_button.invoke()

    assert database.get_loadout("Study")["sites"] == ["reddit.com", "twitter.com", "youtube.com"]
    assert list(editor.listbox.get(0, "end")) == ["Study"]
    assert list(app.loadout_box["values"]) == ["Study"]  # main window heard about it
    assert editor.status_text.get() == "Saved Study."


def test_picking_a_loadout_fills_in_the_form(make_app, database):
    database.save_loadout("Study", ["a.com", "b.com"])
    editor = open_editor(make_app())

    editor.listbox.selection_set(0)
    editor.on_pick()

    assert editor.name_text.get() == "Study"
    assert sites_in(editor) == ["a.com", "b.com"]
    assert editor.current == "Study"


def test_editing_replaces_the_sites(make_app, database):
    database.save_loadout("Study", ["a.com", "b.com"])
    editor = open_editor(make_app())
    editor.listbox.selection_set(0)
    editor.on_pick()

    type_sites(editor, "c.com")
    editor.save_button.invoke()

    assert database.get_loadout("Study")["sites"] == ["c.com"]
    assert database.loadout_names() == ["Study"]


def test_editing_a_loadout_keeps_its_apps(make_app, database):
    database.save_loadout("Study", ["a.com"], apps=["spotify.exe"])
    editor = open_editor(make_app())
    editor.listbox.selection_set(0)
    editor.on_pick()

    type_sites(editor, "b.com")
    editor.save_button.invoke()

    assert database.get_loadout("Study") == {
        "name": "Study",
        "sites": ["b.com"],
        "apps": ["spotify.exe"],
    }


def test_renaming_a_loadout(make_app, database):
    database.save_loadout("Study", ["a.com"])
    app = make_app()
    editor = open_editor(app)
    editor.listbox.selection_set(0)
    editor.on_pick()

    editor.name_text.set("Focus")
    editor.save_button.invoke()

    assert database.loadout_names() == ["Focus"]
    assert list(app.loadout_box["values"]) == ["Focus"]
    assert app.loadout_text.get() == "Focus"


def test_a_bad_site_shows_an_error_and_saves_nothing(make_app, database):
    editor = open_editor(make_app())
    editor.name_text.set("Study")
    type_sites(editor, "good.com not_a_site")

    editor.save_button.invoke()

    assert "not a valid website" in editor.status_text.get()
    assert database.loadout_names() == []


def test_a_loadout_needs_a_name(make_app, database):
    editor = open_editor(make_app())
    type_sites(editor, "a.com")

    editor.save_button.invoke()

    assert "name" in editor.status_text.get()
    assert database.loadout_names() == []


def test_a_new_loadout_cannot_overwrite_an_existing_one(make_app, database):
    database.save_loadout("Study", ["keep.com"])
    editor = open_editor(make_app())
    editor.name_text.set("study")  # "new loadout" mode, but the name is taken
    type_sites(editor, "other.com")

    editor.save_button.invoke()

    assert "already exists" in editor.status_text.get()
    assert database.get_loadout("Study")["sites"] == ["keep.com"]


def test_new_clears_the_form(make_app, database):
    database.save_loadout("Study", ["a.com"])
    editor = open_editor(make_app())
    editor.listbox.selection_set(0)
    editor.on_pick()

    editor.on_new()

    assert editor.name_text.get() == ""
    assert sites_in(editor) == []
    assert editor.current is None
    assert editor.listbox.curselection() == ()


def test_delete_asks_first(make_app, database, monkeypatch):
    database.save_loadout("Study", ["a.com"])
    editor = open_editor(make_app())
    editor.listbox.selection_set(0)
    editor.on_pick()

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *args, **kwargs: False)
    editor.delete_button.invoke()
    assert database.loadout_names() == ["Study"]  # said no, so it's still there


def test_confirmed_delete_removes_it_everywhere(make_app, database, monkeypatch):
    database.save_loadout("Study", ["a.com"])
    app = make_app()
    editor = open_editor(app)
    editor.listbox.selection_set(0)
    editor.on_pick()

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *args, **kwargs: True)
    editor.delete_button.invoke()

    assert database.loadout_names() == []
    assert list(editor.listbox.get(0, "end")) == []
    assert editor.name_text.get() == ""
    assert editor.status_text.get() == "Deleted Study."
    assert app.loadout_text.get() == gui.NO_LOADOUTS


def test_delete_with_nothing_picked_asks_to_pick(make_app, monkeypatch):
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *args, **kwargs: asked.append(1))
    editor = open_editor(make_app())

    editor.delete_button.invoke()

    assert "Pick a loadout" in editor.status_text.get()
    assert asked == []  # it didn't even ask


def test_closing_the_app_closes_the_editor_too(make_app):
    app = make_app()
    editor = open_editor(app)

    app.destroy()

    assert not editor.winfo_exists()


# ---------- the logo ----------

@pytest.mark.parametrize("dpi, filename", [
    (96, "guardian_100.png"),  # 100% scaling
    (120, "guardian_125.png"),  # 125%
    (144, "guardian_150.png"),  # 150%
    (192, "guardian_200.png"),  # 200%
    (110, "guardian_125.png"),  # in between picks the closest
    (72, "guardian_100.png"),  # smaller than anything we have
    (300, "guardian_200.png"),  # bigger than anything we have
])
def test_logo_path_picks_the_size_for_the_screen(dpi, filename):
    assert gui.logo_path(dpi).name == filename


def png_info(path):
    """(width, height, colour type) read straight from the png header."""
    header = path.read_bytes()[:26]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", header[16:24])
    return width, height, header[25]


@pytest.mark.parametrize("filename, height", [
    ("guardian_100.png", 88),
    ("guardian_125.png", 110),
    ("guardian_150.png", 132),
    ("guardian_200.png", 176),
])
def test_each_logo_file_is_a_transparent_png_at_its_size(filename, height):
    width, real_height, colour_type = png_info(gui.ASSETS / filename)

    assert real_height == height
    assert width == height // 2  # the picture is twice as tall as it is wide
    assert colour_type == 6  # RGBA, so it has transparency


def test_every_file_the_window_can_ask_for_exists():
    for name in gui.LOGO_FILES.values():
        assert (gui.ASSETS / name).is_file()


def test_the_logo_sits_in_the_top_right_of_the_header(make_app):
    app = make_app()

    assert app.logo_image.height() in (88, 110, 132, 176)
    info = app.logo_label.grid_info()
    assert (int(info["column"]), int(info["row"]), int(info["rowspan"])) == (1, 0, 3)
    assert set(info["sticky"]) == {"n", "e"}


def test_the_title_and_motto_stay_together_next_to_a_tall_logo(make_app):
    """Old bug in the first version: the spare height was split between the two lines."""
    app = make_app()
    app.update()
    title, motto = [w for w in app.logo_label.master.grid_slaves() if int(w.grid_info()["column"]) == 0][::-1]

    gap = motto.winfo_y() - (title.winfo_y() + title.winfo_height())

    assert gap < 10  # touching, not pushed apart


def test_the_logo_is_really_showing_not_thrown_away(make_app):
    app = make_app()

    gc.collect()  # if nothing kept the image alive, Tk would blank the label here
    app.update_idletasks()

    assert app.logo_label.winfo_reqwidth() >= app.logo_image.width()
    assert app.logo_label.winfo_reqheight() >= app.logo_image.height()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_the_window_still_opens_without_a_usable_logo(make_app, monkeypatch, tmp_path, damage):
    monkeypatch.setattr(gui, "ASSETS", tmp_path)  # an empty folder
    if damage == "corrupt":
        for name in gui.LOGO_FILES.values():
            (tmp_path / name).write_bytes(b"this is not a png")

    app = make_app()

    assert app.logo_image is None
    assert app.logo_label is None
    assert shown(app) == [gui.PLACEHOLDER]  # everything else still works


# ---------- apps: the main window ----------

@pytest.mark.parametrize("text, expected", [
    ("spotify, steam", ["spotify", "steam"]),
    ("spotify\nsteam", ["spotify", "steam"]),
    ("Origin Web Helper Service, steam", ["Origin Web Helper Service", "steam"]),  # spaces stay
    (" a ,, b \n\n", ["a", "b"]),
    ("", []),
])
def test_splitapps(text, expected):
    assert gui.splitapps(text) == expected


def test_blocking_a_loadout_with_apps_blocks_the_sites_and_records_the_apps(make_app, database, sweeps):
    database.save_loadout("Study", ["a.com"], apps=["Spotify"])
    app = make_app()

    app.loadout_button.invoke()

    assert h.list_blocked() == ["a.com"]
    assert database.app_blocks_until() == {"spotify.exe": None}
    assert shown(app) == ["a.com", "spotify.exe [app]"]
    assert app.status_text.get() == (
        "Study loadout blocked: a.com, spotify.exe [app]. Apps are only closed while XamGuard is open."
    )
    assert sweeps.calls == [["spotify.exe"]]  # swept right away, not 2 seconds later


def test_apps_get_the_same_end_time_and_countdown_as_sites(make_app, database, clock):
    database.save_loadout("Study", ["a.com"], apps=["spotify.exe"])
    app = make_app()
    app.length_text.set("25 minutes")

    app.loadout_button.invoke()

    assert database.app_blocks_until() == {"spotify.exe": clock.now + 25 * 60}
    assert shown(app) == ["a.com   (25:00 left)", "spotify.exe [app]   (25:00 left)"]
    assert "for 25 minutes" in app.status_text.get()


def test_a_loadout_with_only_apps_leaves_the_hosts_file_alone(make_app, database, hosts):
    before = hosts.read_text()
    database.save_loadout("Games", [], apps=["steam.exe"])
    app = make_app()

    app.loadout_button.invoke()

    assert database.app_blocks_until() == {"steam.exe": None}
    assert hosts.read_text() == before
    assert shown(app) == ["steam.exe [app]"]


def test_apps_that_are_running_get_closed_right_away(make_app, database, sweeps):
    database.save_loadout("Study", [], apps=["spotify.exe"])
    sweeps.closes = ["spotify.exe"]
    app = make_app()

    app.loadout_button.invoke()

    assert app.status_text.get().endswith("Closed now: spotify.exe.")


def test_blocking_a_loadout_again_says_everything_was_already_blocked(make_app, database):
    database.save_loadout("Study", ["a.com"], apps=["spotify.exe"])
    app = make_app()
    app.loadout_button.invoke()

    app.loadout_button.invoke()

    assert app.status_text.get() == "Everything in Study was already blocked."


def test_without_psutil_the_sites_still_block_and_the_apps_are_not_recorded(make_app, database, monkeypatch):
    monkeypatch.setattr(appblocker, "available", lambda: False)
    database.save_loadout("Study", ["a.com"], apps=["spotify.exe"])
    app = make_app()

    app.loadout_button.invoke()

    assert h.list_blocked() == ["a.com"]
    assert database.app_blocks_until() == {}
    assert "needs psutil" in app.status_text.get()


def test_a_protected_app_in_a_loadout_is_refused_but_the_sites_still_block(make_app, database):
    """Can only happen if the database was edited by hand: the window still says no."""
    database.save_loadout("Study", ["a.com"])
    database.conn.execute("INSERT INTO apps (process_name) VALUES ('explorer.exe')")
    database.conn.execute(
        "INSERT INTO loadout_apps SELECT loadouts.id, apps.id FROM loadouts, apps"
        " WHERE loadouts.name = 'Study' AND apps.process_name = 'explorer.exe'"
    )
    database.conn.commit()
    app = make_app()

    app.loadout_button.invoke()

    assert h.list_blocked() == ["a.com"]
    assert database.app_blocks_until() == {}
    assert "protected" in app.status_text.get()


def test_the_title_counts_sites_and_apps_together(make_app, database):
    h.block(["a.com", "b.com"])
    database.block_apps(["spotify.exe"])
    app = make_app()
    assert app.listing.cget("text") == "Currently blocked (3)"


# ---------- apps: the sweep ----------

def test_the_sweep_closes_blocked_apps_and_says_so(make_app, database, sweeps):
    database.block_apps(["spotify.exe", "steam.exe"])
    app = make_app()
    sweeps.closes = ["spotify.exe"]

    app.sweep_apps()

    assert sweeps.calls == [["spotify.exe", "steam.exe"]]
    assert app.status_text.get() == "Closed: spotify.exe"


def test_the_sweep_does_not_even_look_when_no_apps_are_blocked(make_app, sweeps):
    app = make_app()
    app.sweep_apps()
    assert sweeps.calls == []


def test_the_sweep_stops_looking_for_an_app_once_its_time_is_up(make_app, database, sweeps, clock):
    database.block_apps(["a.exe"], until=clock.now + 60)
    database.block_apps(["b.exe"])
    app = make_app()

    clock.advance(60)  # exactly the end
    app.sweep_apps()

    assert sweeps.calls == [["b.exe"]]
    assert database.app_blocks_until() == {"b.exe": None}
    assert shown(app) == ["b.exe [app]"]
    assert app.status_text.get() == "Time's up. Unblocked: a.exe"


def test_app_blocks_that_ended_while_the_app_was_closed_are_cleared_at_startup(make_app, database, clock):
    database.block_apps(["old.exe"], until=clock.now - 10)
    database.block_apps(["keep.exe"])

    app = make_app()

    assert shown(app) == ["keep.exe [app]"]
    assert "Time's up" in app.status_text.get()


def test_app_blocks_that_have_not_ended_resume_after_a_restart(make_app, database, clock):
    database.block_apps(["a.exe"], until=clock.now + 600)
    app = make_app()  # "restart"
    assert shown(app) == ["a.exe [app]   (10:00 left)"]


def test_the_sweep_works_without_admin_rights(make_app, database, sweeps):
    database.block_apps(["a.exe"])  # closing your own programs doesn't need admin
    app = make_app(admin_rights=False)

    app.sweep_apps()

    assert sweeps.calls == [["a.exe"]]


def test_the_sweep_does_nothing_if_psutil_is_missing(make_app, database, sweeps, monkeypatch):
    database.block_apps(["a.exe"])
    app = make_app()
    monkeypatch.setattr(appblocker, "available", lambda: False)

    app.sweep_apps()

    assert sweeps.calls == []


def test_the_sweep_is_scheduled_and_cancelled_with_the_frame(make_app, tk_root):
    app = make_app()
    job = app._sweep_job

    def pending():
        return tk_root.tk.splitlist(tk_root.tk.call("after", "info"))

    assert job in pending()
    app.destroy()
    assert job not in pending()


# ---------- apps: the list and unblocking ----------

def test_unblock_selected_removes_an_app(make_app, database):
    h.block(["a.com"])
    database.block_apps(["spotify.exe", "steam.exe"])
    app = make_app()
    app.listbox.selection_set(1)  # rows: a.com, spotify.exe, steam.exe

    app.unblock_button.invoke()

    assert database.app_blocks_until() == {"steam.exe": None}
    assert h.list_blocked() == ["a.com"]
    assert app.status_text.get() == "Unblocked: spotify.exe [app]"


def test_unblock_selected_can_remove_a_site_and_an_app_together(make_app, database):
    h.block(["a.com"])
    database.block_apps(["spotify.exe"])
    app = make_app()
    app.listbox.selection_set(0, 1)

    app.unblock_button.invoke()

    assert h.list_blocked() == []
    assert database.app_blocks_until() == {}
    assert app.status_text.get() == "Unblocked: a.com, spotify.exe [app]"


def test_tick_keeps_a_selected_app_row(make_app, database, clock):
    database.block_apps(["a.exe", "b.exe"], until=clock.now + 600)
    app = make_app()
    app.listbox.selection_set(1)  # b.exe

    clock.advance(1)
    app.tick()

    assert app.selected_apps() == ["b.exe"]
    assert app.selected_sites() == []


# ---------- apps: the close button ----------

def ask_back(monkeypatch, reply):
    """Replace the 'are you sure?' popup. Returns the list of messages it was asked."""
    asked = []

    def fake(title, message, **kwargs):
        asked.append(message)
        return reply

    monkeypatch.setattr(gui.messagebox, "askyesno", fake)
    return asked


def test_closing_while_apps_are_blocked_asks_first(make_app, database, monkeypatch):
    database.block_apps(["spotify.exe"])
    app = make_app()
    closed = []
    monkeypatch.setattr(app.root, "destroy", lambda: closed.append(True))

    asked = ask_back(monkeypatch, reply=False)
    app.on_close()
    assert closed == []  # said no, stays open
    assert "spotify.exe" in asked[0]

    ask_back(monkeypatch, reply=True)
    app.on_close()
    assert closed == [True]


def test_closing_with_no_apps_blocked_just_closes(make_app, monkeypatch):
    app = make_app()
    closed = []
    monkeypatch.setattr(app.root, "destroy", lambda: closed.append(True))
    asked = ask_back(monkeypatch, reply=False)

    app.on_close()

    assert closed == [True]
    assert asked == []  # nothing to warn about


def test_closing_does_not_ask_about_app_blocks_that_already_ended(make_app, database, clock, monkeypatch):
    database.block_apps(["a.exe"], until=clock.now + 5)
    app = make_app()
    clock.advance(10)  # over, but nobody has swept yet
    closed = []
    monkeypatch.setattr(app.root, "destroy", lambda: closed.append(True))
    asked = ask_back(monkeypatch, reply=False)

    app.on_close()

    assert closed == [True] and asked == []


# ---------- apps: the editor ----------

def test_picking_a_loadout_shows_its_apps(make_app, database):
    database.save_loadout("Study", ["a.com"], apps=["steam.exe", "spotify.exe"])
    editor = open_editor(make_app())

    editor.listbox.selection_set(0)
    editor.on_pick()

    assert editor.apps_box.get("1.0", "end").split() == ["spotify.exe", "steam.exe"]


def test_saving_apps_cleans_them_and_keeps_names_with_spaces(make_app, database):
    editor = open_editor(make_app())
    editor.name_text.set("Study")
    type_sites(editor, "a.com")
    editor.apps_box.insert("1.0", "Spotify, Origin Web Helper Service\nSTEAM.exe")

    editor.save_button.invoke()

    assert database.get_loadout("Study")["apps"] == [
        "origin web helper service.exe",
        "spotify.exe",
        "steam.exe",
    ]


def test_a_protected_app_shows_an_error_and_saves_nothing(make_app, database):
    editor = open_editor(make_app())
    editor.name_text.set("Study")
    editor.apps_box.insert("1.0", "spotify\nexplorer")

    editor.save_button.invoke()

    assert "protected" in editor.status_text.get()
    assert database.loadout_names() == []


def test_new_also_clears_the_apps_box(make_app, database):
    database.save_loadout("Study", [], apps=["steam.exe"])
    editor = open_editor(make_app())
    editor.listbox.selection_set(0)
    editor.on_pick()

    editor.on_new()

    assert editor.apps_box.get("1.0", "end").strip() == ""


def test_the_picker_lists_running_apps_and_adds_the_chosen_ones(make_app, monkeypatch):
    monkeypatch.setattr(appblocker, "running_apps", lambda *a, **k: ["discord.exe", "spotify.exe", "steam.exe"])
    editor = open_editor(make_app())
    editor.apps_box.insert("1.0", "steam.exe")

    editor.pick_button.invoke()
    picker = editor.picker
    assert list(picker.listbox.get(0, "end")) == ["discord.exe", "spotify.exe", "steam.exe"]

    picker.listbox.selection_set(0)
    picker.listbox.selection_set(2)  # discord and steam (steam is already in the box)
    picker.add_button.invoke()

    assert editor.apps_box.get("1.0", "end").split() == ["steam.exe", "discord.exe"]  # no duplicate
    assert not picker.winfo_exists()  # it closes itself after adding


def test_the_picker_only_opens_once(make_app):
    editor = open_editor(make_app())
    editor.pick_button.invoke()
    first = editor.picker

    editor.pick_button.invoke()

    assert editor.picker is first


def test_the_picker_button_is_off_without_psutil(make_app, monkeypatch):
    monkeypatch.setattr(appblocker, "available", lambda: False)
    editor = open_editor(make_app())
    assert editor.pick_button.instate(["disabled"])


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
