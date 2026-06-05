# main.py
from hostfileservice import block, unblock
import sys


"""
    to run -> python app.py
    install npm (npm install) and run (npm run dev)
"""


blocked_sites = []
blocked_apps = []


def displayinfo():
    request = input("Do you want to see your blocked 'site's or 'app's? ").strip().lower()

    if request in ("no", "n"):
        return

    if request == "site":
        if blocked_sites:
            print(f"Blocked sites: {blocked_sites}")
        else:
            print("No sites are currently blocked.")
    
    elif request == "app":
        if blocked_apps:
            print(f"Blocked apps: {blocked_apps}")
        else:
            print("No apps are currently blocked.")
    else:
        print("Invalid choice.")


def sitelogic():
    sites = input("Enter websites to block (comma separated, e.g. youtube.com, facebook.com): ")
    site_list = [site.strip() for site in sites.split(",") if site.strip()]
    if not site_list:
        print("No sites entered.")
        return
    
    try:
        block(site_list)
    except PermissionError as e:
        print(e)
        return
    
    for site in site_list:
        if site not in blocked_sites:
            blocked_sites.append(site)

    print(f"Blocked sites: {blocked_sites}")


def validateinput(prompt):
    confirm = input(f"{prompt} (y/n): ").strip().lower()
    return confirm == "y"


def applogic():
    apps = input("Enter app names to block (comma separated, e.g. chrome, spotify): ")
    app_list = [app.strip() for app in apps.split(",") if app.strip()]

    if not app_list:
        print("No apps entered.")
        return
    
    for app in app_list:
        if app not in blocked_apps:
            blocked_apps.append(app)
    print(f"Blocked apps (not yet fully blocked): {blocked_apps}")


def unblocklogic():
    choice = input("Unblock 'site' or 'app'? ").strip().lower()
    
    if choice == "site":
        if not blocked_sites:
            print("No sites are currently blocked.")
            return
        
        print(f"Currently blocked sites: {blocked_sites}")
        site = input("Enter site to unblock: ").strip()
        
        if site not in blocked_sites:
            print(f"{site} is not in the blocked list.")
            return
        
        if not validateinput(f"Unblock {site}?"):
            print("Cancelled.")
            return
        
        try:
            unblock([site])
        except PermissionError as e:
            print(e)
            return
        
        blocked_sites.remove(site)
        print(f"Unblocked {site}. Remaining blocked sites: {blocked_sites}")


    elif choice == "app":
        if not blocked_apps:
            print("No apps are currently blocked.")
            return
 
        print(f"Currently blocked apps: {blocked_apps}")
        app = input("Enter app to unblock: ").strip().lower()
 
        if app not in blocked_apps:
            print(f"{app} is not in the blocked list.")
            return
 
        if not validateinput(f"Unblock {app}?"):
            print("Cancelled.")
            return
 
        blocked_apps.remove(app)
        print(f"Unblocked {app}. Remaining blocked apps: {blocked_apps}")

    
    else:
        print("Invalid choice. Please enter 'site' or 'app'.")


def quitlogic():
    print("Exiting XamGuard. Stay focused!")
    exit()



INPUT_HANDLING = {
    "site" : sitelogic,
    "app" : applogic,
    "unblock" : unblocklogic,
    "quit" : quitlogic
}



# HELPERS
def fixinput(text):
    return text.strip().lower()



def main():
    print("Welcome to XamGuard, free yourself from procrastination!")

    while True:
        optionchoice = input("Choose: site | app | unblock | view blacklist | quit: ")
        handling = INPUT_HANDLING.get(optionchoice)

        if handling:
            handling()
        else:
            print("Invalid option. Please choose again.")

if __name__ == "__main__":
    main()