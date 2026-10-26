# hostfileservice.py

"""
Block/unblock websites by editing the system hosts file (Windows-first)
"""

from datetime import datetime as DT
import platform
import re
import subprocess
import os
TAGS = "# XAMGUARD"
ip = "127.0.0.1"

# dot-separated labels, max 63 chars each
# the last one (com, org...) must start with a letter, so IPs get rejected
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
TLD = r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
DOMAIN_RE = re.compile(rf"(?:{LABEL}\.)+{TLD}")



def gethostpath():
    system = platform.system()
    
    if system == "Windows":
        return r"C:\Windows\System32\drivers\etc\hosts"
    elif system in ("Darwin", "Linux"):
        return "/etc/hosts"
    else:
        raise NotImplementedError(f"Unsupported OS: {system}")

HOST_PATH = os.environ.get("XAMGUARD_HOSTS_PATH") or gethostpath()


def normalizedomain(raw):
    """turn what the user typed into a bare hostname, or raise ValueError."""
    site = raw.strip().lower()
    site = re.sub(r"^[a-z][a-z0-9+.-]*://", "", site)   # https://
    site = re.split(r"[/?#]", site, maxsplit=1)[0]       # /path  ?query  #fragment
    site = site.rsplit("@", 1)[-1]                       # user:password@
    site = re.sub(r":\d+$", "", site)                    # :8080
    site = site.rstrip(".")                              # trailing dot

    if (len(site) > 253) or not DOMAIN_RE.fullmatch(site):
        raise ValueError(
            f"'{raw.strip()}' is not a valid website (try something like youtube.com)"
        )
    return site


def withwww(site):
    """The site plus its www/non-www twin."""
    twin = site[4:] if site.startswith("www.") else f"www.{site}"
    return [site, twin]


# get the site and strip it down to something readable
def domainexpansion(domains):
    result = []
    seendomains = set()

    for raw in domains:
        if not raw.strip():
            continue

        for var in withwww(normalizedomain(raw)):
            if var not in seendomains:
                seendomains.add(var)
                result.append(var)

    return result



def readlines():
    try:
        with open(HOST_PATH, "r", encoding="utf-8") as fix:
            return fix.readlines()
    except FileNotFoundError:
        return []
    except PermissionError:
        raise PermissionError(
            "Can't read the hosts file. Run XamGuard as administrator/root."
        )



def parsetagged(line):
    """domain from a line XamGuard wrote, or None for any other line."""
    strippedline = line.strip()

    if not strippedline.endswith(TAGS):
        return None
    parts = strippedline.split()

    if len(parts) >= 2 and parts[0] == ip:
        return parts[1].lower()
    return None



def alreadyblocked(lines):
    return {domain for domain in map(parsetagged, lines) if domain}



def plainsites(entries):
    """['youtube.com', 'www.youtube.com'] -> ['youtube.com']. hides the www twins."""
    
    names = []
    for entry in entries:
        name = entry[4:] if entry.startswith("www.") else entry
        if name not in names:
            names.append(name)
            
    return names



def list_blocked():
    """sites XamGuard blocked, sorted, without the www twins."""
    return sorted(plainsites(alreadyblocked(readlines())))



def dnsflush():
    system = platform.system()

    try:
        if system == "Windows":
            subprocess.run(
                ["ipconfig", "/flushdns"],
                check=True,
                capture_output=True,
                timeout=10,  # a stuck ipconfig shouldn't freeze the window
                creationflags=subprocess.CREATE_NO_WINDOW,  # no console flash
            )
        # elif system == "Darwin" (MAC)

    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass



def block(websites):
    """returns what got added. raises ValueError (before writing) on a bad site."""
    # make the sites parsable
    domains = domainexpansion(websites)

    if not domains:
        return []

    lines = readlines()
    alreadyread = alreadyblocked(lines)
    addothers = [d for d in domains if d not in alreadyread]

    if not addothers:
        return []

    needsnewline = bool(lines) and not lines[-1].endswith("\n")

    try:
        with open(HOST_PATH, "a", encoding="utf-8") as f:
            if needsnewline:
                f.write("\n")
            for d in addothers:
                f.write(f"{ip} {d} {TAGS}\n")

    except PermissionError:
        raise PermissionError(
            "Can't write the hosts file. Run XamGuard as administrator/root."
        )

    dnsflush()
    return addothers



def unblocktargets(websites):
    """everything that counts as 'these sites' when unblocking."""
    targets = set()

    for raw in websites:
        literal = raw.strip().lower()
        if not literal:
            continue

        # the text as typed, so old junk entries can still be removed
        targets.update(withwww(literal))

        # plus the cleaned up version, so pasted URLs work
        try:
            targets.update(domainexpansion([raw]))
        except ValueError:
            pass
    return targets



def unblock(websites):
    """returns what got removed. only touches lines XamGuard wrote."""
    domains = unblocktargets(websites)
    if not domains:
        return []

    lines = readlines()
    kept_lines = []
    removedwebsites = []

    for line in lines:
        domain = parsetagged(line)

        if domain in domains:
            removedwebsites.append(domain)
        else:
            kept_lines.append(line)

    if not removedwebsites:
        return []

    try:
        with open(HOST_PATH, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)
    except PermissionError:
        raise PermissionError(
            "Can't write the hosts file. Run XamGuard as administrator/root."
        )

    dnsflush()
    return removedwebsites