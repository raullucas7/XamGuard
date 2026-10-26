"""The XamGuard window.

Just buttons and clicks. All the hosts file work lives in hostfileservice.py.
"""

import ctypes
import math
import re
import time
import traceback
import tkinter as tk
from tkinter import messagebox, ttk

from . import admin, hostfileservice

GOOD = "#1b5e20"
BAD = "#b00020"
PLACEHOLDER = "No sites are blocked. You are free to roam (carefully)."

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
    def __init__(self, root, admin_rights=None, clock=time.time):
        super().__init__(root, padding=16)
        self.root = root
        # parameters so tests can fake being admin and fake the time
        self.admin_rights = admin.is_admin() if admin_rights is None else admin_rights
        self.clock = clock
        self.sites = []  # the Listbox just shows this list
        self.until = {}  # site -> when it gets unblocked (None = when you unblock it)
        self._tick_job = None

        root.title("XamGuard")
        root.minsize(420, 520)
        self.pack(fill="both", expand=True)

        self.site_text = tk.StringVar()
        self.length_text = tk.StringVar(value=list(DURATIONS)[0])
        self.status_text = tk.StringVar()
        self._build()
        self.refresh()
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
        super().destroy()

    # ---------- reacting to clicks ----------

    def on_block(self):
        if not self._need_admin():
            return

        sites = splitinput(self.site_text.get())
        if not sites:
            self.say("Type a site to block, like youtube.com.", error=True)
            return

        minutes = DURATIONS[self.length_text.get()]
        until = None if minutes is None else self.clock() + minutes * 60

        try:
            added = hostfileservice.block(sites, until=until)
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)
            return

        self.site_text.set("")
        self.refresh()
        if added:
            length = "" if minutes is None else f" for {self.length_text.get()}"
            self.say(f"Blocked{length}: " + ", ".join(hostfileservice.plainsites(added)))
        else:
            self.say("Those sites were already blocked.")

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


def show_unexpected_error(exc_type, exc, tb):
    """Popup for crashes in button handlers (no console to print to once packaged)."""
    traceback.print_exception(exc_type, exc, tb)
    messagebox.showerror("XamGuard", f"Something went wrong:\n\n{exc}")


def run():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharper text on high-DPI screens
    except (AttributeError, OSError):
        pass

    root = tk.Tk()
    root.report_callback_exception = show_unexpected_error
    XamGuardApp(root)
    root.mainloop()
