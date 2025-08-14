from threading import Timer

class Timer:
    def __init__(self, durationinseconds, unblocktimer):
        self.duration = durationinseconds
        self.unblocktimer = durationinseconds
        self.timer = None
    
    def start(self):
        print("Timer running for {self.durationinseconds} seconds")
        self.timer = Timer(self.durationinseconds, self.unblocktimer)
        self.timer.start()
        my_timer = 5
        
    
    def abort(self):
        if self.timer:
            self.timer.cancel()
            print("Timer cancelled")
