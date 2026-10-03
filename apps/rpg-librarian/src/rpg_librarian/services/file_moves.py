"""Filesystem rename that atomically refuses to replace an existing destination."""

import ctypes
import errno
import os
from pathlib import Path


def rename_no_replace(source: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(source, destination)  # Windows rename refuses existing destinations.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
            return
        code = ctypes.get_errno()
        if code not in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise OSError(code, os.strerror(code), str(destination))
    # Link creation is exclusive too; never fall back to a replacing rename.
    os.link(source, destination)
    try:
        source.unlink()
    except BaseException:
        destination.unlink()
        raise
