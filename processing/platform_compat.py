"""What differs on native Windows, in one place. Elsewhere importing this module
changes nothing and its helpers are the plain POSIX behaviour.

Importing it makes this process print UTF-8 on Windows. A redirected or piped
Python prints in the ANSI code page, and cp1252 cannot encode the role names:
print("狼人") raises UnicodeEncodeError, which killed the analysis wherever
stdout was not a console (a server job, the OCR subprocess's log file).
"""
import os
import sys
import time

WINDOWS = os.name == "nt"


def venv_python(processing_dir):
    """The project venv's interpreter: Scripts\\python.exe on Windows."""
    if WINDOWS:
        return os.path.join(processing_dir, "venv", "Scripts", "python.exe")
    return os.path.join(processing_dir, "venv", "bin", "python3")


def replace_file(src, dst):
    """os.replace that waits out Windows refusing a rename while anything has
    either file open for a moment (a reader, the indexer, antivirus on a file
    just written)."""
    tries = 20 if WINDOWS else 1
    for attempt in range(tries):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.25)


if WINDOWS:
    # Python children (the OCR subprocess, yt-dlp) inherit this
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
