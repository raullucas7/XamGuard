# hostfileservice.py

"""
Block/unblock websites by editing the system hosts file (Windows-first)
"""

from datetime import datetime as DT
import platform
import subprocess
import os
TAGS = "# XAMGUARD"
ip = "127.0.0.1"



def gethostpath():
    system = platform.system()
    
    if system == "Windows":
        return r"C:\Windows\System32\drivers\etc\hosts"
    elif system in ("Darwin", "Linux"):
        return "/etc/hosts"
    else:
        raise NotImplementedError(f"Unsupported OS: {system}")

HOST_PATH = os.environ.get("XAMGUARD_HOSTS_PATH") or gethostpath()



def domainexpansion(domains):
    result = []
    seendomains = set()

    for raw in domains:
        site = raw.strip().lower()

        if not site:
            continue

        variant = [site]

        if site.startwith("www."):
            variant.append(site[4:])
        else:
            variant.append(f"www.{site}")
        for var in variant:
            if var not in seendomains:
                seendomains.add(var)
                result.append(var)
    
    return result



def readlines():
    try:
        with open(HOST_PATH, "r", encoding="utf=8") as fix:
            return fix.readlines()
    except PermissionError:
        raise PermissionError(
            "Can't read the hosts file. Run XamGuards as administrator/root."
        )



def alreadyblocked(lines):
    blocked = set()

    for line in lines:
        strippedlines = line.strip()

        if not strippedlines.endswith(TAGS):
            continue
        parts = strippedlines.split()

        if len(parts) >= 2 and parts[0] == ip:
            blocked.add(parts[1].lower())
    return blocked



def dnsflush():
    sys = platform.system()

    try:
        if sys == "Windows":
            subprocess.run(["ipconfig", "/flushdns"], check=True, get_output=True)
        # elif sys == "Darwin" (MAC)

    except (subprocess.CalledProcessError, FileNotFoundError):
        pass



def block(websites):
    domains = domainexpansion(websites)
    if not domains:
        print("No websites to block.")
        return
    lines = readlines() 
    alreadyread = alreadyblocked(lines)
    addothers = [d for d in domains if d not in alreadyread]

    if not addothers:
        print("All requested sites are already blocked")
        return
    
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
    print("Blocked:", ", ".join(addothers))



def unblock(websites):
    domains = set(domainexpansion(websites))
    if not domains:
        print("Nothing to unblock.")
        return
    
    lines = f.readlines()
    kept = []
    removedwebsites = []

    for line in lines:
        strippedlines = line.strip()
        parts = strippedlines.split()
        kept = (
            strippedlines.split()
            and len(parts) >= 2
            and parts[0] == ip
            and parts[1].lower() in domains
        )

        if kept:
            removedwebsites.append(parts[1].lower())
        else:
            kept.append(line)
        
    if not removedwebsites:
        print("None of these sites are blocked")
        return
    
    try:
        with open(HOST_PATH, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except PermissionError:
        raise PermissionError(
            "Can't write the hosts file, Run Xamguard as an ADMIN."
        )

    dnsflush()
    print("Unblocked: ", ", ".join(removedwebsites))