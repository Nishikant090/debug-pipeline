"""Tests for the auto-fix patcher. Run with: pytest"""
from pathlib import Path

import pytest

from app.analyzer.patcher import (
    PatchConflict, _clean_source, _file_change, _snippet_diff, write_changes,
)
from app.models import FunctionEdit

SOURCE = (
    "import os\n"
    "\n"
    "def first():\n"
    "    return 1\n"
    "\n"
    "def second():\n"
    "    return 2\n"
)


def _edit(fn: str, start: int, end: int, old: str, new: str) -> FunctionEdit:
    return FunctionEdit(function=fn, file_path="/mod.py", start_line=start, end_line=end,
                        original_source=old, new_source=new)


FIRST = _edit("first", 3, 4, "def first():\n    return 1", "def first():\n    x = 1\n    return x")
SECOND = _edit("second", 6, 7, "def second():\n    return 2", "def second():\n    return 22")


def test_clean_source_strips_fences_and_reindents():
    original = "    def method(self):\n        return 1"
    llm = "```python\ndef method(self):\n    return 2\n```"
    assert _clean_source(llm, original) == "    def method(self):\n        return 2"


def test_clean_source_empty():
    assert _clean_source("```\n```", "def f():\n    pass") == ""


def test_snippet_diff_offsets_later_hunks_in_same_file():
    diff = _snippet_diff([FIRST, SECOND])
    assert diff.startswith("--- a/mod.py\n+++ b/mod.py\n")
    hunks = [line for line in diff.splitlines() if line.startswith("@@")]
    # first() grows by one line, so second()'s new-side line moves from 7 to 8
    assert hunks == ["@@ -4 +4,2 @@", "@@ -7 +8 @@"]


def test_file_change_applies_edits(tmp_path: Path):
    (tmp_path / "mod.py").write_text(SOURCE, newline="")
    fc = _file_change(tmp_path.resolve(), "/mod.py", [FIRST, SECOND])
    assert fc.original == SOURCE
    assert "    x = 1\n    return x\n" in fc.patched
    assert "return 22\n" in fc.patched


def test_file_change_keeps_crlf(tmp_path: Path):
    (tmp_path / "mod.py").write_bytes(SOURCE.replace("\n", "\r\n").encode())
    fc = _file_change(tmp_path.resolve(), "/mod.py", [SECOND])
    assert fc.patched.endswith("    return 22\r\n")
    assert "\n" not in fc.patched.replace("\r\n", "")


def test_file_change_detects_stale_index(tmp_path: Path):
    (tmp_path / "mod.py").write_text(SOURCE.replace("return 2", "return 3"), newline="")
    with pytest.raises(PatchConflict, match="changed after the index"):
        _file_change(tmp_path.resolve(), "/mod.py", [SECOND])


def test_file_change_rejects_invalid_python(tmp_path: Path):
    (tmp_path / "mod.py").write_text(SOURCE, newline="")
    broken = _edit("second", 6, 7, "def second():\n    return 2", "def second(:\n    return 2")
    with pytest.raises(PatchConflict, match="isn't valid Python"):
        _file_change(tmp_path.resolve(), "/mod.py", [broken])


def test_file_change_rejects_paths_outside_root(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "mod.py").write_text(SOURCE, newline="")
    with pytest.raises(PatchConflict, match="outside the indexed folder"):
        _file_change(root.resolve(), "../mod.py", [SECOND])


def test_write_and_revert_round_trip(tmp_path: Path):
    path = tmp_path / "mod.py"
    path.write_text(SOURCE, newline="")
    fc = _file_change(tmp_path.resolve(), "/mod.py", [FIRST])
    write_changes([fc])
    assert path.read_text() == fc.patched
    write_changes([fc], revert=True)
    assert path.read_text() == SOURCE


def test_revert_refuses_after_manual_edit(tmp_path: Path):
    path = tmp_path / "mod.py"
    path.write_text(SOURCE, newline="")
    fc = _file_change(tmp_path.resolve(), "/mod.py", [FIRST])
    write_changes([fc])
    path.write_text("edited by hand\n", newline="")
    with pytest.raises(PatchConflict, match="can't be reverted"):
        write_changes([fc], revert=True)
