"""Explicit optical-disc backend. Import is safe without native libdiscid.

Offline tests configure a disabled backend; production loads libdiscid lazily.
"""
import importlib

FEATURE_READ=1
class DiscError(Exception):
    pass

_backend=None
_disabled=False

def configure_backend(backend=None, *, disabled=False):
    global _backend,_disabled
    _backend=backend;_disabled=disabled

def read(*args,**kwargs):
    global _backend
    if _disabled:raise DiscError('Optische hardware uitgeschakeld voor tests')
    if _backend is None:_backend=importlib.import_module('libdiscid')
    try:return _backend.read(*args,**kwargs)
    except _backend.DiscError as exc:raise DiscError(str(exc)) from exc
