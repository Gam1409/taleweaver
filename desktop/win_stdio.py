"""Reconnect a windowed Windows service to its supervisor's redirected pipe."""

import os
import sys


def restore() -> None:
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    handle = kernel.GetStdHandle(0xFFFFFFF5)  # STD_OUTPUT_HANDLE (-11)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise RuntimeError("The desktop service has no redirected output pipe.")
    descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY)
    stream = os.fdopen(descriptor, "w", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = stream
    sys.stderr = stream
