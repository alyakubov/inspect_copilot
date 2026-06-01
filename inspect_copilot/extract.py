"""LLM extraction: one chunk of report prose -> validated Observation rows.

This is the load-bearing AI step. The prompt is engineered to:
  - return STRICT JSON matching ExtractionResult (no prose, no fences)
  - use the controlled vocabulary, not free-form labels
  - NOT invent regulatory references (a known hallucination failure mode)
  - attach a short verbatim quote to every observation for audit traceability
  - return an empty list when a chunk contains no defect (e.g. a cover page)

Validation is non-negotiable: anything that fails Pydantic is quarantined in
the extraction_log, never written to the observations table.
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic
from pydantic import ValidationError

from .schema import ExtractionResult

_CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_MODEL = os.environ.get("ANTHROPIC_MODEL")
if not _MODEL:
    raise RuntimeError(
        "ANTHROPIC_MODEL is not set. Define it in .env (see .env.example) "
        "or export it in your shell."
    )

SYSTEM = """You extract building-defect observations from technical inspection reports.
Return ONLY a JSON object of the form {"observations": [...]}, with no prose and no code fences.

Each observation MUST use these controlled values:
- defect_type: one of crack | corrosion | damp_infiltration | spalling | deformation |
  fire_safety_noncompliance | material_degradation | other
- severity: one of info | monitor | repair | urgent

Rules:
- One observation per distinct defect described. A chunk may yield zero observations
  (cover pages, tables of contents, general prose) — return an empty list then.
- regulatory_reference: fill ONLY if a norm/code is explicitly named in the text.
  If none is cited, use null. Never guess or invent a reference.
- verbatim_quote: copy at most one short sentence from the source supporting the observation.
- confidence: your own 0..1 confidence that this observation is correct.
- Reports may be in English, French, or Dutch. Extract regardless of language;
  emit the controlled values in English."""

USER_TMPL = """Source file: {source_file} (page {page}, language: {language})

REPORT TEXT:
\"\"\"
{text}
\"\"\""""


def extract(source_file: str, page: int, language: str, text: str) -> ExtractionResult:
    """Call the LLM and validate. Raises ValidationError/JSONDecodeError on bad output
    so the caller can quarantine the chunk."""
    msg = _CLIENT.messages.create(
        model=_MODEL,
        max_tokens=1500,
        system=SYSTEM,
        messages=[{"role": "user", "content": USER_TMPL.format(
            source_file=source_file, page=page, language=language, text=text)}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text").strip()
    # be tolerant of stray fences even though we asked for none
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    data = json.loads(raw)
    return ExtractionResult.model_validate(data)
