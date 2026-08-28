# timer.py
from threading import Timer as threadingTimer

class Timer:
    def __init__(self, durationinseconds, timerend):
        self.duration = durationinseconds
        self.timerend = timerend
        self.running = None
        self.timer = None
    
    def start(self):
        if self.running:
            print("Timer is running.")
            return
        
        print(f"Timer running for {self.durationinseconds} seconds")
        self.timer = threadingTimer(self.durationinseconds, self.handletimer)
        self.timer.start()
        self.timer = True
    
    def handletimer(self):
        self.running = False
        print("The timer is done.")
        if self.timerend:
            self.timerend()

    def ongoing(self):
        if self.running:
            print(f"The timer is ongoing for {self.durationinseconds}.")
        else:
            print("Timer is not running. Create a new instance.")
    
    def abort(self):
        if self.timer and self.running:
            self.timer.cancel()
            self.running = False
            print("Timer cancelled")
        else:
            print("No active timer to abort.")
