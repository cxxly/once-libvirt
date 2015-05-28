from xmlrpclib import Fault

import types
import BNClient

class BNInvalidDomain(Fault):
    def __init__(self, value):
        Fault.__init__(self, BNClient.ERROR_INVALID_DOMAIN, value)

class BNError(Fault):
    
    def __init__(self, value):
        Fault.__init__(self, BNClient.ERROR_GENERIC, value)
        self.value = value

    def __str__(self):
        return self.value

class BNAPIError(BNError):
    """Extend this class for all error thrown by
    autoplugged classes"""
    def __init__(self):
        BNError.__init__(self, 'XendAPI Error: You should never see this'
                           ' message; this class need to be overidden')

    def get_api_error(self):
        return ['INTERNAL_ERROR', 'You should never see this message; '
                'this method needs to be overidden']

XEND_ERROR_TODO                  = ('ETODO', 'Lazy Programmer Error')