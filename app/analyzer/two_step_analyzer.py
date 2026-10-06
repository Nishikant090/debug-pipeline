"""
TwoStepAnalyzer — the LLM pipeline that runs on every detected error.

Step 1 — Identify:
    Input : error log entry  +  index (function names + descriptions)
    Output: list of suspected function names + reasoning

Step 2 — Analyze:
    Input : error log entry  +  full source code of each suspected function
    Output: root cause, explanation, debugging steps, fixes, severity

Step 3 — Fix (on demand, from the dashboard):
    Input : error log entry  +  Step 2 root cause  +  suspected function source
    Output: full replacement source for each function that must change
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from groq import AsyncGroq, APIConnectionError, APIStatusError, RateLimitError

from app.config import settings
from app.models import (
    AnalyzedEvent, BackendIndex, ErrorEvent,
    FunctionInfo, Step1Result, Step2Result,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_SUSPECTED_FUNCTIONS = 6  # how many Step 1 suspects get their source sent to Steps 2 and 3
MAX_LOG_ENTRY_CHARS = 8000  # guards against a caller pasting an oversized/malformed log entry


def _format_log_entry(log_entry: dict[str, Any]) -> str:
    """JSON-formats a log entry, truncating if some field is unexpectedly huge."""
    text = json.dumps(log_entry, indent=2, default=str)
    if len(text) > MAX_LOG_ENTRY_CHARS:
        text = text[:MAX_LOG_ENTRY_CHARS] + "\n... [truncated — log entry too large]"
    return text


# ── System prompts ─────────────────────────────────────────────────────────────

_STEP1_SYSTEM = """
You are a backend debugging specialist.

Given a JSON error log entry and an index of all functions in the codebase
(function name + description), your job is to identify which functions are most
likely responsible for the error.

Respond with ONLY valid JSON — no markdown, no preamble:
{
  "suspected_functions": ["function_name_1", "function_name_2"],
  "reasoning": "One or two sentences explaining why these functions are implicated.",
  "confidence": 0.0
}

Rules:
- List 1–5 function names only.
- If nothing matches, return an empty list with reasoning "No matching functions found."
- confidence is 0.0–1.0.
"""

_STEP2_SYSTEM = """
You are an elite senior backend debugging engineer with 15+ years of experience.

You have been given a production error log entry and the actual source code of the
functions suspected of causing it. Perform a thorough root-cause analysis.

Respond with ONLY valid JSON — no markdown, no preamble:
{
  "root_cause": "One precise sentence.",
  "technical_explanation": "2–4 paragraphs covering why this happens and its impact.",
  "debugging_steps": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
  "possible_fixes": [
    "Fix 1 (immediate): concrete fix with code example if helpful",
    "Fix 2 (short-term): ...",
    "Fix 3 (long-term): ..."
  ],
  "severity": "low|medium|high|critical",
  "confidence_score": 0.0,
  "affected_components": ["component1"]
}

Severity guide:
- critical: service down / data loss
- high: feature broken, no workaround
- medium: degraded, workaround exists
- low: edge case / cosmetic
"""

_NO_INDEX_SYSTEM = """
You are an elite senior backend debugging engineer with 15+ years of experience.

You have been given a production error log entry (JSON). No source code is available,
but the error message, traceback, service name, and context fields are enough to
perform a thorough root-cause analysis.

Respond with ONLY valid JSON — no markdown, no preamble:
{
  "root_cause": "One precise sentence identifying the root cause from the error/traceback.",
  "technical_explanation": "2–4 paragraphs: what went wrong, why it happens, what the impact is.",
  "debugging_steps": [
    "Step 1: <specific actionable step>",
    "Step 2: <specific actionable step>",
    "Step 3: <specific actionable step>"
  ],
  "possible_fixes": [
    "Fix 1 (immediate): <concrete fix — include code snippet if helpful>",
    "Fix 2 (short-term): <better solution>",
    "Fix 3 (long-term): <architectural improvement>"
  ],
  "suspected_functions": ["<function or module name from the traceback if visible, else empty>"],
  "severity": "low|medium|high|critical",
  "confidence_score": 0.75,
  "affected_components": ["<service or component name>"]
}

Severity guide:
- critical: service down / data loss / security breach
- high: feature completely broken, no workaround
- medium: degraded performance or partial failure, workaround exists
- low: edge case or cosmetic issue

Important: Give real, actionable fixes based on the error type. Never say
"upload codebase index" — that is an internal tool instruction, not a fix.
"""

_STEP3_SYSTEM = """
You are a senior backend engineer writing the code fix for a production bug.

You have been given the error log entry, the root-cause analysis, and the full
source of the functions suspected of causing it. Rewrite only the functions that
must change to fix the root cause.

Respond with ONLY valid JSON — no markdown, no preamble:
{
  "summary": "One or two sentences: what the fix changes and why it resolves the error.",
  "edits": [
    {
      "function": "exact function name from the source headings",
      "new_source": "the complete replacement source of that function"
    }
  ]
}

Rules:
- new_source replaces the original snippet exactly: start on the same line it starts
  on (its signature, without decorators that aren't in the snippet) and end where it ends.
- Return every changed function in full. Never use "...", "# rest unchanged" or other placeholders.
- Make the smallest change that fixes the root cause. Keep the name, signature,
  indentation, docstring and comments unless the fix requires changing them.
- You can only change these functions. If the fix needs a new import, import it
  inside the function.
- If the bug can't be fixed inside these functions (for example it needs a database
  index or a config change), return "edits": [] and say what is needed in summary.
"""


# ── JSON extraction helper ─────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict[str, Any]:
    for attempt in (
        lambda: json.loads(raw),
        lambda: json.loads(re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL).group(1)),
        lambda: json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0)),
    ):
        try:
            return attempt()
        except Exception:
            pass
    raise ValueError(f"Cannot extract JSON from LLM output: {raw[:300]}")


# ── Analyzer class ─────────────────────────────────────────────────────────────

class TwoStepAnalyzer:
    def __init__(self, index: BackendIndex | None = None) -> None:
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._index = index
        # Function lookup: name → FunctionInfo, file_path
        self._fn_map: dict[str, tuple[FunctionInfo, str]] = {}
        if index:
            for fi in index.files:
                for fn in fi.functions:
                    self._fn_map.setdefault(fn.name, (fn, fi.path))
            logger.info(
                "TwoStepAnalyzer ready — %d functions indexed", len(self._fn_map)
            )
        else:
            logger.info("TwoStepAnalyzer ready — no-index mode (error-only analysis)")

    # ── Public entry point (with index) ───────────────────────────────────────

    async def analyze(self, event: ErrorEvent) -> AnalyzedEvent:
        step1 = await self._step1_identify(event)
        logger.info(
            "Step 1 complete — suspected: %s (confidence=%.2f)",
            step1.suspected_functions, step1.confidence,
        )

        step2 = await self._step2_analyze(event, step1)
        logger.info(
            "Step 2 complete — severity=%s confidence=%.2f",
            step2.severity, step2.confidence_score,
        )

        return AnalyzedEvent(
            id=str(uuid.uuid4()),
            error=event,
            step1=step1,
            step2=step2,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Public entry point (no index — error-only analysis) ───────────────────

    async def analyze_without_index(self, event: ErrorEvent) -> AnalyzedEvent:
        """
        Full LLM analysis using only the error log entry (no codebase index).
        Extracts root cause, fixes, severity, and suspected components
        directly from the error message and traceback.
        """
        logger.info("No-index analysis for event %s", event.id[:8])

        user_msg = (
            "## Production Error Log Entry\n"
            "```json\n"
            f"{_format_log_entry(event.log_entry)}\n"
            "```\n\n"
            "Analyse this error thoroughly. Use the error message, traceback, "
            "service name, and any other fields in the JSON to identify the root cause "
            "and provide concrete, actionable fixes."
        )

        data = await self._call_llm_json(_NO_INDEX_SYSTEM, user_msg)

        # Normalise fields
        data.setdefault("affected_components", [])
        data.setdefault("suspected_functions", [])
        data["confidence_score"] = max(0.0, min(1.0, float(data.get("confidence_score", 0.70))))
        for field in ("debugging_steps", "possible_fixes", "affected_components", "suspected_functions"):
            if not isinstance(data.get(field), list):
                data[field] = []

        step1 = Step1Result(
            suspected_functions=data.get("suspected_functions", []),
            reasoning=(
                "Inferred from error message and traceback — "
                "no codebase index loaded. Upload your backend ZIP in ⚙️ Setup Index for deeper analysis."
            ),
            confidence=0.5,
        )
        step2 = Step2Result(
            **{k: v for k, v in data.items() if k in Step2Result.model_fields}
        )

        logger.info(
            "No-index analysis done — severity=%s confidence=%.2f",
            step2.severity, step2.confidence_score,
        )

        return AnalyzedEvent(
            id=str(uuid.uuid4()),
            error=event,
            step1=step1,
            step2=step2,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Step 1 ─────────────────────────────────────────────────────────────────

    async def _step1_identify(self, event: ErrorEvent) -> Step1Result:
        fn_index_lines = []
        for fi in self._index.files:
            for fn in fi.functions:
                fn_index_lines.append(
                    f"  - {fn.name} ({fi.path}): {fn.description[:150]}"
                )

        user_msg = (
            f"## Error Log Entry\n```json\n"
            f"{_format_log_entry(event.log_entry)}\n```\n\n"
            f"## Function Index ({len(fn_index_lines)} functions)\n"
            + "\n".join(fn_index_lines[:150])  # cap to ~150 functions to fit context
        )

        data = await self._call_llm_json(_STEP1_SYSTEM, user_msg)

        return Step1Result(
            suspected_functions=data.get("suspected_functions", []),
            reasoning=data.get("reasoning", ""),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        )

    # ── Step 2 ─────────────────────────────────────────────────────────────────

    async def _step2_analyze(self, event: ErrorEvent, step1: Step1Result) -> Step2Result:
        MAX_SOURCE_CHARS = 6000  # per function — guards against huge/generated files blowing the context budget
        code_blocks: list[str] = []
        for fn_name in step1.suspected_functions[:MAX_SUSPECTED_FUNCTIONS]:
            if fn_name in self._fn_map:
                fn_info, file_path = self._fn_map[fn_name]
                source = fn_info.source_code
                if len(source) > MAX_SOURCE_CHARS:
                    source = source[:MAX_SOURCE_CHARS] + "\n... [truncated — function too large to include in full]"
                code_blocks.append(
                    f"### `{fn_name}` — {file_path}\n"
                    f"**Description**: {fn_info.description}\n"
                    f"```\n{source}\n```"
                )

        if not code_blocks:
            code_blocks.append("*(No matching function source code found in index)*")

        user_msg = (
            f"## Production Error\n```json\n"
            f"{_format_log_entry(event.log_entry)}\n```\n\n"
            f"## Step 1 Reasoning\n{step1.reasoning}\n\n"
            f"## Suspected Function Source Code\n"
            + "\n\n".join(code_blocks)
        )

        data = await self._call_llm_json(_STEP2_SYSTEM, user_msg)

        data.setdefault("optimization_recommendations", [])
        data.setdefault("affected_components", [])
        data["confidence_score"] = max(0.0, min(1.0, float(data.get("confidence_score", 0.75))))

        for field in ("debugging_steps", "possible_fixes", "affected_components"):
            if not isinstance(data.get(field), list):
                data[field] = []

        return Step2Result(**{k: v for k, v in data.items() if k in Step2Result.model_fields})

    # ── Step 3 (on demand) ─────────────────────────────────────────────────────

    def function(self, name: str) -> tuple[FunctionInfo, str] | None:
        """The indexed function and its file path, as Step 2 saw it."""
        return self._fn_map.get(name)

    async def propose_fix(self, analyzed: AnalyzedEvent) -> tuple[str, list[dict[str, str]]]:
        """Ask the LLM to rewrite the suspected functions. Returns (summary, edits)."""
        code_blocks = []
        for fn_name in analyzed.step1.suspected_functions[:MAX_SUSPECTED_FUNCTIONS]:
            if found := self.function(fn_name):
                fn_info, file_path = found
                code_blocks.append(f"### `{fn_name}` — {file_path}\n```\n{fn_info.source_code}\n```")
        if not code_blocks:
            raise ValueError("None of the suspected functions are in the index")

        s2 = analyzed.step2
        user_msg = (
            f"## Production Error\n```json\n"
            f"{_format_log_entry(analyzed.error.log_entry)}\n```\n\n"
            f"## Root Cause\n{s2.root_cause}\n\n"
            f"## Explanation\n{s2.technical_explanation}\n\n"
            f"## Suggested Fixes\n" + "\n".join(f"- {f}" for f in s2.possible_fixes) + "\n\n"
            f"## Suspected Function Source Code\n" + "\n\n".join(code_blocks)
        )

        data = await self._call_llm_json(_STEP3_SYSTEM, user_msg, max_tokens=max(settings.groq_max_tokens, 4096))
        edits = [
            e for e in data.get("edits") or []
            if isinstance(e, dict) and isinstance(e.get("function"), str) and isinstance(e.get("new_source"), str)
        ]
        return str(data.get("summary", "")), edits

    # ── Groq caller with retry ─────────────────────────────────────────────────

    async def _call_llm(self, system: str, user: str, max_tokens: int | None = None) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for attempt in range(1, 4):
            try:
                resp = await self._client.chat.completions.create(
                    model=settings.groq_model,
                    messages=messages,
                    temperature=settings.groq_temperature,
                    max_tokens=max_tokens or settings.groq_max_tokens,
                    timeout=settings.groq_timeout,
                )
                content = resp.choices[0].message.content
                if not content:
                    raise ValueError("Empty LLM response")
                return content
            except RateLimitError:
                if attempt == 3:
                    raise RuntimeError("Groq rate limit exceeded")
                await asyncio.sleep(2 ** attempt)
            except APIConnectionError as e:
                raise RuntimeError(f"Groq connection error: {e}") from e
            except APIStatusError as e:
                raise RuntimeError(f"Groq API error {e.status_code}: {e.message}") from e
        raise RuntimeError("LLM call failed after 3 attempts")

    async def _call_llm_json(self, system: str, user: str, max_tokens: int | None = None) -> dict[str, Any]:
        """Call the LLM and parse its JSON reply, asking once more if the reply is malformed."""
        for attempt in range(1, 3):
            raw = await self._call_llm(system, user, max_tokens)
            try:
                return _extract_json(raw)
            except ValueError:
                if attempt == 2:
                    raise
                logger.warning("LLM returned malformed JSON — retrying once")
