from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from ainza_restaurant.domain.enums import DietaryClassification


class MenuImportFieldConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_manual_review: bool = False
    reason: str | None = None


class MenuImportVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    price: Decimal
    confidence: MenuImportFieldConfidence | None = None


class MenuImportDish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    price: Decimal | None = None
    dietary_classification: DietaryClassification | None = None
    variants: list[MenuImportVariant] = Field(default_factory=list)
    confidence_scores: list[MenuImportFieldConfidence] = Field(default_factory=list)
    requires_review: bool = False
    duplicate_warning: str | None = None
    unresolved_fields: list[str] = Field(default_factory=list)


class MenuImportCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dishes: list[MenuImportDish] = Field(default_factory=list)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class MenuImportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID = Field(default_factory=uuid4)
    outlet_id: UUID
    source_file_name: str
    source_file_type: Literal["photo", "pdf", "image"]
    source_file_sha256: str | None = None
    categories: list[MenuImportCategory] = Field(default_factory=list)
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    has_low_confidence_fields: bool = False
    warnings: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    is_approved_by_owner: bool = False
    can_publish: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
