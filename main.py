from threading import Timer

blocked_sites = []
blocked_apps = []


def sitelogic():
    sites = input("Enter websites to block (comma separated, e.g. youtube.com,facebook.com): ")
    site_list = [site.strip() for site in sites.split(",") if site.strip()]
    blocked_sites.extend(site_list)
    print(f"Blocked sites: {blocked_sites}")

def applogic():
    apps = input("Enter app names to block (comma separated, e.g. chrome,spotify): ")
    app_list = [app.strip() for app in apps.split(",") if app.strip()]
    blocked_apps.extend(app_list)
    print(f"Blocked apps: {blocked_apps}")

def unblocklogic():
    choice = input("Unblock 'site' or 'app'? ").strip().lower()
    
    if choice == "site":
        if not blocked_sites:
            print("No sites are currently blocked.")
            return
        
        print(f"Currently blocked sites: {blocked_sites}")
        site = input("Enter site to unblock: ").strip()
        
        if site in blocked_sites:
            blocked_sites.remove(site)
            print(f"Unblocked {site}. Remaining blocked sites: {blocked_sites}")
        
        else:
            print(f"{site} is not in the blocked list.")
    
    elif choice == "app":
        if not blocked_apps:
            print("No apps are currently blocked.")
            return
        
        print(f"Currently blocked apps: {blocked_apps}")
        app = input("Enter app to unblock: ").strip()
        
        if app in blocked_apps:
            blocked_apps.remove(app)
            print(f"Unblocked {app}. Remaining blocked apps: {blocked_apps}")
        
        else:
            print(f"{app} is not in the blocked list.")
    
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

def validateinput(prompt):
    confirm = input(f"{prompt} (y/n): ").strip().lower()
    return confirm == "y"

def main():
    print("Welcome to XamGuard, rapture yourself from procrastination!")
    while True:
        optionchoice = input("Choose: site | app | unblock | quit: ")
        optionchoice = fixinput(optionchoice)
        if optionchoice == "site":
            sitelogic()
        elif optionchoice == "app":
            applogic()
        elif optionchoice == "unblock":
            unblocklogic()
        elif optionchoice == "quit":
            quitlogic()
        else:
            print("Invalid option. Please choose again.")

if __name__ == "__main__":
    main()