"""The XamGuard window.

Just buttons and clicks. All the hosts file work lives in hostfileservice.py.
"""

import ctypes
import re
import traceback
import tkinter as tk
from tkinter import messagebox, ttk

from . import admin, hostfileservice

GOOD = "#1b5e20"
BAD = "#b00020"
PLACEHOLDER = "No sites are blocked. You are free to roam (carefully)."


def splitinput(text):
    """'a.com, b.com c.com' -> ['a.com', 'b.com', 'c.com']"""
    return [piece for piece in re.split(r"[,\s]+", text) if piece]


class XamGuardApp(ttk.Frame):
    def __init__(self, root, admin_rights=None):
        super().__init__(root, padding=16)
        self.root = root
        # a parameter so tests can fake being admin
        self.admin_rights = admin.is_admin() if admin_rights is None else admin_rights
        self.sites = []  # the Listbox just shows this list

        root.title("XamGuard")
        root.minsize(420, 480)
        self.pack(fill="both", expand=True)

        self.site_text = tk.StringVar()
        self.status_text = tk.StringVar()
        self._build()
        self.refresh()

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
        self.entry = ttk.Entry(form, textvariable=self.site_text)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda event: self.on_block())
        self.entry.focus_set()
        self.block_button = ttk.Button(form, text="Block", command=self.on_block)
        self.block_button.pack(side="left", padx=(8, 0))
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
        try:
            self.sites = hostfileservice.list_blocked()
        except OSError as error:
            self.sites = []
            self.say(str(error), error=True)

        self.listbox.delete(0, "end")
        for site in self.sites:
            self.listbox.insert("end", site)
        if not self.sites:
            self.listbox.insert("end", PLACEHOLDER)
            self.listbox.itemconfig(0, foreground="gray")

        self.listing.configure(text=f"Currently blocked ({len(self.sites)})")

    # ---------- reacting to clicks ----------

    def on_block(self):
        if not self._need_admin():
            return

        sites = splitinput(self.site_text.get())
        if not sites:
            self.say("Type a site to block, like youtube.com.", error=True)
            return

        try:
            added = hostfileservice.block(sites)
        except (ValueError, OSError) as error:
            self.say(str(error), error=True)
            return

        self.site_text.set("")
        self.refresh()
        if added:
            self.say("Blocked: " + ", ".join(hostfileservice.plainsites(added)))
        else:
            self.say("Those sites were already blocked.")

    def on_unblock(self):
        if not self._need_admin():
            return

        # row numbers -> names. the placeholder row isn't in self.sites, so it's skipped
        chosen = [self.sites[row] for row in self.listbox.curselection() if row < len(self.sites)]
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
