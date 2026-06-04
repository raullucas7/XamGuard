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

hostpath = os.environ.get("XAMGUARD_HOSTS_PATH") or gethostpath()

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


def block(websites):
    with open(hostpath, "r+") as f:
        linestoadd = []
        filetext = f.read()
        
        if filetext and not filetext.endswith("\n"):
            linestoadd.insert(0, "\n")
        
        for i in websites:
            site = i.strip()
            
            if not site:
                continue
            
            # exact ip and site 
            if f"{ip} {site}" in filetext or f"{ip}\t{site}" in filetext:
                print(f"{site} already blocked")
            else:
                linestoadd.append(f"{ip} {site} {TAGS}\n")

        if not linestoadd:
            print("Nothing to add")
            return
        
        # stop writing over the sites; 0 = start, 2 = end
        f.seek(0, 2)
        
        for line in linestoadd:
            f.write(line)
    print("Blocked the following sites:", websites)


def unblock(websites):
    with open(host_path, "r+") as f:
        # remove the line where site is at, not entire file
        lines = f.readlines()
    
        linestoremove = []
        
        # move read pointer from end to the start of line
        f.seek(0)
        
        for line in lines:
            for site in websites:
                site = site.strip()
                blockentry = f"{ip} {site} {TAGS}"
                
                # checker to prevent wrong lines from dying
                mustremove = False
                
                if blockentry in line:
                    mustremove = True
                    linestoremove.append(site)
                    break
            
            # write the line back / prevent deleting
            if not mustremove:
                f.write(line)
        
        f.truncate()
        
    print("Unblocked the following sites:", linestoremove)