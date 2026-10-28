import os
import shutil
import subprocess
import sys
import time

import psutil
import pytest

from xamguard import appblocker


class FakeProc:
    """Looks enough like a psutil process, and closing it only sets a flag."""

    def __init__(self, pid, name, user="me", error=None, user_error=None):
        self.pid = pid
        self.info = {"name": name}
        self.user = user
        self.error = error  # raised when we try to close it
        self.user_error = user_error  # raised when we ask who owns it
        self.closed = False

    def username(self):
        if self.user_error:
            raise self.user_error
        return self.user

    def terminate(self):
        if self.error:
            raise self.error
        self.closed = True


def sweep(blocked, procs, keep=()):
    return appblocker.sweep(blocked, processes=procs, me="me", keep=set(keep))


# ---------- normalizeapp ----------

@pytest.mark.parametrize("text, expected", [
    ("spotify", "spotify.exe"),
    ("Spotify.EXE", "spotify.exe"),
    ("  steam  ", "steam.exe"),
    ('"chrome.exe"', "chrome.exe"),
    ("Origin Web Helper Service", "origin web helper service.exe"),
    ("notepad++.exe", "notepad++.exe"),
])
def test_normalizeapp_cleans_names(text, expected):
    assert appblocker.normalizeapp(text) == expected


@pytest.mark.parametrize("text", [
    "", "   ", ".", "...",
    r"C:\Program Files\App\app.exe",  # a path, not a name
    "a/b.exe", "bad*name", "what?.exe", "pipe|.exe", "tab\tname",
])
def test_normalizeapp_rejects_things_that_cannot_be_a_process_name(text):
    with pytest.raises(ValueError, match="valid app name"):
        appblocker.normalizeapp(text)


@pytest.mark.parametrize("text", ["explorer", "EXPLORER.EXE", "svchost", "python", "cmd", "pwsh", "taskmgr"])
def test_normalizeapp_refuses_protected_apps(text):
    with pytest.raises(ValueError, match="protected"):
        appblocker.normalizeapp(text)


def test_everything_protected_is_lowercase():
    # the checks compare lowercase names, so an uppercase entry would never match
    assert all(name == name.lower() for name in appblocker.PROTECTED)


# ---------- sweep, with fake processes ----------

def test_sweep_closes_only_exact_name_matches():
    target = FakeProc(1, "spotify.exe")
    lookalike = FakeProc(2, "notspotify.exe")
    other = FakeProc(3, "spotify-helper.exe")

    closed = sweep({"spotify.exe"}, [target, lookalike, other])

    assert closed == ["spotify.exe"]
    assert (target.closed, lookalike.closed, other.closed) == (True, False, False)


def test_sweep_ignores_capital_letters():
    proc = FakeProc(1, "Spotify.EXE")
    assert sweep({"spotify.exe"}, [proc]) == ["spotify.exe"]
    assert proc.closed


def test_sweep_closes_every_copy_but_reports_the_name_once():
    chrome = [FakeProc(pid, "chrome.exe") for pid in (10, 11, 12)]

    assert sweep({"chrome.exe"}, chrome) == ["chrome.exe"]
    assert all(proc.closed for proc in chrome)


def test_sweep_leaves_other_users_processes_alone():
    mine = FakeProc(1, "spotify.exe", user="me")
    theirs = FakeProc(2, "spotify.exe", user="OTHERPC\\someone")
    system = FakeProc(3, "spotify.exe", user="NT AUTHORITY\\SYSTEM")

    sweep({"spotify.exe"}, [mine, theirs, system])

    assert (mine.closed, theirs.closed, system.closed) == (True, False, False)


def test_sweep_never_closes_protected_processes_even_if_listed():
    explorer = FakeProc(1, "explorer.exe")
    terminal = FakeProc(2, "WindowsTerminal.exe")

    closed = sweep({"explorer.exe", "windowsterminal.exe"}, [explorer, terminal])

    assert closed == []
    assert not explorer.closed and not terminal.closed


def test_sweep_never_closes_this_program_or_what_started_it():
    me = FakeProc(os.getpid(), "spotify.exe")  # pretend we ARE a blocked app
    parent = FakeProc(4242, "spotify.exe")
    stranger = FakeProc(7, "spotify.exe")

    # keep=None means "work it out for real": our own pid, plus our parents
    appblocker.sweep({"spotify.exe"}, processes=[me, stranger], me="me")
    assert not me.closed
    assert stranger.closed

    sweep({"spotify.exe"}, [parent], keep={4242})
    assert not parent.closed


def test_sweep_survives_a_process_that_will_not_close():
    stubborn = FakeProc(1, "a.exe", error=psutil.AccessDenied(1))
    fine = FakeProc(2, "b.exe")

    closed = sweep({"a.exe", "b.exe"}, [stubborn, fine])

    assert closed == ["b.exe"]  # a.exe isn't claimed as closed, and b.exe still got done
    assert fine.closed


def test_sweep_survives_a_process_that_vanished_mid_scan():
    gone = FakeProc(1, "a.exe", user_error=psutil.NoSuchProcess(1))
    fine = FakeProc(2, "a.exe")

    assert sweep({"a.exe"}, [gone, fine]) == ["a.exe"]
    assert fine.closed


def test_sweep_skips_processes_with_no_readable_name():
    nameless = FakeProc(1, None)
    assert sweep({"a.exe"}, [nameless]) == []


def test_sweep_with_nothing_blocked_does_not_even_look():
    def explode():
        raise AssertionError("it scanned the processes for no reason")
        yield  # makes this a generator

    assert appblocker.sweep(set(), processes=explode(), me="me", keep=set()) == []


def test_sweep_returns_sorted_names():
    procs = [FakeProc(1, "zoom.exe"), FakeProc(2, "discord.exe")]
    assert sweep({"zoom.exe", "discord.exe"}, procs) == ["discord.exe", "zoom.exe"]


# ---------- running_apps, with fake processes ----------

def test_running_apps_lists_your_own_unprotected_programs_once_each():
    procs = [
        FakeProc(1, "Spotify.exe"),
        FakeProc(2, "spotify.exe"),  # a second copy
        FakeProc(3, "explorer.exe"),  # protected
        FakeProc(4, "svchost.exe", user="NT AUTHORITY\\SYSTEM"),
        FakeProc(5, "Discord.exe"),
        FakeProc(6, "System"),  # no .exe
        FakeProc(7, None),
        FakeProc(8, "Locked.exe", user_error=psutil.AccessDenied(8)),
    ]

    assert appblocker.running_apps(processes=procs, me="me") == ["discord.exe", "spotify.exe"]


# ---------- the one test that uses a real process ----------

@pytest.mark.skipif(sys.platform != "win32", reason="uses a Windows program")
def test_sweep_really_closes_a_real_process(tmp_path):
    """A copy of ping.exe with a name nobody else uses, pinging your own machine.

    This is the only test that closes a real process, and it can only match this one.
    """
    name = "xamguard_test_sleeper.exe"
    sleeper = tmp_path / name
    shutil.copy(os.path.join(os.environ["SystemRoot"], "System32", "PING.EXE"), sleeper)

    process = subprocess.Popen(
        [str(sleeper), "-n", "120", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.time() + 5
        while name not in appblocker.running_apps() and time.time() < deadline:
            time.sleep(0.1)
        assert name in appblocker.running_apps()  # psutil can see it

        assert appblocker.sweep({name}) == [name]

        process.wait(timeout=5)  # raises if it's still alive
        assert process.returncode is not None
        assert name not in appblocker.running_apps()
    finally:
        if process.poll() is None:
            process.kill()
