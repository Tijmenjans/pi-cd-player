"""Atomic, private state files; failed writes never expose partial contents."""
import json
import os
import tempfile
from pathlib import Path


def write_text(path, text, durable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
        os.replace(temporary, path)
        if durable:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value, durable=False):
    write_text(path, json.dumps(value), durable)


def read_text(path, default=''):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return default
