#============================================================================
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#============================================================================
# Copyright (C) 2006 XenSource Ltd.
#============================================================================

import time
import pam
from bnlibvirt import uuid
from BNError import *
from bnlibvirt.BNLogging import log

class BNAuthSessions:
    """Keeps track of Xen API Login Sessions using PAM.

    Note: Login sessions are not valid across instances of Xend.
    """
    def __init__(self):
        self.sessions = {}

    def init(self):
        pass

    def login_unconditionally(self, username):
        """Returns a session UUID if valid.

        @rtype: string
        @return: Session UUID
        """
#        file_object = open('/home/lt/ver', 'w')
#        file_object.write('in uncondition')
#        file_object.close()
        new_session = uuid.gen_regularUuid()
        self.sessions[new_session] = (username, time.time())
        return new_session

    def login_with_password(self, username, password):
        """Returns a session UUID if valid, otherwise raises an error.

        @raises XendError: If login fails.
        @rtype: string
        @return: Session UUID
        """
        if self.is_authorized(username, password):
            return self.login_unconditionally(username)

        raise BNError("Login failed")

    def logout(self, session):
        """Delete session of it exists."""
        if self.is_session_valid(session):
            del self.sessions[session]

    def is_session_valid(self, session):
        """Returns true is session is valid."""
        if type(session) == type(str()):
            return (session in self.sessions)
        return False

    def is_authorized(self, username, password):
        """Returns true is a user is authorised via PAM.

        Note: We use the 'login' PAM stack rather than inventing
              our own.

        @rtype: boolean
        """
        return pam.authenticate(username, password, 'sshd')
        
    def get_user(self, session):
        try:
            return self.sessions[session][0]
        except (KeyError, IndexError):
            return None


def instance():
    """Singleton constructor. Use this instead of the class constructor.
    """
    global inst
    try:
        inst
    except:
        inst = BNAuthSessions()
        inst.init()
    return inst
