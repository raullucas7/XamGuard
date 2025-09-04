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
    print("Welcome to Windows!")
    
elif (os_name == "Darwin"):
    host_path = r"/etc/hosts"
    print("Hello mac users")

# add linux option here


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
    
    with open(host_path, "w") as g:
        g.write(linestoadd)
    
    print("blocked this site")


def unblock(websites):
    # yes
    
    
    
    print("blocked this site")
    
    return