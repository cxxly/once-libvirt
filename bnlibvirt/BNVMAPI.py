import traceback
import inspect
import os
import Queue
import string
import sys
import threading
import time
import xmlrpclib
import socket
import struct
import copy
import re
import libvirt
try: 
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET
import uuid
import os
import XmlConfig

from BNError import *

from bnlibvirt.ConfigUtil import getConfigVar
from bnlibvirt.util.xpopen import xPopen3
from bnlibvirt.util.xmlrpclib2 import stringify
from bnlibvirt.util.xmlrpcclient import ServerProxy
from bnlibvirt import uuid as genuuid
from BNAuthSessions import instance as auth_manager
from BNLogging import log

if getConfigVar('compute', 'VM', 'disk_limit'):
    DISK_LIMIT = int(getConfigVar('compute', 'VM', 'disk_limit'))
else:
    DISK_LIMIT = 6
    
if getConfigVar('compute', 'VM', 'interface_limit'):
    INTERFACE_LIMIT = int(getConfigVar('compute', 'VM', 'interface_limit'))
else:
    INTERFACE_LIMIT = 6

try:
    set
except NameError:
    from sets import Set as set

reload(sys)
sys.setdefaultencoding( "utf-8" )

AUTH_NONE = 'none'
AUTH_PAM = 'pam'
DOM0_UUID = "00000000-0000-0000-0000-000000000000"
argcounts = {}

def doexec(args, inputtext=None):
    """Execute a subprocess, then return its return code, stdout and stderr"""
    proc = xPopen3(args, True)
    if inputtext != None:
        proc.tochild.write(inputtext)
    stdout = proc.fromchild
    stderr = proc.childerr
    rc = proc.wait()
    return (rc, stdout, stderr)

opts = None

class Opts:

    def __init__(self, defaults):
        for (k, v) in defaults.items():
            setattr(self, k, v)
        pass
    
def cmd(p, s):
    global opts
    c = p + ' ' + s
    if opts.verbose: print c
    if not opts.dryrun:
        os.system(c)
        
defaults = {
    'verbose'  : 1,
    'dryrun'   : 0,
    }

opts = Opts(defaults)

def set_opts(val):
    global opts
    opts = val
    return opts

# ------------------------------------------
# Utility Methods for Xen API Implementation
# ------------------------------------------

def xen_api_success(value):
    """Wraps a return value in XenAPI format."""
    if value is None:
        s = ''
    else:
        s = stringify(value)
    return {"Status": "Success", "Value": s}

def xen_api_success_void():
    """Return success, but caller expects no return value."""
    return xen_api_success("")

def xen_api_error(error):
    """Wraps an error value in XenAPI format."""
    if type(error) == tuple:
        error = list(error)
    if type(error) != list:
        error = [error]
    if len(error) == 0:
        error = ['INTERNAL_ERROR', 'Empty list given to xen_api_error']

    return { "Status": "Failure",
             "ErrorDescription": [str(x) for x in error] }


def xen_rpc_call(ip, method, *args):
    """wrap rpc call to a remote host"""
    try:
        if not ip:
            return xen_api_error("Invalid ip for rpc call")
        # create
        proxy = ServerProxy("http://" + ip + ":9363/")
        
        # login 
        response = proxy.session.login('root')
        if cmp(response['Status'], 'Failure') == 0:
            log.exception(response['ErrorDescription'])
            return xen_api_error(response['ErrorDescription'])  
        session_ref = response['Value']
        
        # excute
        method_parts = method.split('_')
        method_class = method_parts[0]
        method_name  = '_'.join(method_parts[1:])
        
        if method.find("host_metrics") == 0:
            method_class = "host_metrics"
            method_name = '_'.join(method_parts[2:])
        #log.debug(method_class)
        #log.debug(method_name)
        if method_class.find("Async") == 0:
            method_class = method_class.split(".")[1]
            response = proxy.__getattr__("Async").__getattr__(method_class).__getattr__(method_name)(session_ref, *args)
        else:
            response = proxy.__getattr__(method_class).__getattr__(method_name)(session_ref, *args)
        if cmp(response['Status'], 'Failure') == 0:
            log.exception(response['ErrorDescription'])
            return xen_api_error(response['ErrorDescription'])
        # result
        return response
    except socket.error:
        return xen_api_error('socket error')


def xen_api_todo():
    """Temporary method to make sure we track down all the TODOs"""
    return {"Status": "Error", "ErrorDescription": XEND_ERROR_TODO}


def now():
    return datetime()


def datetime(when = None):
    """Marshall the given time as a Xen-API DateTime.

    @param when The time in question, given as seconds since the epoch, UTC.
                May be None, in which case the current time is used.
    """
    if when is None:
        return xmlrpclib.DateTime(time.gmtime())
    else:
        return xmlrpclib.DateTime(time.gmtime(when))
    
# ---------------------------------------------------
# Event dispatch
# ---------------------------------------------------

EVENT_QUEUE_LENGTH = 50
event_registrations = {}

def event_register(session, reg_classes):
    if session not in event_registrations:
        event_registrations[session] = {
            'classes' : set(),
            'queue'   : Queue.Queue(EVENT_QUEUE_LENGTH),
            'next-id' : 1
            }
    if not reg_classes:
        reg_classes = classes
    sessionclasses = event_registrations[session]['classes']
    if hasattr(sessionclasses, 'union_update'):
        sessionclasses.union_update(reg_classes)
    else:
        sessionclasses.update(reg_classes)



def event_unregister(session, unreg_classes):
    if session not in event_registrations:
        return

    if unreg_classes:
        event_registrations[session]['classes'].intersection_update(
            unreg_classes)
        if len(event_registrations[session]['classes']) == 0:
            del event_registrations[session]
    else:
        del event_registrations[session]


def event_next(session):
    if session not in event_registrations:
        return xen_api_error(['SESSION_NOT_REGISTERED', session])
    queue = event_registrations[session]['queue']
    events = [queue.get()]
    try:
        while True:
            events.append(queue.get(False))
    except Queue.Empty:
        pass

    return xen_api_success(events)


def _ctor_event_dispatch(xenapi, ctor, api_cls, session, args):
    result = ctor(xenapi, session, *args)
    if result['Status'] == 'Success':
        ref = result['Value']
        event_dispatch('add', api_cls, ref, '')
    return result


def _dtor_event_dispatch(xenapi, dtor, api_cls, session, ref, args):
    result = dtor(xenapi, session, ref, *args)
    if result['Status'] == 'Success':
        event_dispatch('del', api_cls, ref, '')
    return result


def _setter_event_dispatch(xenapi, setter, api_cls, attr_name, session, ref,
                           args):
    result = setter(xenapi, session, ref, *args)
    if result['Status'] == 'Success':
        event_dispatch('mod', api_cls, ref, attr_name)
    return result


def event_dispatch(operation, api_cls, ref, attr_name):
    assert operation in ['add', 'del', 'mod']
    event = {
        'timestamp' : now(),
        'class'     : api_cls,
        'operation' : operation,
        'ref'       : ref,
        'obj_uuid'  : ref,
        'field'     : attr_name,
        }
    for reg in event_registrations.values():
        if api_cls in reg['classes']:
            event['id'] = reg['next-id']
            reg['next-id'] += 1
            reg['queue'].put(event)


# ---------------------------------------------------
# Python Method Decorators for input value validation
# ---------------------------------------------------

def trace(func, api_name=''):
    """Decorator to trace XMLRPC Xen API methods.

    @param func: function with any parameters
    @param api_name: name of the api call for debugging.
    """
    if hasattr(func, 'api'):
        api_name = func.api
    def trace_func(self, *args, **kwargs):
        log.debug('%s: %s' % (api_name, args))
        return func(self, *args, **kwargs)
    trace_func.api = api_name
    return trace_func


def catch_typeerror(func):
    """Decorator to catch any TypeErrors and translate them into Xen-API
    errors.

    @param func: function with params: (self, ...)
    @rtype: callable object
    """
    def f(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except TypeError, exn:
            #log.exception('catch_typeerror')
            if hasattr(func, 'api') and func.api in argcounts:
                # Assume that if the argument count was wrong and if the
                # exception was thrown inside this file, then it is due to an
                # invalid call from the client, otherwise it's an internal
                # error (which will be handled further up).
                expected = argcounts[func.api]
                actual = len(args) + len(kwargs)
                if expected != actual:
                    tb = sys.exc_info()[2]
                    try:
                        sourcefile = traceback.extract_tb(tb)[-1][0]
                        if sourcefile == inspect.getsourcefile(BNVMAPI):
                            return xen_api_error(
                                ['MESSAGE_PARAMETER_COUNT_MISMATCH',
                                 func.api, expected, actual])
                    finally:
                        del tb
            raise
        except BNAPIError, exn:
            return xen_api_error(exn.get_api_error())

    return f

def session_required(func):
    """Decorator to verify if session is valid before calling method.

    @param func: function with params: (self, session, ...)
    @rtype: callable object
    """    
    def check_session(self, session, *args, **kwargs):
        if auth_manager().is_session_valid(session) or cmp(session, "SessionForTest") == 0:
            return func(self, session, *args, **kwargs)
        else:
            return xen_api_error(['SESSION_INVALID', session])

    return check_session


def _is_valid_ref(ref, validator):
    return type(ref) == str and validator(ref)

def _check_ref(validator, clas, func, api, session, ref, *args, **kwargs):
    if _is_valid_ref(ref, validator):
        return func(api, session, ref, *args, **kwargs)
    else:
        return xen_api_error(['HANDLE_INVALID', clas, ref])

def _check_vm(validator, clas, func, api, session, ref, *args, **kwargs):
#    for host_ref in BNPoolAPI._host_structs.keys():
#        if BNPoolAPI._host_structs[host_ref]['VMs'].has_key(ref):
#     if BNPoolAPI.check_vm(ref):
    return func(api, session, ref, *args, **kwargs)
#     return xen_api_error(['VM_NOT_FOUND', clas, ref])

def _check_console(validator, clas, func, api, session, ref, *args, **kwargs):
    #if BNPoolAPI._consoles_to_VM.has_key(ref):
    return func(api, session, ref, *args, **kwargs)
    #else:
    return xen_api_error(['HANDLE_INVALID', clas, ref])

# def valid_object(class_name):
#     """Decorator to verify if object is valid before calling
#     method.
# 
#     @param func: function with params: (self, session, pif_ref)
#     @rtype: callable object
#     """
#     return lambda func: \
#            lambda *args, **kwargs: \
#            _check_ref(lambda r: \
#                           XendAPIStore.get(r, class_name) is not None,
#                       class_name, func, *args, **kwargs)
           
# def valid_task(func):
#     """Decorator to verify if task_ref is valid before calling
#     method.
# 
#     @param func: function with params: (self, session, task_ref)
#     @rtype: callable object
#     """
#     return lambda *args, **kwargs: \
#            _check_ref(XendTaskManager.get_task,
#                       'task', func, *args, **kwargs)
    
def valid_vm(func):
    """Decorator to verify if vm_ref is valid before calling method.

    @param func: function with params: (self, session, vm_ref, ...)
    @rtype: callable object
    """    
    return lambda * args, **kwargs: \
           _check_vm(None,
                      'VM', func, *args, **kwargs)

def valid_vbd(func):
    """Decorator to verify if vbd_ref is valid before calling method.

    @param func: function with params: (self, session, vbd_ref, ...)
    @rtype: callable object
    """    
    return lambda *args, **kwargs: \
           _check_ref(lambda r: None,
                      'VBD', func, *args, **kwargs)

def valid_vbd_metrics(func):
    """Decorator to verify if ref is valid before calling method.

    @param func: function with params: (self, session, ref, ...)
    @rtype: callable object
    """    
    return lambda *args, **kwargs: \
           _check_ref(lambda r: None,
                      'VBD_metrics', func, *args, **kwargs)

def valid_vif(func):
    """Decorator to verify if vif_ref is valid before calling method.

    @param func: function with params: (self, session, vif_ref, ...)
    @rtype: callable object
    """
    return lambda *args, **kwargs: \
           _check_ref(lambda r: None,
                      'VIF', func, *args, **kwargs)

def valid_vif_metrics(func):
    """Decorator to verify if ref is valid before calling method.

    @param func: function with params: (self, session, ref, ...)
    @rtype: callable object
    """    
    return lambda *args, **kwargs: \
           _check_ref(lambda r: None,
                      'VIF_metrics', func, *args, **kwargs)
           
def valid_console(func):
    """Decorator to verify if console_ref is valid before calling method.

    @param func: function with params: (self, session, console_ref, ...)
    @rtype: callable object
    """
    return lambda * args, **kwargs: \
           _check_console(lambda r: None,
                      'console', func, *args, **kwargs)

classes = {
    'session'      : None,
    'VM'           : valid_vm,
    'VBD'          : valid_vbd,
#     'VBD_metrics'  : valid_vbd_metrics,
    'VIF'          : valid_vif
#     'VIF_metrics'  : valid_vif_metrics,
#     'console'      : valid_console,
#     'task'         : valid_task,
}

class BNVMAPI(object): 
    
    __decorated__ = False
    __init_lock__ = threading.Lock()
    __vm_clone_lock__ = threading.Lock()
    __vm_change_host_lock__ = threading.Lock()
    __set_passwd_lock__ = threading.Lock()
    __vbd_lock__ = threading.Lock()
    
    def __new__(cls, *args, **kwds):
        """ Override __new__ to decorate the class only once.

        Lock to make sure the classes are not decorated twice.
        """
        cls.__init_lock__.acquire()
        try:
            if not cls.__decorated__:
                cls._decorate()
                cls.__decorated__ = True
                
            return object.__new__(cls, *args, **kwds)
        finally:
            cls.__init_lock__.release()
            
    def _decorate(cls):
        """ Decorate all the object methods to have validators
        and appropriate function attributes.

        This should only be executed once for the duration of the
        server.
        """
        global_validators = [session_required, catch_typeerror]
        # Cheat methods _hosts_name_label
        # -------------
        # Methods that have a trivial implementation for all classes.
        # 1. get_by_uuid == getting by ref, so just return uuid for
        #    all get_by_uuid() methods.
        
        for api_cls in classes.keys():
            # We'll let the autoplug classes implement these functions
            # themselves - its much cleaner to do it in the base class
            
            get_by_uuid = '%s_get_by_uuid' % api_cls
            get_uuid = '%s_get_uuid' % api_cls
            get_all_records = '%s_get_all_records' % api_cls    

            def _get_by_uuid(_1, _2, ref):
                return xen_api_success(ref)

            def _get_uuid(_1, _2, ref):
                return xen_api_success(ref)

            def unpack(v):
                return v.get('Value')

            def _get_all_records(_api_cls):
                return lambda s, session: \
                    xen_api_success(dict([(ref, unpack(getattr(cls, '%s_get_record' % _api_cls)(s, session, ref)))\
                                          for ref in unpack(getattr(cls, '%s_get_all' % _api_cls)(s, session))]))

            setattr(cls, get_by_uuid, _get_by_uuid)
            setattr(cls, get_uuid, _get_uuid)
            setattr(cls, get_all_records, _get_all_records(api_cls))

        # Autoplugging classes
        # --------------------
        # These have all of their methods grabbed out from the implementation
        # class, and wrapped up to be compatible with the Xen-API.

#         def getter(ref, type):
#             return XendAPIStore.get(ref, type)

        def wrap_method(name, new_f):
            try:
                f = getattr(cls, name)
                wrapped_f = (lambda * args: new_f(f, *args))
                wrapped_f.api = f.api
                wrapped_f.async = f.async
                setattr(cls, name, wrapped_f)
            except AttributeError:
                # Logged below (API call: %s not found)
                pass


        def setter_event_wrapper(api_cls, attr_name):
            setter_name = '%s_set_%s' % (api_cls, attr_name)
            wrap_method(
                setter_name,
                lambda setter, s, session, ref, *args:
                _setter_event_dispatch(s, setter, api_cls, attr_name,
                                       session, ref, args))


        def ctor_event_wrapper(api_cls):
            ctor_name = '%s_create' % api_cls
            wrap_method(
                ctor_name,
                lambda ctor, s, session, *args:
                _ctor_event_dispatch(s, ctor, api_cls, session, args))


        def dtor_event_wrapper(api_cls):
            dtor_name = '%s_destroy' % api_cls
            wrap_method(
                dtor_name,
                lambda dtor, s, session, ref, *args:
                _dtor_event_dispatch(s, dtor, api_cls, session, ref, args))


        # Wrapping validators around XMLRPC calls
        # ---------------------------------------
        for api_cls, validator in classes.items():
            def doit(n, takes_instance, async_support=False,
                     return_type=None):
                n_ = n.replace('.', '_')
                try:
                    f = getattr(cls, n_)
                    if n not in argcounts:
                        argcounts[n] = f.func_code.co_argcount - 1
                    
                    validators = takes_instance and validator and \
                                 [validator] or []
                                 
                    validators += global_validators
                    for v in validators:
                        f = v(f)
                        f.api = n
                        f.async = async_support
                        if return_type:
                            f.return_type = return_type
                    
                    setattr(cls, n_, f)
                except AttributeError:
                    log.warn("API call: %s not found" % n)

           
            ro_attrs = getattr(cls, '%s_attr_ro' % api_cls, []) \
                           + cls.Base_attr_ro
            rw_attrs = getattr(cls, '%s_attr_rw' % api_cls, []) \
                           + cls.Base_attr_rw
            methods = getattr(cls, '%s_methods' % api_cls, []) \
                           + cls.Base_methods
            funcs = getattr(cls, '%s_funcs' % api_cls, []) \
                           + cls.Base_funcs

            # wrap validators around readable class attributes
            for attr_name in ro_attrs + rw_attrs:
                doit('%s.get_%s' % (api_cls, attr_name), True,
                     async_support=False)

            # wrap validators around writable class attrributes
            for attr_name in rw_attrs:
                doit('%s.set_%s' % (api_cls, attr_name), True,
                     async_support=False)
                setter_event_wrapper(api_cls, attr_name)

            # wrap validators around methods
            for method_name, return_type in methods:
                doit('%s.%s' % (api_cls, method_name), True,
                     async_support=True)

            # wrap validators around class functions
            for func_name, return_type in funcs:
                
                doit('%s.%s' % (api_cls, func_name), False,
                     async_support=True,
                     return_type=return_type)
            
            ctor_event_wrapper(api_cls)
            dtor_event_wrapper(api_cls)
            



    _decorate = classmethod(_decorate)
    
    def __init__(self, auth):
        self.auth = auth
        
    Base_attr_ro = ['uuid']
    Base_attr_rw = ['name_label', 'name_description']
    Base_methods = [('get_record', 'Struct')]
    Base_funcs = [('get_all', 'Set'), ('get_by_uuid', None), ('get_all_records', 'Set')]
        
    
#     def _get_XendAPI_instance(self):
#         import XendAPI
#         return XendAPI.instance()
#     
#     def _get_BNStorageAPI_instance(self):
#         import BNStorageAPI
#         return BNStorageAPI.instance()
    
    # Xen API: Class Session
    # ----------------------------------------------------------------
    # NOTE: Left unwrapped by __init__

    session_attr_ro = ['this_host', 'this_user', 'last_active']
    session_methods = [('logout', None)]

    def session_get_all(self, session):
        return xen_api_success([session])

    def session_login(self, username):
        try:
            log.debug("in session login")
            session = auth_manager().login_unconditionally(username)
            return xen_api_success(session)
        except BNError, e:
            return xen_api_error(['SESSION_AUTHENTICATION_FAILED'])
    session_login.api = 'session.login'
       
    def session_login_with_password(self, *args):
#         if not BNPoolAPI._isMaster and BNPoolAPI._inPool:
#             return xen_api_error(XEND_ERROR_HOST_IS_SLAVE)
        if len(args) < 2:
            return xen_api_error(
                ['MESSAGE_PARAMETER_COUNT_MISMATCH',
                 'session.login_with_password', 2, len(args)])
        username = args[0]
        password = args[1]
        try:
#            session = ((self.auth == AUTH_NONE and
#                        auth_manager().login_unconditionally(username)) or
#                       auth_manager().login_with_password(username, password))
            session = auth_manager().login_with_password(username, password)
            return xen_api_success(session)
        except BNError, e:
            return xen_api_error(['SESSION_AUTHENTICATION_FAILED'])
    session_login_with_password.api = 'session.login_with_password'

    # object methods
    def session_logout(self, session):
        auth_manager().logout(session)
        return xen_api_success_void()

    def session_get_record(self, session, self_session):
        if self_session != session:
            return xen_api_error(['PERMISSION_DENIED'])
        record = {'uuid'       : session,
#                   'this_host'  : XendNode.instance().uuid,
                  'this_user'  : auth_manager().get_user(session),
                  'last_active': now()}
        return xen_api_success(record)

    def session_get_uuid(self, session, self_session):
        return xen_api_success(self_session)

    def session_get_by_uuid(self, session, self_session):
        return xen_api_success(self_session)

    # attributes (ro)
    def session_get_this_host(self, session, self_session):
        if self_session != session:
            return xen_api_error(['PERMISSION_DENIED'])
#         if not BNPoolAPI._isMaster and BNPoolAPI._inPool:
#             return xen_api_error(XEND_ERROR_HOST_IS_SLAVE)
        return None
#         return xen_api_success(XendNode.instance().uuid)

    def session_get_this_user(self, session, self_session):
        if self_session != session:
            return xen_api_error(['PERMISSION_DENIED'])
        user = auth_manager().get_user(session)
        if user is not None:
            return xen_api_success(user)
        return xen_api_error(['SESSION_INVALID', session])

    def session_get_last_active(self, session, self_session):
        if self_session != session:
            return xen_api_error(['PERMISSION_DENIED'])
        return xen_api_success(now())


#     # Xen API: Class User
#     # ----------------------------------------------------------------
# 
#     # Xen API: Class Tasks
#     # ----------------------------------------------------------------
# 
#     task_attr_ro = ['name_label',
#                     'name_description',
#                     'status',
#                     'progress',
#                     'type',
#                     'result',
#                     'error_info',
#                     'allowed_operations',
#                     'session'
#                     ]
# 
#     task_attr_rw = []
# 
#     task_funcs = [('get_by_name_label', 'Set(task)'),
#                   ('cancel', None)]
# 
#     def task_get_name_label(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.name_label)
# 
#     def task_get_name_description(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.name_description)
# 
#     def task_get_status(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.get_status())
# 
#     def task_get_progress(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.progress)
# 
#     def task_get_type(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.type)
# 
#     def task_get_result(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.result)
# 
#     def task_get_error_info(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.error_info)
# 
#     def task_get_allowed_operations(self, session, task_ref):
#         return xen_api_success({})
# 
#     def task_get_session(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         return xen_api_success(task.session)
# 
#     def task_get_all(self, session):
#         tasks = XendTaskManager.get_all_tasks()
#         return xen_api_success(tasks)
# 
#     def task_get_record(self, session, task_ref):
#         task = XendTaskManager.get_task(task_ref)
#         log.debug(task.get_record())
#         return xen_api_success(task.get_record())
# 
#     def task_cancel(self, session, task_ref):
#         return xen_api_error('OPERATION_NOT_ALLOWED')

#     def task_get_by_name_label(self, session, name):
#         return xen_api_success(XendTaskManager.get_task_by_name(name))
    
    # Xen API: Class VM
    # ----------------------------------------------------------------        

    def _get_libvirt_connection(self):
        libvirt_connection = None
        try:
            libvirt_connection = libvirt.open('xen:///')
        except Exception, exn:
            log.excepiton("Libivrt connect to xen:/// failed!")
            log.excepiton(exn)
        return libvirt_connection

    VM_methods = [('start', None),
                  ('shutdown', None),
                  ('destroy', None),
                  ('migrate', None),
                  ('reboot', None),
                  ('attach_vif', None),
                  ('detach_vif', None),
                  ('attach_vbd', None),
                  ('detach_vbd', None),
                  ('config_save', None)]
    
    VM_funcs = [('create', 'VM')]
    
    VBD_funcs = [('create', 'VBD'),
                 ('destroy', 'VBD')]
    
    VIF_funcs = [('create', 'VIF'),
                 ('destroy', 'VIF')]
    
    def VM_start(self, session, vm_ref, start_pause=0):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                dom.createWithFlags(int(start_pause))
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_start_failed!'])
#     VM_attr_ro = ['power_state',
#                   'resident_on',
#                   'consoles',
#                   'snapshots',
#                   'VIFs',
#                   'VBDs',
#                   'VTPMs',
#                   'DPCIs',
#                   'DSCSIs',
#                   'media',
#                   'fibers',
#                   'DSCSI_HBAs',
#                   'tools_version',
#                   'domid',
#                   'is_control_domain',
#                   'metrics',
#                   'crash_dumps',
#                   'cpu_pool',
#                   'cpu_qos',
#                   'network_qos',
#                   'VCPUs_CPU',
#                   'ip_addr',
#                   'MAC',
#                   'is_local_vm',
#                   'vnc_location',
#                   'available_vbd_device',
#                   'VIF_record',
#                   'VBD_record',
#                   'dev2path_list',
#                   'pid2devnum_list',
#                   'vbd2device_list',
#                   'config',
#                   'record_lite',
#                   'inner_ip',
#                   'system_VDI',
#                   'network_record',
#                   ]
#                   
#     VM_attr_rw = ['name_label',
#                   'name_description',
#                   'user_version',
#                   'is_a_template',
#                   'auto_power_on',
#                   'snapshot_policy',
#                   'memory_dynamic_max',
#                   'memory_dynamic_min',
#                   'memory_static_max',
#                   'memory_static_min',
#                   'VCPUs_max',
#                   'VCPUs_at_startup',
#                   'VCPUs_params',
#                   'actions_after_shutdown',
#                   'actions_after_reboot',
#                   'actions_after_suspend',
#                   'actions_after_crash',
#                   'PV_bootloader',
#                   'PV_kernel',
#                   'PV_ramdisk',
#                   'PV_args',
#                   'PV_bootloader_args',
#                   'HVM_boot_policy',
#                   'HVM_boot_params',
#                   'platform',
#                   'PCI_bus',
#                   'other_config',
#                   'security_label',
#                   'pool_name',
#                   'suspend_VDI',
#                   'suspend_SR',
#                   'VCPUs_affinity',
#                   'tags',
#                   'tag',
#                   'rate',
#                   'all_tag',
#                   'all_rate',
#                   'boot_order',
#                   'IO_rate_limit',
# #                  'ip_map',  
#                   'passwd',  
#                   'config',
#                   'platform_serial',
#                   ]
# 
#     VM_methods = [('clone', 'VM'),
#                   ('clone_local', 'VM'),
#                   ('clone_MAC', 'VM'),
#                   ('clone_local_MAC', 'VM'),
#                   ('start', None),
#                   ('start_on', None),                  
#                   ('snapshot', None),
#                   ('rollback', None),
#                   ('destroy_snapshot', 'Bool'),
#                   ('destroy_all_snapshots', 'Bool'),
#                   ('pause', None),
#                   ('unpause', None),
#                   ('clean_shutdown', None),
#                   ('clean_reboot', None),
#                   ('hard_shutdown', None),
#                   ('hard_reboot', None),
#                   ('suspend', None),
#                   ('resume', None),
#                   ('send_sysrq', None),
#                   ('set_VCPUs_number_live', None),
#                   ('add_to_HVM_boot_params', None),
#                   ('remove_from_HVM_boot_params', None),
#                   ('add_to_VCPUs_params', None),
#                   ('add_to_VCPUs_params_live', None),
#                   ('remove_from_VCPUs_params', None),
#                   ('add_to_platform', None),
#                   ('remove_from_platform', None),
#                   ('add_to_other_config', None),
#                   ('remove_from_other_config', None),
#                   ('save', None),
#                   ('set_memory_dynamic_max_live', None),
#                   ('set_memory_dynamic_min_live', None),
#                   ('send_trigger', None),
#                   ('pool_migrate', None),
#                   ('migrate', None),
#                   ('destroy', None),
#                   ('cpu_pool_migrate', None),
#                   ('destroy_local', None),
#                   ('destroy_fiber', None),
#                   ('destroy_media', None),
#                   ('destroy_VIF', None),
#                   ('disable_media', None),
#                   ('enable_media', None),
#                   ('eject_media', None),
#                   ('copy_sxp_to_nfs', None),
#                   ('media_change', None),
#                   ('add_tags', None),
#                   ('check_fibers_valid', 'Map'),
#                   ('can_start','Bool'),
#                   ('init_pid2devnum_list', None),
#                   ('clear_IO_rate_limit', None),
#                   ('clear_pid2devnum_list', None),
#                   ('start_set_IO_limit', None),
#                   ('start_init_pid2dev', None),
#                   ('create_image', 'Bool'),
#                   ('send_request_via_serial', 'Bool'),
# #                  ('del_ip_map', None),
#                   ]
#     
#     VM_funcs = [('create', 'VM'),
#                 ('', 'VM'),
#                 ('create_from_sxp', 'VM'),
#                 ('create_from_vmstruct', 'VM'),
#                  ('restore', None),
#                  ('get_by_name_label', 'Set(VM)'),
#                  ('get_all_and_consoles', 'Map'),
#                  ('get_lost_vm_by_label', 'Map'),
#                  ('get_lost_vm_by_date', 'Map'),
#                  ('get_record_lite', 'Set'),
#                  ('create_data_VBD', 'Bool'),
#                  ('delete_data_VBD', 'Bool'),
#                  ('create_from_template', None),
#                  ('_from_template', None),
#                  ('clone_system_VDI', 'VDI'),
#                  ('create_with_VDI', None),
#                  ]
# 
#     # parameters required for _create()
#     VM_attr_inst = [
#         'name_label',
#         'name_description',
#         'user_version',
#         'is_a_template',
#         'is_local_vm',
#         'memory_static_max',
#         'memory_dynamic_max',
#         'memory_dynamic_min',
#         'memory_static_min',
#         'VCPUs_max',
#         'VCPUs_at_startup',
#         'VCPUs_params',
#         'actions_after_shutdown',
#         'actions_after_reboot',
#         'actions_after_suspend',
#         'actions_after_crash',
#         'PV_bootloader',
#         'PV_kernel',
#         'PV_ramdisk',
#         'PV_args',
#         'PV_bootloader_args',
#         'HVM_boot_policy',
#         'HVM_boot_params',
#         'platform',
#         'PCI_bus',
#         'other_config',
#         'security_label']
        
    def VM_shutdown(self, session, vm_ref, start_pause=0):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                dom.shutdownFlags(int(start_pause))
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_shutdown_failed!'])
    
    def VM_destroy(self, session, vm_ref, start_pause=0):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                dom.undefineFlags(int(start_pause))
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_destroy_failed!'])
    
    def VM_create(self, session, domid, name, memory, vcpu, image, tap2, vif, vbd, vfb, console):
        conn = self._get_libvirt_connection()      
        if conn:
            configOri = XmlConfig.XmlConfig(domid, name, memory, vcpu, image, tap2, vif, vbd, vfb, console)
            xml_config = configOri.xmlConfig()
#             print os.getcwd()
#             tree = ET.parse(xml_config)
#             xml_config = ET.tostring(tree.getroot(),encoding='utf8')
            dom = conn.defineXML(xml_config)
            if dom:
                dom_path = self._managed_path(dom.UUIDString())
                if not os.path.isdir(dom_path):
                    os.mkdir(dom_path)
                f = open(self._managed_config_path(dom.UUIDString()),'w+')
                try:
                    dom_xml = dom.XMLDesc(0)
                    f.writelines(dom_xml)
                except Exception:
                    dom.undefine()
                    return xen_api_error(['VM_config_save_failed!'])
                else:
                    return xen_api_success_void()
                finally:
                    f.close()
            else:
                log.error("Domain Config Error.")
        return xen_api_error(['VM_create_failed!'])
    
    def VM_reboot(self, session, vm_ref):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                dom.reboot(0)
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_reboot_failed!'])
    
    def VM_migrate(self, session, vm_ref, dconn):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                dom.migrate(dconn)
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_migrate_failed!'])
    
    def VM_get_interface(self, session, vm_ref):
        conn = self._get_libvirt_connection()
        if conn:
            ifaces = []
            iface = {}
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                xml = dom.XMLDesc(0)
                root = ET.fromstring(xml)
                for elem in root.getiterator('interface'):
                    for child in elem:
                        if child.tag == 'mac':
                            iface['mac'] = child.attrib.values()[0]
                        if child.tag == 'source':
                            iface['device'] = child.attrib.values()[0]
                            for netName in conn.listNetworks():
                                net = conn.networkLookupByName(netName)
                                if net.bridgeName() == child.attrib.values()[0]:
                                    iface['ref'] = net.UUIDString()
                                    iface['name'] = net.bridgeName()
                                    netXml = net.XMLDesc(0)
                                    netRoot = ET.fromstring(netXml)
                                    for elem in netRoot.getiterator('ip'):
                                        iface['ip'] = elem.attrib['address']
                    ifaces.append(iface)
        return ifaces        
    
    def VM_get_metrics(self, session, vm_ref):
        conn = self._get_libvirt_connection()
        record = None
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                
                record = {
                'uuid': uuid.createString(),
                'memoryActual': dom.info()[1],
                'VCPUsNumber': dom.vcpusFlags(0),
                'VCPUsUtilisation': dom.vcpus(),
                'VCPUsCPU': dom.vcpus(),
                'VCPUsParams': dom.vcpus(),
                'VCPUsFlags': dom.vcpus(),
                'state':  dom.state(0),
#                 'startTime':,
#                 'installTime':,
#                 'lastUpdated':,
#                 'otherConfig':,
                          }
        return record
             
    def VM_get_record(self, session, vm_ref):
        conn = self._get_libvirt_connection()
        record = None
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                VBDs = []
                connectedIsoSRs= []
                xml = dom.XMLDesc(0)
                root = ET.fromstring(xml)
                for elem in root.getiterator('loader'):
                    PV_kernel = elem.text
                for elem in root.getiterator('disk'):
                    if elem.attrib['device'] == 'disk':
                        for child in elem:
                            if child.tag == 'source':   
                                VBDs.append(child.attrib.values()[0])
                    if elem.attrib['device'] == 'cdrom':
                        for child in elem:
                            if child.tag == 'source': 
                                connectedIsoSRs.append(child.attrib.values()[0])
                mac = []
                ip_addr = []
                VIFs = []
                for i in range(len(self.VM_get_interface(session,vm_ref))):
                    mac.append(self.VM_get_interface(session,vm_ref)[i]['mac'])
                    ip_addr.append(self.VM_get_interface(session,vm_ref)[i]['ip'])
                    VIFs.append(self.VM_get_interface(session,vm_ref)[i]['name'])
#                 xml = dom.XMLDesc(0)
#                 file = open("/home/test/test0422.xml",'w')
#                 file.writelines(xml)
#                 file.close()
                record = {
                'uuid': dom.UUIDString(),
                'power_state': dom.state(0),
                'name_label': dom.name(),
                'name_description': dom.XMLDesc(0),
                'user_version': 1,
                'is_a_template': False if dom.ID() in conn.listDomainsID() else True,
#                 'is_local_vm' : False,
                'ip_addr' : ip_addr,
                'MAC' : mac,  
                'auto_power_on': dom.autostart(),
#                 'resident_on': dom.hostname(0),
                'memory_overhead' : dom.info()[2],
#                 'memory_static_min': None,
                'memory_static_max': dom.maxMemory(),
#                 'memory_dynamic_min': None,
                'memory_dynamic_max': dom.info()[1],
#                 'VCPUs_params': dom.vcpus(),
                'VCPUs_at_startup': dom.info()[3],
#                 'VCPUs_max': dom.maxVcpus(),
                'actions_after_shutdown': 'DESTROY',
#                 'actions_after_reboot': None,
#                 'actions_after_suspend': None,
#                 'actions_after_crash': None,
#                 'consoles': None,
                'VIFs':  VIFs,
                'VBDs': VBDs,
#                 'VTPMs': None,
#                 'DPCIs': None ,
#                 'DSCSIs': None ,
#                 'DSCSI_HBAs': None,
#                 'PV_bootloader': PV_kernel,
                'PV_kernel': PV_kernel,
#                 'PV_ramdisk': None,
#                 'PV_args': None,
#                 'PV_bootloader_args': None,
#                 'HVM_boot_policy': None,
#                 'HVM_boot_params': None,
#                 'platform': dom.OSType(),
#                 'PCI_bus': None,
#                 'tools_version': None,
#                 'other_config': None,
#                 'tags' : None,
                'domid': dom.ID(),
#                 'is_control_domain': ,
                'metrics': self.VM_get_metrics(session, vm_ref)['uuid'],
#                 'cpu_qos': None,
#                 'security_label': dom.securityLabelList(),
#                 'crash_dumps': None,
#                 'suspend_VDI' : None,
#                 'suspend_SR' : None,
                'connected_disk_SRs' :VBDs,
                'connected_iso_SRs' : connectedIsoSRs,
#                 'pool_name': None,
                }
        return xen_api_success(record)
    
    def VM_config_save(self, session, vm_ref):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                if not self.is_domain_managed(session, dom):
                    return xen_api_error(['not a managed dom!'])
                try:
                    dom_xml = dom.XMLDesc(0)
                    dom_path = self._managed_path(vm_ref)
                    if not os.path.isdir(dom_path):
                        os.mkdir(dom_path)
                    f = open(self._managed_config_path(vm_ref),'w+')
                    try:
                        f.writelines(dom_xml)
                    except Exception:
                        return xen_api_error(['VM_config_save_failed!'])
                    else:
                        return xen_api_success_void()
                    finally:
                        f.close()
                except Exception:
                    return xen_api_error(['VM_config_save_failed!'])
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_config_save_failed!'])
                
    def is_domain_managed(self, session, dom=None):
        return (dom.UUIDString() in self.managed_domains(session))
    
    def managed_domains(self, session):
        conn = self._get_libvirt_connection()
        if conn:
            dom_path = self._managed_path()
            dom_uuids = os.listdir(dom_path)
            doms = []
            for dom_uuid in dom_uuids:
                try:
                    cfg_file = self._managed_config_path(dom_uuid)
                    cfg_uuid = ''
                    try:
                        cfg = open(cfg_file,'r')
                        cfg_xml = ET.fromstring(cfg.read())
                        for elem in cfg_xml.getiterator('uuid'):
                            cfg_uuid = elem.text
                    except IOError as e:
                        log.exception(e)
                    if cfg_uuid != dom_uuid:
                        log.error("UUID mismatch in stored configuration: %s" % cfg_file)
                        continue
                    dom = conn.lookupByUUIDString(cfg_uuid)
                    if dom:
                        if dom.isActive():
                            log.error("Domain %s is running." % cfg_uuid)
                            continue    
                    else:
                        log.error("Domain %s not found." % cfg_uuid)
                        continue
                    doms.append(cfg_uuid)
                except Exception:
                    log.exception('Unable to open or parse config.xml: %s' % cfg_file)
        return doms
    
    def _managed_config_path(self, domuuid, usr_path=None):
        return os.path.join(self._managed_path(domuuid, usr_path), 'config.xml')
#         return self._managed_path(domuuid, usr_path)+'.xml'
    
    def _managed_path(self, domuuid=None, usr_path=None):
        if usr_path:
            dom_path = usr_path
        else:
            dom_path = '/home/test/domains'
        if domuuid:
            dom_path = os.path.join(dom_path, domuuid)
        return dom_path        
    
    def VBD_create(self, session, size, file, driver, phy):
        import VBDXmlConfig
        vbdConfig = VBDXmlConfig.VBDXmlConfig(file, driver, phy)
        vbdConfig.vbdXmlConfig()
        cmd("qemu-img", 'create -f raw %s %s' % (file, size))
        return xen_api_success_void()
    
#     def VBD_get_record(self, session, vbd_ref):
    
    def VM_attach_vbd(self, session, vm_ref, vbdXml):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                print os.getcwd()
                tree = ET.parse(vbdXml)
                xml_config = ET.tostring(tree.getroot(),encoding='utf8')
                dom.attachDeviceFlags(xml_config, 0)
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VM_migrate_failed!'])
    
    def VIF_create(self, session, name, mac, ip, vlan, driver, bridge):
        conn = self._get_libvirt_connection()
        import VIFXmlConfig
        if conn:
            configOri = VIFXmlConfig.VIFXmlConfig(name, mac, ip, vlan, driver, bridge)
            xml_config = configOri.netXmlConfig()
            vif = conn.networkDefineXML(xml_config)
            if vif:
                return xen_api_success_void()
        return xen_api_error(['VIF_create_failed!'])
    
    def VIF_destroy(self, session, name):
        conn = self._get_libvirt_connection()
        if conn:
            vif = conn.networkLookupByName(name)
            if vif:
                if not vif.isActive():
                    vif.undefine()
                    return xen_api_success_void()
                else:
                    log.error("vif %s is active" % name)
            else:
                log.error("vif %s not found" % name)
        return xen_api_error(['VIF_create_failed!'])
    
#     def VM_get_VIFs(self, session, vm_ref):
    
    def VIF_get_record(self, session, vif_ref):
        conn = self._get_libvirt_connection()
        record = None
        if conn:
            network = conn.networkLookupByUUID(vif_ref)
            if network:
                record = {
                    'uuid': network.UUID(),
                    'device': network.bridgeName(),
                    'network': network.name(),
#                     'VM': '',
#                     'MAC': '',
#                     'MTU': '',
#                     'otherConfig': '',
                    'currentlyAttached': network.IsActive(),
#                     'statusCode': '',
#                     'statusDetail': '',
#                     'runtimeProperties': '',
#                     'metrics': '',
#                     'MACAutogenerated': ''   
                }
        return xen_api_success(record)
    
    def VM_attach_vif(self, session,vm_ref, net):
        conn = self._get_libvirt_connection()
        if conn:
            network = conn.networkLookupByName(net)
            if not network.isActive():
                network.create()
            vif = network.bridgeName()
            xml = "<interface type='bridge'><source bridge='"+vif+"'/><model type='virtio'/></interface>"
#             interface = conn.interfaceLookupByName(vif)
#             if interface:
#                 xml = interface.XMLDesc()
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                dom.attachDeviceFlags(xml, 2)
                return xen_api_success_void()
            else:
                log.error("Domain %s not found." % vm_ref)
        return xen_api_error(['VIF_attach_failed!'])
     
    def VM_detach_vif(self, session, vm_ref, net, name, mac):
        conn = self._get_libvirt_connection()
        if conn:
            dom = conn.lookupByUUIDString(vm_ref)
            if dom:
                network = conn.networkLookupByName(net)
                xml ="<interface type='bridge'><mac address = '"+mac+"'/><source bridge='"+name+"'/></interface>"
                dom.detachDeviceFlags(xml, 2)
                if network.isActive():
                    network.destroy()
                return xen_api_success_void()    
            else:
                log.error("domain %s not found." % vm_ref)
        return xen_api_error(['VIF_detach_failed!'])  
# class BNVMAPIAsyncProxy:
#     """ A redirector for Async.Class.function calls to XendAPI
#     but wraps the call for use with the XendTaskManager.
# 
#     @ivar xenapi: Xen API instance
#     @ivar method_map: Mapping from XMLRPC method name to callable objects.
#     """
# 
#     method_prefix = 'Async.'
# 
#     def __init__(self, xenapi):
#         """Initialises the Async Proxy by making a map of all
#         implemented Xen API methods for use with XendTaskManager.
# 
#         @param xenapi: XendAPI instance
#         """
#         self.xenapi = xenapi
#         self.method_map = {}
#         for method_name in dir(self.xenapi):
#             method = getattr(self.xenapi, method_name)            
#             if method_name[0] != '_' and hasattr(method, 'async') \
#                    and method.async == True:
#                 self.method_map[method.api] = method
# 
#     def _dispatch(self, method, args):
#         """Overridden method so that SimpleXMLRPCServer will
#         resolve methods through this method rather than through
#         inspection.
# 
#         @param method: marshalled method name from XMLRPC.
#         @param args: marshalled arguments from XMLRPC.
#         """
# 
#         # Only deal with method names that start with "Async."
#         if not method.startswith(self.method_prefix):
#             return xen_api_error(['MESSAGE_METHOD_UNKNOWN', method])
# 
#         # Lookup synchronous version of the method
#         synchronous_method_name = method[len(self.method_prefix):]
#         if synchronous_method_name not in self.method_map:
#             return xen_api_error(['MESSAGE_METHOD_UNKNOWN', method])
#         
#         method = self.method_map[synchronous_method_name]
# 
#         # Check that we've got enough arguments before issuing a task ID.
#         needed = argcounts[method.api]
#         if len(args) != needed:
#             return xen_api_error(['MESSAGE_PARAMETER_COUNT_MISMATCH',
#                                   self.method_prefix + method.api, needed,
#                                   len(args)])
# 
#         # Validate the session before proceeding
#         session = args[0]
#         if not auth_manager().is_session_valid(session):
#             return xen_api_error(['SESSION_INVALID', session])
# 
#         # create and execute the task, and return task_uuid
#         return_type = getattr(method, 'return_type', '<none/>')
#         task_uuid = XendTaskManager.create_task(method, args,
#                                                 synchronous_method_name,
#                                                 return_type,
#                                                 synchronous_method_name,
#                                                 session)
#         return xen_api_success(task_uuid)

def instance():
    """Singleton constructror. Use this method instead of the class constructor.
    """
    global inst
    try:
        inst
    except:
        inst = BNVMAPI(None)
    return inst
 
