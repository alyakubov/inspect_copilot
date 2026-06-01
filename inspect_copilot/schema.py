"""Structured schema for a single defect observation.

This schema is the core intellectual contribution of the project: it
defines *what* we pull out of free-text inspection reports. Every LLM
extraction is validated against it before it is allowed into the database,
so the structured index never contains free-form garbage.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DefectType(str, Enum):
    CRACK = "crack"
    CORROSION = "corrosion"
    DAMP = "damp_infiltration"
    SPALLING = "spalling"
    DEFORMATION = "deformation"
    FIRE_NONCOMPLIANCE = "fire_safety_noncompliance"
    MATERIAL_DEGRADATION = "material_degradation"
    OTHER = "other"


class Severity(str, Enum):
    INFO = "info"          # noted, no action
    MONITOR = "monitor"    # re-inspect / watch
    REPAIR = "repair"      # remediation needed
    URGENT = "urgent"      # safety risk / act now


class Observation(BaseModel):
    """One defect observation extracted from one chunk of a report."""

    defect_type: DefectType
    building_element: str = Field(description="facade, roof, slab, beam, column, foundation, HVAC, ...")
    material: Optional[str] = Field(default=None, description="concrete, steel, masonry, timber, glass, ...")
    severity: Severity
    recommended_action: Optional[str] = None
    regulatory_reference: Optional[str] = Field(
        default=None, description="Eurocode / EN norm / national code, ONLY if explicitly cited in the text"
    )
    location_in_building: Optional[str] = None
    building_address: Optional[str] = Field(
        default=None,
        description=(
            "Identifier of the building this defect is in, copied from the source text. "
            "Prefer a postal address; fall back to a labeled name (e.g. 'Building A'). "
            "None when no clear identifier is present in the chunk. Never invented."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0, description="model self-rated extraction confidence")
    verbatim_quote: str = Field(description="<=1 short sentence from the source, for audit traceability")

    @field_validator("verbatim_quote")
    @classmethod
    def _short_quote(cls, v: str) -> str:
        # keep quotes short: traceability anchor, not reproduction
        words = v.split()
        return " ".join(words[:25]) if len(words) > 25 else v


class ExtractionResult(BaseModel):
    """What the LLM returns for a single chunk: zero or more observations."""

    observations: list[Observation] = Field(default_factory=list)
