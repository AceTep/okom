"""Logging to the terminal and to a file per run, for easier debugging.

Every program calls setup_logging() once at start-up. Each run gets its own
file in data/logs/ (never committed: logs contain window titles, which can be
private). Uncaught exceptions, also from background threads, are written to
the file with the full traceback before the program dies.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"
KEEP_PER_PROGRAM = 30  # older log files of the same program are deleted
FILE_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(threadName)s %(name)s: %(message)s"


def setup_logging(
    program: str,
    console_format: str = "%(asctime)s %(message)s",
    level: int = logging.INFO,
    log_dir: Path = LOG_DIR,
    keep: int = KEEP_PER_PROGRAM,
) -> Path | None:
    """Log to stderr and to data/logs/<time>_<program>.log. Returns the file, or None."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):  # calling it twice must not duplicate lines
        root.removeHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(console_format, datefmt="%H:%M:%S"))
    root.addHandler(console)

    path: Path | None = log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{program}.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _delete_old(log_dir, program, keep - 1)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        root.addHandler(handler)
    except OSError as exc:  # a read-only disk must not stop the program
        logging.getLogger(__name__).warning("cannot write a log file in %s: %s", log_dir, exc)
        path = None

    _log_uncaught_exceptions()
    if path is not None:
        logging.getLogger(__name__).debug("logging to %s", path)
        root.handlers[-1].stream.write(f"# {program}: {' '.join(sys.argv)}\n")
    return path


def _delete_old(log_dir: Path, program: str, keep: int) -> None:
    files = sorted(log_dir.glob(f"*_{program}.log"))
    for old in files[: max(0, len(files) - keep)]:
        old.unlink(missing_ok=True)


def _log_uncaught_exceptions() -> None:
    log = logging.getLogger("uncaught")

    def main_hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        log.critical(
            "uncaught exception in thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = main_hook
    threading.excepthook = thread_hook
