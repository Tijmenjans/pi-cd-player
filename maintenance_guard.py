"""Coordinate web actions with the deploy tool using the same flock inode."""
from contextlib import contextmanager
import fcntl
from functools import wraps
import os

class MaintenanceBusy(RuntimeError):pass

@contextmanager
def action_lease(path):
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise MaintenanceBusy('Onderhoud bezig; probeer de bediening straks opnieuw.') from None
        yield

def guarded_action(path):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            try:
                with action_lease(path):return function(*args,**kwargs)
            except MaintenanceBusy as exc:
                from flask import jsonify
                return jsonify(error=str(exc)),409
        return wrapped
    return decorate
