import timer
import threading

class Timer:
    def __init__(self, durationinseconds):
        self.durationinseconds = durationinseconds
        self.timeremaining = durationinseconds
        self.starttimer = None
        self.timerrunning = None
        self.timerthread = None
        self.unblocktimer = None
    
    def unblock(self):
        
    
    def start(self):
        print("timer is starting")
        t = threading.Timer(30.0, self.unblock).start()

"""
if __name__ == "__main__":
""" 