"""The XamGuard window.

Just buttons and clicks. All the hosts file work lives in hostfileservice.py.
"""

import ctypes
import math
import re
import sqlite3
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import admin, appblocker, hostfileservice
from .db import Database

GOOD = "#1b5e20"
BAD = "#b00020"
PLACEHOLDER = "No sites are blocked. You are free to roam (carefully)."
NO_LOADOUTS = "(no loadouts yet)"
LOADOUTS_OFF = "(loadouts unavailable)"
APP_TAG = "[app]"  # marks an app in the list, so it isn't mistaken for a site
SWEEP_MS = 2000  # how often blocked apps are looked for and closed

# Tk can only resize pictures by whole numbers, so the logo is drawn ahead of time at a few
# sizes. display scaling (1.0 = 100%) -> file. tools/make_logo.ps1 makes them
ASSETS = Path(__file__).parent / "assets"
LOGO_FILES = {
    1.0: "guardian_100.png",
    1.25: "guardian_125.png",
    1.5: "guardian_150.png",
    2.0: "guardian_200.png",
}

# what the "For" box offers: label -> minutes (None = until you unblock it)
DURATIONS = {
    "Until I unblock": None,
    "15 minutes": 15,
    "25 minutes": 25,
    "45 minutes": 45,
    "1 hour": 60,
    "2 hours": 120,
    "4 hours": 240,
}


def splitinput(text):
    """'a.com, b.com c.com' -> ['a.com', 'b.com', 'c.com']"""
    return [piece for piece in re.split(r"[,\s]+", text) if piece]


def splitapps(text):
    """'spotify, steam' or one per line -> ['spotify', 'steam']. spaces stay, some names have them"""
    return [piece.strip() for piece in re.split(r"[,\n]+", text) if piece.strip()]


def formatremaining(seconds):
    """3725 -> '1:02:05', 1450 -> '24:10'. rounds up so it never shows 0:00 early."""
    seconds = math.ceil(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes}:{secs:02}"


def logo_path(dpi):
    """The logo file closest to the screen's scaling (96 dpi = 100%, 144 dpi = 150%)."""
    scale = dpi / 96
    closest = min(LOGO_FILES, key=lambda size: abs(size - scale))
    return ASSETS / LOGO_FILES[closest]


def load_logo(master):
    """The logo as a Tk image, or None if it can't be loaded (it's only decoration)."""
    try:
        return tk.PhotoImage(master=master, file=str(logo_path(master.winfo_fpixels("1i"))))
    except tk.TclError:
        return None


class XamGuardApp(ttk.Frame):
    def __init__(self, root, admin_rights=None, clock=time.time, db=None):
        super().__init__(root, padding=16)
        self.root = root
        # parameters so tests can fake being admin, the time and the database
        self.admin_rights = admin.is_admin() if admin_rights is None else admin_rights
        self.clock = clock
        self.db = db  # None = loadouts are switched off (say the database wouldn't open)
        self.editor = None  # the "Edit loadouts" window while it's open
        self.sites = []  # the Listbox just shows these two lists
        self.apps = []
        self.until = {}  # site -> when it gets unblocked (None = when you unblock it)
        self.app_until = {}  # same for apps, kept in the database
        self._tick_job = None
        self._sweep_job = None

        root.title("XamGuard")
        root.minsize(420, 640)
        root.protocol("WM_DELETE_WINDOW", self.on_close)  # the X button
        self.pack(fill="both", expand=True)

        self.site_text = tk.StringVar()
        self.length_text = tk.StringVar(value=list(DURATIONS)[0])
        self.status_text = tk.StringVar()
        self._build()
        self.refresh()
        self.refresh_loadouts()
        if self.admin_rights:
            self.end_expired()  # timed blocks that ended while the app was closed
        self.end_expired_apps()
        self._schedule_tick()
        self._schedule_sweep()

    # ---------- building the window ----------

    def _build(self):
        # title and motto on the left, the logo in the top right corner
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 12))
        header.columnconfigure(0, weight=1)  # the text column takes the spare width
        header.rowconfigure(2, weight=1)  # and spare height goes below the text, not between
        ttk.Label(header, text="XamGuard", font=("Segoe UI", 22, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text="Master your focus. Eliminate distractions.").grid(
            row=1, column=0, sticky="w"
        )

        # keep a reference on self, or Python throws the image away and Tk shows nothing
        self.logo_image = load_logo(self)
        self.logo_label = None
        if self.logo_image is not None:
            self.logo_label = ttk.Label(header, image=self.logo_image)
            self.logo_label.grid(row=0, column=1, rowspan=3, sticky="ne", padx=(12, 0))

        if not self.admin_rights:
            self._build_admin_banner()

        form = ttk.LabelFrame(self, text="Block a site", padding=12)
        form.pack(fill="x")
        siterow = ttk.Frame(form)
        siterow.pack(fill="x")
        self.entry = ttk.Entry(siterow, textvariable=self.site_text)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda event: self.on_block())
        self.entry.focus_set()
        self.block_button = ttk.Button(siterow, text="Block", command=self.on_block)
        self.block_button.pack(side="left", padx=(8, 0))

        lengthrow = ttk.Frame(form)
        lengthrow.pack(fill="x", pady=(8, 0))
        ttk.Label(lengthrow, text="For").pack(side="left")
        self.length_box = ttk.Combobox(
            lengthrow,
            textvariable=self.length_text,
            values=list(DURATIONS),
            state="readonly",  # pick from the list, no typing
            width=18,
        )
        self.length_box.pack(side="left", padx=(8, 0))
        ttk.Label(self, text="e.g. youtube.com, facebook.com", foreground="gray").pack(
            anchor="w", pady=(4, 0)
        )

        loadouts = ttk.LabelFrame(self, text="Loadouts", padding=12)
        loadouts.pack(fill="x", pady=(12, 0))
        pickrow = ttk.Frame(loadouts)
        pickrow.pack(fill="x")
        self.loadout_text = tk.StringVar()
        self.loadout_box = ttk.Combobox(pickrow, textvariable=self.loadout_text, state="readonly")
        self.loadout_box.pack(side="left", fill="x", expand=True)
        self.loadout_button = ttk.Button(
            pickrow, text="Block loadout", command=self.on_block_loadout
        )
        self.loadout_button.pack(side="left", padx=(8, 0))

        editrow = ttk.Frame(loadouts)
        editrow.pack(fill="x", pady=(8, 0))
        ttk.Label(editrow, text='Uses the "For" time above.', foreground="gray").pack(side="left")
        self.edit_button = ttk.Button(
            editrow, text="Edit loadouts...", command=self.on_edit_loadouts
        )
        self.edit_button.pack(side="right")

        self.listing = ttk.LabelFrame(self, text="Currently blocked", padding=12)
        self.listing.pack(fill="both", expand=True, pady=(12, 0))

        listarea = ttk.Frame(self.listing)
        listarea.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            listarea, selectmode="extended", activestyle="none", font=("Segoe UI", 11),
            height=7,  # the default 10 rows made the window taller than a 1080p screen
        )
        scrollbar = ttk.Scrollbar(listarea, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)

        self.unblock_button = ttk.Button(
            self.listing, text="Unblock selected", command=self.on_unblock
        )
        self.unblock_button.pack(anchor="e", pady=(8, 0))

        self.status_label = ttk.Label(self, textvariable=self.status_text, wraplength=380)
        self.status_label.pack(anchor="w", pady=(10, 0))

        if not self.admin_rights:
            self.block_button.state(["disabled"])
            self.unblock_button.state(["disabled"])

    def _build_admin_banner(self):
        # plain tk here, ttk can't set a background color
        banner = tk.Frame(self, background="#fff4e5", padx=10, pady=8)
        banner.pack(fill="x", pady=(0, 12))
        tk.Label(
            banner,
            text="Not running as administrator, so sites can't be blocked or unblocked.",
            background="#fff4e5",
            wraplength=360,
            justify="left",
        ).pack(anchor="w")
        ttk.Button(
            banner, text="Restart as Administrator", command=self.on_elevate
        ).pack(anchor="w", pady=(6, 0))

    # ---------- keeping the screen in sync ----------

    def say(self, text, error=False):
        self.status_text.set(text)
        self.status_label.configure(foreground=BAD if error else GOOD)

    def refresh(self):
        """Reload the list: sites from the hosts file, apps from the database."""
        keep = self.selected_items()
        try:
            self.until = hostfileservice.list_blocked_until()
        except OSError as error:
            self.until = {}
            self.say(str(error), error=True)

        self.app_until = {}
        if self.db is not None:
            try:
                self.app_until = self.db.app_blocks_until()
            except sqlite3.Error as error:
                self.say(str(error), error=True)

        self.sites = sorted(self.until)
        self.apps = sorted(self.app_until)
        self.draw_rows(keep)
        self.listing.configure(text=f"Currently blocked ({len(self.sites) + len(self.apps)})")

    def listed_items(self):
        """Everything in the list, top to bottom: ('site', name) then ('app', name)."""
        return [("site", site) for site in self.sites] + [("app", app) for app in self.apps]

    def draw_rows(self, keep=()):
        """Show the sites and apps in the list, with the time left on timed ones.

        keep: items (like ('site', 'a.com')) that should stay selected, since redrawing
        would clear the selection.
        """
        now = self.clock()
        items = self.listed_items()
        rows = [self.rowtext(kind, name, now) for kind, name in items] or [PLACEHOLDER]
        if list(self.listbox.get(0, "end")) == rows:
            return  # nothing changed

        top = self.listbox.yview()[0]  # scroll position
        self.listbox.delete(0, "end")
        for row in rows:
            self.listbox.insert("end", row)
        if not items:
            self.listbox.itemconfig(0, foreground="gray")

        for index, item in enumerate(items):
            if item in keep:
                self.listbox.selection_set(index)
        self.listbox.yview_moveto(top)

    def rowtext(self, kind, name, now):
        until = self.until.get(name) if kind == "site" else self.app_until.get(name)
        label = name if kind == "site" else f"{name} {APP_TAG}"
        if until is None:
            return label
        if until <= now:
            return f"{label}   (time's up)"
        return f"{label}   ({formatremaining(until - now)} left)"

    def selected_items(self):
        # row numbers -> items. the placeholder row isn't in the list, so it's skipped
        items = self.listed_items()
        return [items[row] for row in self.listbox.curselection() if row < len(items)]

    def selected_sites(self):
        return [name for kind, name in self.selected_items() if kind == "site"]

    def selected_apps(self):
        return [name for kind, name in self.selected_items() if kind == "app"]

    # ---------- timed blocks ----------

    def tick(self):
        """Runs once a second: ends timed blocks that are up, updates the countdowns."""
        try:
            if self.admin_rights and any(
                until is not None and until <= self.clock() for until in self.until.values()
            ):
                self.end_expired()
            self.draw_rows(self.selected_items())
        finally:
            self._schedule_tick()  # even if something failed, keep the clock going

    def end_expired(self):
        """Unblock timed sites whose time is up (this also catches ones that ended while closed)."""
        try:
            done = hostfileservice.unblock_expired(self.clock())
        except OSError as error:
            self.say(str(error), error=True)
            return

        if done:
            self.refresh()
            self.say("Time's up. Unblocked: " + ", ".join(done))

    # ---------- blocked apps ----------

    def sweep_apps(self):
        """Runs every 2 seconds: ends app blocks that are up, closes blocked apps that are running."""
        try:
            self.end_expired_apps()
            closed = self.close_blocked_apps()
            if closed:
                self.say("Closed: " + ", ".join(closed))
        finally:
            self._schedule_sweep()  # same as tick: keep going even if this round failed

    def close_blocked_apps(self):
        """Close every blocked app that's running right now. Returns the names it closed."""
        if not self.app_until or not appblocker.available():
            return []
        return appblocker.sweep(self.app_until)

    def end_expired_apps(self):
        """Unblock timed apps whose time is up (this also catches ones that ended while closed)."""
        if self.db is None:
            return
        try:
            done = self.db.unblock_expired_apps(self.clock())
        except sqlite3.Error as error:
            self.say(str(error), error=True)
            return

        if done:
            self.refresh()
            self.say("Time's up. Unblocked: " + ", ".join(done))

    def _schedule_tick(self):
        if self._tick_job:
            self.after_cancel(self._tick_job)
        self._tick_job = self.after(1000, self.tick)

    def _schedule_sweep(self):
        if self._sweep_job:
            self.after_cancel(self._sweep_job)
        self._sweep_job = self.after(SWEEP_MS, self.sweep_apps)

    def destroy(self):
        # after() jobs belong to Tk, not to this frame, so they'd outlive it
        if self._tick_job:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        if self._sweep_job:
            self.after_cancel(self._sweep_job)
            self._sweep_job = None
        if self.editor is not None:
            try:
                self.editor.destroy()  # it belongs to the root, not to this frame
            except tk.TclError:
                pass  # already gone
        super().destroy()

    # ---------- reacting to clicks ----------

    def on_block(self):
        if not self._need_admin():
            return

        sites = splitinput(self.site_text.get())
        if not sites:
            self.say("Type a site to block, like youtube.com.", error=True)
            return

        self._start_block(sites, clear_entry=True)

    def on_block_loadout(self):
        if not self._need_admin():
            return
        if self.db is None:
            self.say("Loadouts are unavailable.", error=True)
            return

        try:
            loadout = self.db.get_loadout(self.loadout_text.get())
        except sqlite3.Error as error:
            self.say(str(error), error=True)
            return

        if not loadout or not (loadout["sites"] or loadout["apps"]):
            self.say("That loadout has no sites or apps to block.", error=True)
            return
        self._start_block(loadout["sites"], loadout["apps"], label=loadout["name"])

    def _start_block(self, sites, apps=(), label=None, clear_entry=False):
        """Block the sites and apps for the time in the "For" box. label = the loadout's name."""
        minutes = DURATIONS[self.length_text.get()]
        until = None if minutes is None else self.clock() + minutes * 60

        try:
            added_sites = hostfileservice.block(sites, until=until) if sites else []
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)
            return

        # apps can't go in the hosts file, so they go in the database and the sweep closes them
        added_apps, app_problem = [], None
        if apps:
            if self.db is None or not appblocker.available():
                app_problem = "The apps weren't blocked: app blocking needs psutil (pip install psutil)."
            else:
                try:
                    added_apps = self.db.block_apps(apps, until=until)
                except (ValueError, sqlite3.Error) as error:
                    app_problem = str(error)

        if clear_entry:
            self.site_text.set("")
        self.refresh()

        added = hostfileservice.plainsites(added_sites) + [f"{app} {APP_TAG}" for app in added_apps]
        if added:
            length = "" if minutes is None else f" for {self.length_text.get()}"
            who = f"{label} loadout blocked" if label else "Blocked"
            text = f"{who}{length}: " + ", ".join(added)
            if added_apps:
                text += ". Apps are only closed while XamGuard is open."
                closed = self.close_blocked_apps()  # don't wait for the next sweep
                if closed:
                    text += " Closed now: " + ", ".join(closed) + "."
        elif label:
            text = f"Everything in {label} was already blocked."
        else:
            text = "Those sites were already blocked."

        if app_problem:
            text = f"{text} {app_problem}" if added else app_problem
        self.say(text, error=bool(app_problem))

    def on_edit_loadouts(self):
        if self.db is None:
            return
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.lift()  # already open, don't make a second one
            return
        self.editor = LoadoutEditor(self.root, self.db, on_change=self.refresh_loadouts)

    def refresh_loadouts(self):
        """Reload the loadout names into the dropdown, and enable or disable the buttons."""
        names = []
        if self.db is not None:
            try:
                names = self.db.loadout_names()
            except sqlite3.Error as error:
                self.say(str(error), error=True)

        self.loadout_box.configure(values=names)
        if self.loadout_text.get() not in names:  # keep the pick if it still exists
            empty = NO_LOADOUTS if self.db is not None else LOADOUTS_OFF
            self.loadout_text.set(names[0] if names else empty)

        can_block = bool(names) and self.admin_rights
        self.loadout_button.state(["!disabled" if can_block else "disabled"])
        self.edit_button.state(["!disabled" if self.db is not None else "disabled"])

    def on_unblock(self):
        if not self._need_admin():
            return

        sites, apps = self.selected_sites(), self.selected_apps()
        if not (sites or apps):
            self.say("Select one or more sites or apps in the list first.", error=True)
            return

        removed, removed_apps = [], []
        try:
            if sites:
                removed = hostfileservice.unblock(sites)
            if apps and self.db is not None:
                removed_apps = self.db.unblock_apps(apps)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.say(str(error), error=True)
            return

        self.refresh()
        names = hostfileservice.plainsites(removed) + [f"{app} {APP_TAG}" for app in removed_apps]
        if names:
            self.say("Unblocked: " + ", ".join(names))
        else:
            self.say("Those were no longer blocked.")

    def on_close(self):
        """The window's X button. Apps are only blocked while we're open, so ask first."""
        now = self.clock()
        active = [app for app, until in self.app_until.items() if until is None or until > now]
        if active and not messagebox.askyesno(
            "Close XamGuard?",
            "Blocked apps are only closed while XamGuard is open.\n"
            f"Still blocked: {', '.join(active)}\n\nClose it anyway?",
            parent=self.root,
        ):
            return
        self.root.destroy()

    def on_elevate(self):
        if admin.relaunch_as_admin():
            self.root.destroy()  # the admin copy takes over
        else:
            self.say("Administrator permission was not granted.", error=True)

    def _need_admin(self):
        if self.admin_rights:
            return True
        self.say("Restart as administrator to block or unblock sites.", error=True)
        return False


class LoadoutEditor(tk.Toplevel):
    """The "Edit loadouts" window: pick one on the left, edit it on the right."""

    def __init__(self, parent, db, on_change=None):
        super().__init__(parent)
        self.db = db
        self.on_change = on_change  # called after a save or a delete
        self.names = []  # the Listbox just shows this list
        self.current = None  # name of the loadout being edited, None = a new one
        self.picker = None  # the "running apps" window while it's open

        self.title("Edit loadouts")
        self.minsize(560, 520)
        self.transient(parent)
        self.name_text = tk.StringVar()
        self.status_text = tk.StringVar()
        self._build()
        self.refresh_names()

    def _build(self):
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        # exportselection=False: otherwise clicking in the Sites box deselects the loadout
        self.listbox = tk.Listbox(
            left, exportselection=False, activestyle="none", width=22, font=("Segoe UI", 11)
        )
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda event: self.on_pick())
        ttk.Button(left, text="New loadout", command=self.on_new).pack(fill="x", pady=(8, 0))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        ttk.Label(right, text="Name").pack(anchor="w")
        self.name_entry = ttk.Entry(right, textvariable=self.name_text)
        self.name_entry.pack(fill="x")
        ttk.Label(right, text="Sites (separate with commas, spaces or new lines)").pack(
            anchor="w", pady=(10, 0)
        )
        self.sites_box = tk.Text(right, height=6, width=30, font=("Segoe UI", 11), wrap="word")
        self.sites_box.pack(fill="both", expand=True)

        ttk.Label(right, text="Apps (one per line, or separated by commas)").pack(
            anchor="w", pady=(10, 0)
        )
        self.apps_box = tk.Text(right, height=4, width=30, font=("Segoe UI", 11), wrap="word")
        self.apps_box.pack(fill="both", expand=True)
        self.pick_button = ttk.Button(
            right, text="Pick from running apps...", command=self.on_pick_running
        )
        self.pick_button.pack(anchor="w", pady=(4, 0))
        if not appblocker.available():
            self.pick_button.state(["disabled"])  # it needs psutil to see what's running

        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(8, 0))
        self.save_button = ttk.Button(buttons, text="Save", command=self.on_save)
        self.save_button.pack(side="left")
        self.delete_button = ttk.Button(buttons, text="Delete", command=self.on_delete)
        self.delete_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")

        self.status_label = ttk.Label(right, textvariable=self.status_text, wraplength=300)
        self.status_label.pack(anchor="w", pady=(8, 0))

    def say(self, text, error=False):
        self.status_text.set(text)
        self.status_label.configure(foreground=BAD if error else GOOD)

    def refresh_names(self, select=None):
        try:
            self.names = self.db.loadout_names()
        except sqlite3.Error as error:
            self.names = []
            self.say(str(error), error=True)

        self.listbox.delete(0, "end")
        for name in self.names:
            self.listbox.insert("end", name)
        if select in self.names:
            self.listbox.selection_set(self.names.index(select))

    def on_pick(self):
        picked = self.listbox.curselection()
        if not picked:
            return

        try:
            loadout = self.db.get_loadout(self.names[picked[0]])
        except sqlite3.Error as error:
            self.say(str(error), error=True)
            return
        if loadout is None:
            return

        self.current = loadout["name"]
        self.name_text.set(loadout["name"])
        self.sites_box.delete("1.0", "end")
        self.sites_box.insert("1.0", "\n".join(loadout["sites"]))
        self.apps_box.delete("1.0", "end")
        self.apps_box.insert("1.0", "\n".join(loadout["apps"]))
        self.say("")

    def on_new(self):
        self.listbox.selection_clear(0, "end")
        self.current = None
        self.name_text.set("")
        self.sites_box.delete("1.0", "end")
        self.apps_box.delete("1.0", "end")
        self.name_entry.focus_set()
        self.say("")

    def on_save(self):
        name = self.name_text.get().strip()
        sites = splitinput(self.sites_box.get("1.0", "end"))
        apps = splitapps(self.apps_box.get("1.0", "end"))

        try:
            # save_loadout replaces a loadout that already has this name. fine when editing,
            # but a "new" one must not quietly overwrite somebody else's
            if self.current is None and self.db.get_loadout(name):
                self.say(f"'{name}' already exists. Pick it in the list to edit it.", error=True)
                return
            saved = self.db.save_loadout(name, sites, apps=apps, old_name=self.current)
        except (ValueError, sqlite3.Error) as error:
            self.say(str(error), error=True)
            return

        self.current = saved
        self.refresh_names(select=saved)
        self.say(f"Saved {saved}.")
        self._changed()

    def on_delete(self):
        if self.current is None:
            self.say("Pick a loadout to delete first.", error=True)
            return
        if not messagebox.askyesno("Delete loadout", f"Delete '{self.current}'?", parent=self):
            return

        gone = self.current
        try:
            self.db.delete_loadout(gone)
        except sqlite3.Error as error:
            self.say(str(error), error=True)
            return

        self.on_new()
        self.refresh_names()
        self.say(f"Deleted {gone}.")
        self._changed()

    def on_pick_running(self):
        if self.picker is not None and self.picker.winfo_exists():
            self.picker.lift()  # already open
            return
        self.picker = AppPicker(self, on_add=self.add_apps)

    def add_apps(self, names):
        """Add apps to the Apps box, skipping ones that are already in there."""
        current = splitapps(self.apps_box.get("1.0", "end"))
        have = {name.lower() for name in current}
        current += [name for name in names if name.lower() not in have]
        self.apps_box.delete("1.0", "end")
        self.apps_box.insert("1.0", "\n".join(current))

    def _changed(self):
        if self.on_change:
            self.on_change()


class AppPicker(tk.Toplevel):
    """A list of the apps running right now. Pick some, click Add."""

    def __init__(self, parent, on_add):
        super().__init__(parent)
        self.on_add = on_add
        self.names = []  # the Listbox just shows this list

        self.title("Running apps")
        self.minsize(300, 380)
        self.transient(parent)

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Your running apps (Ctrl or Shift to pick several)").pack(anchor="w")

        area = ttk.Frame(body)
        area.pack(fill="both", expand=True, pady=(6, 0))
        self.listbox = tk.Listbox(
            area, selectmode="extended", exportselection=False, activestyle="none",
            font=("Segoe UI", 11),
        )
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.add_button = ttk.Button(buttons, text="Add selected", command=self.on_add_selected)
        self.add_button.pack(side="left")
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")

        self.refresh()

    def refresh(self):
        self.names = appblocker.running_apps()
        self.listbox.delete(0, "end")
        for name in self.names:
            self.listbox.insert("end", name)

    def on_add_selected(self):
        chosen = [self.names[row] for row in self.listbox.curselection()]
        if chosen:
            self.on_add(chosen)
        self.destroy()


def show_unexpected_error(exc_type, exc, tb):
    """Popup for crashes in button handlers (no console to print to once packaged)."""
    traceback.print_exception(exc_type, exc, tb)
    messagebox.showerror("XamGuard", f"Something went wrong:\n\n{exc}")


def run():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharper text on high-DPI screens
    except (AttributeError, OSError):
        pass

    # if the database won't open, blocking still works, just without loadouts
    database, problem = None, None
    try:
        database = Database()
    except (sqlite3.Error, OSError) as error:
        problem = str(error)

    root = tk.Tk()
    root.report_callback_exception = show_unexpected_error
    app = XamGuardApp(root, db=database)
    if problem:
        app.say(f"Loadouts are off, the database wouldn't open: {problem}", error=True)
    root.mainloop()

    if database is not None:
        database.close()
