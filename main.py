from threading import Timer

INPUT_HANDLING = {
    "site" : sitelogic,
    "app" : applogic,
    "unblock" : unblocklogic,
    "quit" : quitlogic
}


def sitelogic():
    return

def applogic():
    return

def blocklogic():
    return

def unblocklogic():
    return

def quitlogic():
    return


# HELPERS
def inputcleaner():
    return

def confirminput():
    return



def main():
    print("Welcome to XamGuard, your personal focus app.")
    
    
    
    while True:
        optionchoice = input("Choose: site | app | unblock | quit")
        
        if (optionchoice == ("site").lower().strip()):
            sitechoices = input("Enter websites (comma separated like 'youtube.com'): ")
            
            
            
            
        
        elif (optionchoice == ("app").lower().strip()):
            appchoices = input("Enter the apps you wish to block")
            
        elif (optionchoice == ("unblock").lower().strip()):
            unblockchoice = input("")
        else:
            print("Quitting")
            exit()



"""
def siteunblock():
    print("Unblocking sites immediately")
    
    timer = Timer(10, siteunblock)
    timer.start()

"""