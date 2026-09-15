"""Operating-system-backed locking for one durable run directory."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
from typing import BinaryIO, Iterator

from .errors import RunLockedError, RunStoreError


LOCK_FILE_NAME = ".run.lock"
_LOCK_CONTENTION_ERRNOS = frozenset((errno.EACCES, errno.EAGAIN))


@contextmanager
def acquire_run_lock(run_dir: Path) -> Iterator[None]:
    """Acquire a nonblocking OS lock for ``run_dir`` until the context exits.

    The persistent lock file is only a lock target; its presence never establishes
    ownership. The open descriptor carries ownership for the lifetime of this
    context manager.
    """
    lock_path = run_dir / LOCK_FILE_NAME
    _validate_lock_target_before_open(lock_path)
    try:
        lock_file = lock_path.open("a+b")
    except OSError as exc:
        raise RunStoreError(f"could not open run lock: {lock_path}") from exc

    try:
        _validate_open_lock_target(lock_path, lock_file)
        acquired = _try_acquire(lock_file)
    except (OSError, RunStoreError) as exc:
        lock_file.close()
        if isinstance(exc, RunStoreError):
            raise
        raise RunStoreError(f"could not acquire run lock: {lock_path}") from exc
    if not acquired:
        lock_file.close()
        raise RunLockedError(run_dir)

    try:
        yield
    finally:
        try:
            _release(lock_file)
        finally:
            lock_file.close()


def _try_acquire(lock_file: BinaryIO) -> bool:
    """Attempt a platform-native exclusive lock without waiting."""
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in _LOCK_CONTENTION_ERRNOS:
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _LOCK_CONTENTION_ERRNOS:
            return False
        raise
    return True


def _release(lock_file: BinaryIO) -> None:
    """Release the platform-native lock while keeping the lock file on disk."""
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _is_link_or_reparse_point(metadata: os.stat_result) -> bool:
    """Return whether metadata names a symbolic link or Windows reparse point."""
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_point
    )


def _validate_lock_target_before_open(lock_path: Path) -> None:
    """Reject an existing unsafe lock path before opening can follow or mutate it."""
    try:
        metadata = lock_path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RunStoreError(f"could not inspect run lock: {lock_path}") from exc
    if _is_link_or_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RunStoreError(f"unsafe run lock target: {lock_path}")


def _validate_open_lock_target(lock_path: Path, lock_file: BinaryIO) -> None:
    """Close the check/open race before platform locking can write a sentinel byte."""
    try:
        path_metadata = lock_path.lstat()
        descriptor_metadata = os.fstat(lock_file.fileno())
    except OSError as exc:
        raise RunStoreError(f"could not inspect open run lock: {lock_path}") from exc
    if (
        _is_link_or_reparse_point(path_metadata)
        or not stat.S_ISREG(path_metadata.st_mode)
        or path_metadata.st_nlink != 1
        or not os.path.samestat(path_metadata, descriptor_metadata)
    ):
        raise RunStoreError(f"unsafe run lock target: {lock_path}")
