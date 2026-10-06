"""
Patcher — turns Step 3's rewritten functions into a diff, and writes or reverts it.

Each edit replaces the exact line range the indexer recorded for that function.
Nothing is written unless the file still holds the indexed source at those lines,
so a patch never lands on code that changed after indexing.
"""
from __future__ import annotations

import ast
import difflib
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from app.analyzer.two_step_analyzer import TwoStepAnalyzer
from app.models import FileChange, FixProposal, FunctionEdit

_FENCE = re.compile(r"^\s*```[\w+-]*\n(.*?)\n?```\s*$", re.DOTALL)
_HUNK = re.compile(r"^@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@")


class PatchConflict(Exception):
    """The files on disk aren't in the state the patch expects."""


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _clean_source(new_source: str, original: str) -> str:
    """Strip markdown fences and re-indent to the original's base indentation."""
    if m := _FENCE.match(new_source):
        new_source = m.group(1)
    new_source = new_source.strip("\n").rstrip()
    if not new_source:
        return ""
    base = _indent_of(original.splitlines()[0])
    if _indent_of(new_source.splitlines()[0]) != base:
        new_source = textwrap.indent(textwrap.dedent(new_source), base)
    return new_source


def _lines(text: str) -> list[str]:
    return [line + "\n" for line in text.splitlines()]


def _file_diff(rel: str, original: str, patched: str) -> str:
    """Whole-file unified diff; paths are relative to the indexed folder."""
    rel = rel.lstrip("/")
    return "".join(difflib.unified_diff(_lines(original), _lines(patched), f"a/{rel}", f"b/{rel}"))


def _snippet_diff(edits: list[FunctionEdit]) -> str:
    """Zero-context diff built from the indexed functions alone, for when the files aren't on disk.

    Line numbers are real file lines, so `git apply --unidiff-zero` applies it.
    """
    out: list[str] = []
    current_file = None
    delta = 0  # how far earlier edits in the same file moved the new-side line numbers
    for e in edits:  # sorted by (file_path, start_line)
        if e.file_path != current_file:
            current_file, delta = e.file_path, 0
            rel = e.file_path.lstrip("/")
            out += [f"--- a/{rel}\n", f"+++ b/{rel}\n"]
        old, new = _lines(e.original_source), _lines(e.new_source)
        for line in list(difflib.unified_diff(old, new, n=0))[2:]:
            if m := _HUNK.match(line):
                offset = e.start_line - 1
                line = (f"@@ -{int(m[1]) + offset}{m[2] or ''} "
                        f"+{int(m[3]) + offset + delta}{m[4] or ''} @@\n")
            out.append(line)
        delta += len(new) - len(old)
    return "".join(out)


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _file_change(root: Path, rel: str, edits: list[FunctionEdit]) -> FileChange:
    path = (root / rel.lstrip("/")).resolve()
    if root not in path.parents:
        raise PatchConflict(f"{rel} is outside the indexed folder.")
    if not path.is_file():
        raise PatchConflict(f"{rel} no longer exists. Re-index the codebase.")

    text = _read(path)
    lines = text.splitlines()
    for e in reversed(edits):  # bottom-up, so earlier line numbers stay valid
        if "\n".join(lines[e.start_line - 1:e.end_line]) != e.original_source:
            raise PatchConflict(
                f"`{e.function}` in {rel} changed after the index was built. "
                "Re-index the codebase, then generate the fix again."
            )
        lines[e.start_line - 1:e.end_line] = e.new_source.splitlines()

    nl = "\r\n" if "\r\n" in text else "\n"
    patched = nl.join(lines) + (nl if text.endswith(("\n", "\r")) else "")
    if path.suffix == ".py":
        try:
            ast.parse(patched)
        except SyntaxError as exc:
            raise PatchConflict(
                f"The generated code for {rel} isn't valid Python (line {exc.lineno}: {exc.msg}). "
                "Generate the fix again."
            ) from exc
    return FileChange(path=path, original=text, patched=patched)


def build_proposal(
    analyzer: TwoStepAnalyzer,
    index_root: str,
    allowed_functions: list[str],
    summary: str,
    raw_edits: list[dict[str, str]],
) -> FixProposal:
    """Validate the LLM's edits against the index and the files on disk."""
    by_name: dict[str, FunctionEdit] = {}
    for raw in raw_edits:
        name = raw["function"]
        found = analyzer.function(name) if name in allowed_functions else None
        if found is None:
            continue  # the LLM named a function it wasn't given
        fn, rel = found
        new_source = _clean_source(raw["new_source"], fn.source_code)
        if new_source and new_source != fn.source_code:
            by_name[name] = FunctionEdit(
                function=name, file_path=rel, start_line=fn.start_line, end_line=fn.end_line,
                original_source=fn.source_code, new_source=new_source,
            )

    # Drop edits that overlap an earlier one in the same file (e.g. a nested function).
    edits: list[FunctionEdit] = []
    for e in sorted(by_name.values(), key=lambda e: (e.file_path, e.start_line)):
        if edits and edits[-1].file_path == e.file_path and e.start_line <= edits[-1].end_line:
            continue
        edits.append(e)

    proposal = FixProposal(
        summary=summary or "No summary returned.",
        edits=edits,
        diff=_snippet_diff(edits),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    if not edits:
        return proposal

    root = Path(index_root).resolve()
    if not root.is_dir():
        proposal.apply_blocker = (
            "The index was built from an uploaded ZIP, so the source isn't on the API server. "
            "Download the patch and run `git apply --unidiff-zero <file>.patch` in your project folder."
        )
        return proposal

    files = sorted({e.file_path for e in edits})
    try:
        proposal.file_changes = [
            _file_change(root, rel, [e for e in edits if e.file_path == rel]) for rel in files
        ]
    except PatchConflict as exc:
        proposal.apply_blocker = str(exc)
        return proposal
    proposal.diff = "".join(
        _file_diff(rel, fc.original, fc.patched) for rel, fc in zip(files, proposal.file_changes)
    )
    proposal.can_apply = True
    return proposal


def write_changes(changes: list[FileChange], revert: bool = False) -> None:
    """Write the patched text (or, with revert, the original text) to every file.

    Checks all files first, so either every file is written or none is.
    """
    for fc in changes:
        expected = fc.patched if revert else fc.original
        if _read(fc.path) != expected:
            raise PatchConflict(
                f"{fc.path.name} was edited after the fix was "
                + ("applied, so it can't be reverted automatically." if revert
                   else "generated. Re-index the codebase and generate the fix again.")
            )
    for fc in changes:
        _write(fc.path, fc.original if revert else fc.patched)
