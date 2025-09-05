import time
from datetime import datetime as DT
import platform
TAGS = "# XAMGUARD"


os_name = platform.system()
print(f"The OS detected is: {os_name}")

host_temp = "hosts.txt"
ip = "127.0.0.1"

if (os_name == "Windows"):
    host_path = r"C:\Windows\System32\drivers\etc\hosts"
    print("Hello Windows user!")
    
elif (os_name == "Darwin"):
    host_path = r"/etc/hosts"
    print("Hello Mac user!")

elif (os_name == "Linux"):
    host_path = r"/etc/hosts"
    print("Hello Linux user!")

def block(websites):
    with open(host_path, "r+") as f:
        filetext = f.read()
    
        linestoadd = []
        
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
                f.write(lines)
        
        f.truncate()
        
    print("Unblocked the following sites:", linestoremove)