"""Windows backend for the link-safe workspace digest (Hermes-on-Windows stage S1). Trusted host-side code.

The POSIX walker (`workbench.digest`) relies on O_NOFOLLOW, which Windows does not have. Here a file is opened with
CreateFileW and FILE_FLAG_OPEN_REPARSE_POINT, so a symbolic link or junction swapped in after the directory listing is
opened as the link itself and never as its target; the attributes of the opened handle (not of the path) then decide what
the entry is. The output format is the same as the POSIX walker's:

  regular file      -> "file:<sha256>"        (+ ":truncated:<size>", ":nlink>1", ":ads:<names>")
  symlink/junction  -> "link:<target>"        (any reparse point; the target is never opened or listed)
  directory         -> "dir"                  (+ ":ads:<names>"), walked unless it is a reparse point
  anything else     -> "special:other"

Alternate data streams (hidden extra content on an NTFS file or folder) are named in the entry, so adding one changes
the digest. Hard links are flagged because their content is shared with a file elsewhere.
"""

import ctypes
import hashlib
import msvcrt
import os
import stat
from ctypes import wintypes

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
GENERIC_READ = 0x80000000
FILE_SHARE_ALL = 0x7
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000   # needed to open a folder handle; harmless for files
INVALID_HANDLE = ctypes.c_void_p(-1).value
ERROR_HANDLE_EOF = 38
MAIN_STREAM = "::$DATA"

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.FindFirstStreamW.restype = wintypes.HANDLE
_k32.FindFirstStreamW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_k32.FindNextStreamW.restype = wintypes.BOOL
_k32.FindNextStreamW.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
_k32.FindClose.argtypes = [wintypes.HANDLE]


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME), ("accessed", wintypes.FILETIME),
                ("written", wintypes.FILETIME), ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD), ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD)]


class _StreamData(ctypes.Structure):
    _fields_ = [("size", ctypes.c_longlong), ("name", ctypes.c_wchar * 296)]


_k32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
_k32.GetFileInformationByHandle.restype = wintypes.BOOL


def streams(path) -> list:
    """Name=size of each alternate data stream on `path` (everything but the main data stream); [] if there are none.
    Stream CONTENT is not hashed: a stream rewritten to the same size is not noticed (documented limit)."""
    data = _StreamData()
    handle = _k32.FindFirstStreamW(os.fspath(path), 0, ctypes.byref(data), 0)
    if handle in (None, INVALID_HANDLE):
        return []  # no streams at all (a folder), or the path could not be opened: nothing to report
    try:
        names = []
        while True:
            if data.name != MAIN_STREAM:
                names.append(f"{data.name}={data.size}")  # name and size: a changed size changes the digest
            if not _k32.FindNextStreamW(handle, ctypes.byref(data)):
                break
        return sorted(names)
    finally:
        _k32.FindClose(handle)


def _suffix(path, names=None) -> str:
    found = streams(path) if names is None else names
    return ":ads:" + ",".join(found) if found else ""


def _link_text(path) -> str:
    try:
        return f"link:{os.readlink(path)}"
    except ValueError:  # a reparse point that is not an NT symlink, e.g. a WSL symlink made through a Docker bind mount
        try:
            return f"link:(reparse {int(os.lstat(path).st_reparse_tag):#x})"
        except (OSError, AttributeError, TypeError):
            return "link:(reparse)"
    except OSError:
        return "link:(unreadable)"


def _hash_file(path, limits) -> str:
    """Open `path` without following a reparse point, then decide from the opened handle."""
    max_bytes, chunk = limits
    h = _k32.CreateFileW(os.fspath(path), GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING,
                         FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, None)
    if h in (None, INVALID_HANDLE):
        raise ctypes.WinError(ctypes.get_last_error())
    info = _FileInfo()
    try:
        if not _k32.GetFileInformationByHandle(h, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & FILE_ATTRIBUTE_REPARSE_POINT:
            return _link_text(path)   # swapped for a link after the listing: record it, never read it
        if info.attributes & FILE_ATTRIBUTE_DIRECTORY:
            return "special:other"    # swapped for a folder
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
        h = None                      # the descriptor now owns the handle
        try:
            sha, left = hashlib.sha256(), max_bytes
            while left > 0:
                block = os.read(fd, min(chunk, left))
                if not block:
                    break
                sha.update(block)
                left -= len(block)
        finally:
            os.close(fd)
        size = (info.size_high << 32) | info.size_low
        out = f"file:{sha.hexdigest()}"
        if size > max_bytes:
            out += f":truncated:{size}"
        if info.links > 1:
            out += ":nlink>1"
        return out + _suffix(path)
    finally:
        if h is not None:
            _k32.CloseHandle(h)


def digest(root, max_entries, limits, limit_error) -> dict:
    """{relative path: entry} under `root`, never following a link. `limits` is (max bytes per file, read chunk)."""
    root = os.fspath(root)
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("digest root must be a real directory, not a link or file")
    out, stack = {}, [""]
    while stack:
        rel_dir = stack.pop()
        with os.scandir(os.path.join(root, rel_dir) if rel_dir else root) as it:
            for entry in it:
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name   # "/" like the POSIX walker, so records match
                if len(out) >= max_entries:
                    raise limit_error(f"more than {max_entries} entries")
                est = entry.stat(follow_symlinks=False)
                attrs = est.st_file_attributes
                if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                    out[rel] = _link_text(entry.path)
                elif attrs & FILE_ATTRIBUTE_DIRECTORY:
                    out[rel] = "dir" + _suffix(entry.path)
                    stack.append(rel)
                elif stat.S_ISREG(est.st_mode):
                    out[rel] = _hash_file(entry.path, limits)
                else:
                    out[rel] = "special:other"
    return dict(sorted(out.items()))
