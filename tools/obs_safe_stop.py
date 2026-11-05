"""OBS stop/profile-switch guard. No credentials, OBS installation or app automation.

request is a callable: request('StopRecord') -> responseData dict.
Use with your own local authenticated obs-websocket adapter.
Windows additionally waits until the recording file can be exclusively opened.
"""
import ctypes
import os
from pathlib import Path
import time
import uuid


def ensure_record_directory(path):
    directory = Path(path).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ('.obs-write-check-' + uuid.uuid4().hex)
    try:
        with probe.open('xb') as handle:
            handle.write(b'OBS directory write check')
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if probe.exists():
            probe.unlink()
    return directory


def _closed_on_windows(path):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return False
    kernel.CloseHandle(handle)
    return True


def stop_record_safely(request, timeout=20):
    stopped = request('StopRecord')
    path = Path(stopped['outputPath'])
    deadline = time.monotonic() + timeout
    stable = 0
    previous_size = None
    while time.monotonic() < deadline:
        inactive = not request('GetRecordStatus')['outputActive']
        size = path.stat().st_size if path.exists() else None
        closed = inactive and size is not None and size > 0
        if closed:
            closed = _closed_on_windows(path) if os.name == 'nt' else size == previous_size
        stable = stable + 1 if closed else 0
        if stable >= (3 if os.name == 'nt' else 12):
            return stopped
        previous_size = size
        time.sleep(.2)
    raise TimeoutError('OBS output has not fully closed; do not restore the profile yet')
