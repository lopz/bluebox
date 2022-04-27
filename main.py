#!/usr/bin/env python

import ConfigParser

from spampoint.tracker import SpamPoint



class Kernel:
    
    def __init__(self):
        self.config = ConfigParser.ConfigParser()
        self.config.read('campaigns.ini')
        
        self.spampoint = SpamPoint(self)
        #self.webconfig = WebConfig()
        
    def turn_on(self):
        self.spampoint.start()
        #self.webconfig.start()

        
        
kernel = Kernel()



if __name__ == '__main__':
    kernel.turn_on()
    
    
        
    
        
    
