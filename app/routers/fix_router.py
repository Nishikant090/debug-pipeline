"""
Fix Router — on-demand code patches for analysed incidents.

POST /api/v1/fix/{event_id}          Generate (or regenerate) a patch for the incident
POST /api/v1/fix/{event_id}/apply    Write the patch to the indexed source folder
POST /api/v1/fix/{event_id}/revert   Restore the files the patch changed
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.analyzer.patcher import PatchConflict, build_proposal, write_changes
from app.analyzer.two_step_analyzer import MAX_SUSPECTED_FUNCTIONS, TwoStepAnalyzer
from app.config import settings
from app.indexer.service import IndexingService
from app.models import AnalyzedEvent, FixProposal
from app.routers.index_router import INDEX_SAVE_PATH
from app.state import state
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _event(event_id: str) -> AnalyzedEvent:
    for ev in state.events:
        if ev.id == event_id:
            return ev
    raise HTTPException(404, f"Event {event_id} not found.")


async def _reindex() -> None:
    """Rebuild the index after files change, so line numbers and source stay current."""
    if state.index is None:
        return
    try:
        state.index = await IndexingService(Path(state.index.root_path)).run()
        IndexingService.save(state.index, INDEX_SAVE_PATH)
    except Exception as exc:
        logger.warning("Re-index after patch failed — rebuild it on Codebase: %s", exc)


@router.post("/fix/{event_id}", response_model=FixProposal, tags=["Fix"])
async def generate_fix(event_id: str):
    """Ask the LLM to rewrite the incident's suspected functions and return the patch."""
    ev = _event(event_id)
    if ev.fix and ev.fix.applied_at:
        raise HTTPException(409, "This incident's fix is applied. Revert it before generating a new one.")
    if state.index is None:
        raise HTTPException(400, "Auto-fix needs a codebase index. Build one on Codebase first.")

    analyzer = TwoStepAnalyzer(state.index)
    suspected = ev.step1.suspected_functions[:MAX_SUSPECTED_FUNCTIONS]
    if not any(analyzer.function(name) for name in suspected):
        raise HTTPException(400, "No indexed function was matched to this incident, so there is no code to fix.")

    try:
        summary, raw_edits = await analyzer.propose_fix(ev)
    except Exception as exc:
        raise HTTPException(502, f"Fix generation failed: {exc}")

    ev.fix = build_proposal(analyzer, state.index.root_path, suspected, summary, raw_edits)
    logger.info(
        "Fix for %s — %d function(s) changed, can_apply=%s",
        event_id[:8], len(ev.fix.edits), ev.fix.can_apply,
    )
    return ev.fix


@router.post("/fix/{event_id}/apply", response_model=FixProposal, tags=["Fix"])
async def apply_fix(event_id: str):
    """Write the generated patch to the source files, then re-index."""
    fix = _event(event_id).fix
    if fix is None:
        raise HTTPException(404, "Generate a fix first.")
    if fix.applied_at:
        raise HTTPException(409, "This fix is already applied.")
    if not settings.allow_fix_apply:
        raise HTTPException(403, "Applying fixes is turned off on this server (ALLOW_FIX_APPLY=false). Download the patch instead.")
    if not fix.can_apply:
        raise HTTPException(409, fix.apply_blocker or "This fix has no code changes to apply.")
    if settings.fix_apply_root:
        allowed = Path(settings.fix_apply_root).resolve()
        outside = [fc.path.name for fc in fix.file_changes if allowed not in fc.path.parents]
        if outside:
            raise HTTPException(
                403, f"This server only applies fixes inside {settings.fix_apply_root}. Download the patch instead."
            )

    try:
        write_changes(fix.file_changes)
    except PatchConflict as exc:
        raise HTTPException(409, str(exc))
    fix.applied_at = datetime.now(timezone.utc).isoformat()
    logger.info("Fix for %s applied to %s", event_id[:8], [str(fc.path) for fc in fix.file_changes])
    await _reindex()
    return fix


@router.post("/fix/{event_id}/revert", response_model=FixProposal, tags=["Fix"])
async def revert_fix(event_id: str):
    """Put back the original source of every file the fix changed, then re-index."""
    fix = _event(event_id).fix
    if fix is None or not fix.applied_at:
        raise HTTPException(409, "This incident has no applied fix to revert.")

    try:
        write_changes(fix.file_changes, revert=True)
    except PatchConflict as exc:
        raise HTTPException(409, str(exc))
    fix.applied_at = None
    logger.info("Fix for %s reverted", event_id[:8])
    await _reindex()
    return fix
