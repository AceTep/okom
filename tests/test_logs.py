import logging
import sys
import threading

import pytest

from shared.logs import setup_logging


@pytest.fixture(autouse=True)
def restore_logging(monkeypatch):
    """setup_logging changes global state: put back handlers and exception hooks."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        if h not in handlers:
            h.close()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)


def test_log_file_written_and_old_ones_deleted(tmp_path) -> None:
    for i in range(5):
        (tmp_path / f"20260101-00000{i}_app.log").write_text("old")
    (tmp_path / "20260101-000000_gaze.log").write_text("other program")
    path = setup_logging("app", log_dir=tmp_path, keep=3)
    logging.getLogger("test").info("hello file")
    for h in logging.getLogger().handlers:
        h.flush()
    assert "hello file" in path.read_text()
    assert len(list(tmp_path.glob("*_app.log"))) == 3  # 2 old + this one
    assert (tmp_path / "20260101-000000_gaze.log").exists()  # other programs untouched


def test_uncaught_exceptions_reach_the_file(tmp_path) -> None:
    path = setup_logging("crashy", log_dir=tmp_path)
    try:
        raise RuntimeError("main thread boom")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    t = threading.Thread(target=lambda: 1 / 0, name="worker")
    t.start()
    t.join()
    for h in logging.getLogger().handlers:
        h.flush()
    text = path.read_text()
    assert "main thread boom" in text and "Traceback" in text
    assert "uncaught exception in thread worker" in text and "ZeroDivisionError" in text


def test_unwritable_dir_does_not_crash(tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    assert setup_logging("app", log_dir=blocker / "logs") is None
