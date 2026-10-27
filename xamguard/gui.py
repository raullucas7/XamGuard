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
from tkinter import messagebox, ttk

from . import admin, hostfileservice
from .db import Database

GOOD = "#1b5e20"
BAD = "#b00020"
PLACEHOLDER = "No sites are blocked. You are free to roam (carefully)."
NO_LOADOUTS = "(no loadouts yet)"
LOADOUTS_OFF = "(loadouts unavailable)"

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


def formatremaining(seconds):
    """3725 -> '1:02:05', 1450 -> '24:10'. rounds up so it never shows 0:00 early."""
    seconds = math.ceil(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes}:{secs:02}"


class XamGuardApp(ttk.Frame):
    def __init__(self, root, admin_rights=None, clock=time.time, db=None):
        super().__init__(root, padding=16)
        self.root = root
        # parameters so tests can fake being admin, the time and the database
        self.admin_rights = admin.is_admin() if admin_rights is None else admin_rights
        self.clock = clock
        self.db = db  # None = loadouts are switched off (say the database wouldn't open)
        self.editor = None  # the "Edit loadouts" window while it's open
        self.sites = []  # the Listbox just shows this list
        self.until = {}  # site -> when it gets unblocked (None = when you unblock it)
        self._tick_job = None

        root.title("XamGuard")
        root.minsize(420, 640)
        self.pack(fill="both", expand=True)

        self.site_text = tk.StringVar()
        self.length_text = tk.StringVar(value=list(DURATIONS)[0])
        self.status_text = tk.StringVar()
        self._build()
        self.refresh()
        self.refresh_loadouts()
        if self.admin_rights:
            self.end_expired()  # timed blocks that ended while the app was closed
        self._schedule_tick()

    # ---------- building the window ----------

    def _build(self):
        ttk.Label(self, text="XamGuard", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(self, text="Master your focus. Eliminate distractions.").pack(
            anchor="w", pady=(0, 12)
        )

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
            listarea, selectmode="extended", activestyle="none", font=("Segoe UI", 11)
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
        """Reload the list from the hosts file."""
        keep = self.selected_sites()
        try:
            self.until = hostfileservice.list_blocked_until()
        except OSError as error:
            self.until = {}
            self.say(str(error), error=True)

        self.sites = sorted(self.until)
        self.draw_rows(keep)
        self.listing.configure(text=f"Currently blocked ({len(self.sites)})")

    def draw_rows(self, keep=()):
        """Show self.sites in the list, with the time left on timed ones.

        keep: sites that should stay selected (redrawing would clear the selection).
        """
        now = self.clock()
        rows = [self.rowtext(site, now) for site in self.sites] or [PLACEHOLDER]
        if list(self.listbox.get(0, "end")) == rows:
            return  # nothing changed

        top = self.listbox.yview()[0]  # scroll position
        self.listbox.delete(0, "end")
        for row in rows:
            self.listbox.insert("end", row)
        if not self.sites:
            self.listbox.itemconfig(0, foreground="gray")

        for index, site in enumerate(self.sites):
            if site in keep:
                self.listbox.selection_set(index)
        self.listbox.yview_moveto(top)

    def rowtext(self, site, now):
        until = self.until.get(site)
        if until is None:
            return site
        if until <= now:
            return f"{site}   (time's up)"
        return f"{site}   ({formatremaining(until - now)} left)"

    def selected_sites(self):
        # row numbers -> names. the placeholder row isn't in self.sites, so it's skipped
        return [self.sites[row] for row in self.listbox.curselection() if row < len(self.sites)]

    # ---------- timed blocks ----------

    def tick(self):
        """Runs once a second: ends timed blocks that are up, updates the countdowns."""
        try:
            if self.admin_rights and any(
                until is not None and until <= self.clock() for until in self.until.values()
            ):
                self.end_expired()
            self.draw_rows(self.selected_sites())
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

    def _schedule_tick(self):
        if self._tick_job:
            self.after_cancel(self._tick_job)
        self._tick_job = self.after(1000, self.tick)

    def destroy(self):
        # after() jobs belong to Tk, not to this frame, so they'd outlive it
        if self._tick_job:
            self.after_cancel(self._tick_job)
            self._tick_job = None
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

        self._block_sites(sites, clear_entry=True)

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

        if not loadout or not loadout["sites"]:
            self.say("That loadout has no sites to block.", error=True)
            return
        self._block_sites(loadout["sites"], label=loadout["name"])

    def _block_sites(self, sites, label=None, clear_entry=False):
        """Block the sites for the time in the "For" box. label = the loadout's name, if any."""
        minutes = DURATIONS[self.length_text.get()]
        until = None if minutes is None else self.clock() + minutes * 60

        try:
            added = hostfileservice.block(sites, until=until)
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)
            return

        if clear_entry:
            self.site_text.set("")
        self.refresh()
        if added:
            length = "" if minutes is None else f" for {self.length_text.get()}"
            who = f"{label} loadout blocked" if label else "Blocked"
            self.say(f"{who}{length}: " + ", ".join(hostfileservice.plainsites(added)))
        elif label:
            self.say(f"Everything in {label} was already blocked.")
        else:
            self.say("Those sites were already blocked.")

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

        chosen = self.selected_sites()
        if not chosen:
            self.say("Select one or more sites in the list first.", error=True)
            return

        try:
            removed = hostfileservice.unblock(chosen)
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)
            return

        self.refresh()
        if removed:
            self.say("Unblocked: " + ", ".join(hostfileservice.plainsites(removed)))
        else:
            self.say("Those sites were no longer blocked.")

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
        self.apps = []  # kept as they are for now, so saving doesn't wipe them

        self.title("Edit loadouts")
        self.minsize(540, 360)
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
        self.sites_box = tk.Text(right, height=10, width=30, font=("Segoe UI", 11), wrap="word")
        self.sites_box.pack(fill="both", expand=True)

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
        self.apps = loadout["apps"]
        self.name_text.set(loadout["name"])
        self.sites_box.delete("1.0", "end")
        self.sites_box.insert("1.0", "\n".join(loadout["sites"]))
        self.say("")

    def on_new(self):
        self.listbox.selection_clear(0, "end")
        self.current = None
        self.apps = []
        self.name_text.set("")
        self.sites_box.delete("1.0", "end")
        self.name_entry.focus_set()
        self.say("")

    def on_save(self):
        name = self.name_text.get().strip()
        sites = splitinput(self.sites_box.get("1.0", "end"))

        try:
            # save_loadout replaces a loadout that already has this name. fine when editing,
            # but a "new" one must not quietly overwrite somebody else's
            if self.current is None and self.db.get_loadout(name):
                self.say(f"'{name}' already exists. Pick it in the list to edit it.", error=True)
                return
            saved = self.db.save_loadout(name, sites, apps=self.apps, old_name=self.current)
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

    def _changed(self):
        if self.on_change:
            self.on_change()


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
