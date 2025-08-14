import os
import time
from datetime import datetime as DT
import platform

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


