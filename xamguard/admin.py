"""Admin rights. Windows only lets admins edit the hosts file."""

import ctypes
import os
import subprocess
import sys


def is_admin():
    """True if we're allowed to edit the hosts file."""
    try:
        if os.name == "nt":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except (AttributeError, OSError):
        return False


def relaunch_as_admin():
    """Restart the app as admin (this shows the UAC prompt).

    True means Windows said yes, so close this copy. False means no.
    """
    if os.name != "nt":
        return False

    if getattr(sys, "frozen", False):
        # packaged .exe, sys.executable is the app itself
        program, arguments = sys.executable, sys.argv[1:]
    else:
        # running as a script. pythonw.exe so no console window pops up
        program = sys.executable
        windowless = os.path.join(os.path.dirname(program), "pythonw.exe")
        if os.path.exists(windowless):
            program = windowless
        arguments = [os.path.abspath(sys.argv[0]), *sys.argv[1:]]

    # "runas" is what triggers the UAC prompt. above 32 means it worked
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", program, subprocess.list2cmdline(arguments), os.getcwd(), 1
    )
    return result > 32
