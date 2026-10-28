"""Closes the apps you've blocked.

Sites get blocked by the hosts file and Windows enforces that on its own. There's no hosts
file for apps, so something has to keep checking what's running and close the blocked ones.
"""

import os

try:
    import psutil
except ImportError:  # app blocking switches off, the rest of XamGuard still works
    psutil = None

# never closed, even if one of these ends up on the list: windows itself, the shells you
# might have started XamGuard from, and XamGuard
PROTECTED = {
    "system", "system idle process", "registry", "memory compression", "secure system",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "svchost.exe", "fontdrvhost.exe", "dwm.exe", "explorer.exe", "sihost.exe",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "ctfmon.exe", "audiodg.exe", "spoolsv.exe", "dllhost.exe",
    "conhost.exe", "taskmgr.exe", "logonui.exe", "msmpeng.exe", "securityhealthservice.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe",
    "python.exe", "pythonw.exe", "py.exe", "xamguard.exe",
}

BAD_CHARS = set('\\/:*?"<>|')  # can't be in a file name, so can't be in a process name

# what psutil raises when a process is already gone or off limits
PROCESS_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied) if psutil else (OSError,)


def available():
    return psutil is not None


def normalizeapp(text):
    """'Spotify' -> 'spotify.exe'. ValueError if it can't be an app name or it's protected."""
    name = text.strip().strip("\"'").strip().lower()

    if not name.strip(". ") or any(c in BAD_CHARS or ord(c) < 32 for c in name):
        raise ValueError(f"'{text.strip()}' isn't a valid app name (try something like spotify.exe)")
    if "." not in name:
        name += ".exe"
    if name in PROTECTED:
        raise ValueError(f"{name} is protected and can't be blocked, closing it could break Windows or XamGuard")
    return name


def current_user():
    return psutil.Process().username()


def safe_pids():
    """This program and everything that started it (the terminal, say). Never closed."""
    pids = {os.getpid()}
    try:
        pids.update(parent.pid for parent in psutil.Process().parents())
    except PROCESS_ERRORS:
        pass
    return pids


def sweep(blocked, processes=None, me=None, keep=None):
    """Close every running process whose name is in blocked. Returns the names it closed.

    processes, me and keep are only here so tests can hand in fake ones. Real use leaves
    them out.
    """
    blocked = {name.lower() for name in blocked}
    if not blocked:
        return []  # nothing to look for, so don't even scan
    if processes is None:
        if psutil is None:
            return []
        processes = psutil.process_iter(["name"])

    me = me or current_user()
    keep = safe_pids() if keep is None else keep
    closed = set()

    for proc in processes:
        name = (proc.info.get("name") or "").lower()
        if name not in blocked or name in PROTECTED or proc.pid in keep:
            continue

        try:
            if proc.username() != me:  # only your own programs, never somebody else's
                continue
            proc.terminate()
            closed.add(name)
        except PROCESS_ERRORS:
            continue  # it closed by itself, or we're not allowed to. move on to the next

    return sorted(closed)


def running_apps(processes=None, me=None):
    """Names of apps you could block: your own running programs, minus the protected ones."""
    if processes is None:
        if psutil is None:
            return []
        processes = psutil.process_iter(["name"])

    me = me or current_user()
    names = set()
    for proc in processes:
        name = (proc.info.get("name") or "").lower()
        if not name.endswith(".exe") or name in PROTECTED or name in names:
            continue
        try:
            if proc.username() == me:
                names.add(name)
        except PROCESS_ERRORS:
            continue
    return sorted(names)
