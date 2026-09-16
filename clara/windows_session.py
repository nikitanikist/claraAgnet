"""Keep the dedicated Windows session alive while Clara waits.

Remote Desktop Services counts only user input as activity. A locked or idle
client sends none, so the server's idle-session limit disconnects the session
and Clara's process ends with it (16 Sep 2026: "Idle timer expired" after the
Mac locked). A zero-net mouse move is real input for that timer and changes
nothing on screen. The server's own session limits still belong to IT; this
only stops an idle worker from being counted as an absent person.
"""
import ctypes
import os

KEEPALIVE_S = 240


def touch_input():
    """Move the pointer one pixel right and back again; True when Windows accepted both events."""
    if os.name != 'nt':
        return False
    try:
        from ctypes import wintypes
        MOUSEEVENTF_MOVE = 0x0001

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                        ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            class _Union(ctypes.Union):
                _fields_ = [('mi', MOUSEINPUT)]
            _anonymous_ = ('u',)
            _fields_ = [('type', wintypes.DWORD), ('u', _Union)]

        moves = (INPUT * 2)()
        for item, dx in zip(moves, (1, -1)):
            item.type = 0  # INPUT_MOUSE
            item.mi = MOUSEINPUT(dx, 0, 0, MOUSEEVENTF_MOVE, 0, 0)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        return user32.SendInput(2, moves, ctypes.sizeof(INPUT)) == 2
    except Exception:
        return False
