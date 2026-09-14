from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType, AIToolContext
from ainza_restaurant.ai.errors import AIToolScopeError
from ainza_restaurant.ai.models import AIToolSafetyLevel
from ainza_restaurant.ai.tools.definitions import AIToolDefinition
from ainza_restaurant.availability.schemas import AvailabilityProposalCreate
from ainza_restaurant.availability.service import AvailabilityService
from ainza_restaurant.domain.enums import (
    AvailabilityAction,
    AvailabilityDurationMode,
    AvailabilityReasonCode,
    AvailabilityTargetType,
)


class OwnerAvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool | None = None
    category_id: UUID | None = None


class OwnerCreateAvailabilityProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: AvailabilityTargetType
    target_id: UUID
    action: AvailabilityAction
    duration_mode: AvailabilityDurationMode | None = None
    requested_until: datetime | None = None
    reason_code: AvailabilityReasonCode | None = None
    reason_note: str | None = None


class OwnerProposalIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID


async def owner_get_availability(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerAvailabilityInput, payload)
    return await AvailabilityService(session).outlet_availability(
        context.outlet_id,
        available=data.available,
        category_id=data.category_id,
    )


async def owner_create_availability_proposal(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerCreateAvailabilityProposalInput, payload)
    return await AvailabilityService(session).create_proposal(
        context.outlet_id,
        AvailabilityProposalCreate(
            target_type=data.target_type,
            target_id=data.target_id,
            action=data.action,
            duration_mode=data.duration_mode,
            requested_until=data.requested_until,
            reason_code=data.reason_code,
            reason_note=data.reason_note,
        ),
    )


async def owner_get_availability_proposal(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerProposalIdInput, payload)
    proposal = await AvailabilityService(session).get_proposal(data.proposal_id)
    if proposal.outlet_id != context.outlet_id:
        raise AIToolScopeError("availability proposal does not belong to context outlet")
    return proposal


async def owner_confirm_availability_proposal(
    session: AsyncSession, context: AIToolContext, payload: BaseModel
) -> object:
    data = cast(OwnerProposalIdInput, payload)
    proposal = await AvailabilityService(session).get_proposal(data.proposal_id)
    if proposal.outlet_id != context.outlet_id:
        raise AIToolScopeError("availability proposal does not belong to context outlet")
    return await AvailabilityService(session).confirm_proposal(data.proposal_id, confirm=True)


OWNER = frozenset({AIActorType.OWNER})

OWNER_TOOLS = [
    AIToolDefinition(
        name="owner_get_availability",
        description="Return outlet-scoped availability for the server-bound owner outlet.",
        input_model=OwnerAvailabilityInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_get_availability,
    ),
    AIToolDefinition(
        name="owner_create_availability_proposal",
        description=(
            "Create an availability proposal preview for the server-bound outlet. "
            "This does not immediately change availability."
        ),
        input_model=OwnerCreateAvailabilityProposalInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.REVERSIBLE_MUTATION,
        requires_confirmation=False,
        handler=owner_create_availability_proposal,
    ),
    AIToolDefinition(
        name="owner_get_availability_proposal",
        description="Read an outlet-scoped availability proposal.",
        input_model=OwnerProposalIdInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.READ_ONLY,
        requires_confirmation=False,
        handler=owner_get_availability_proposal,
    ),
    AIToolDefinition(
        name="owner_confirm_availability_proposal",
        description=(
            "Confirm an availability proposal. Requires external human confirmation "
            "outside model-generated arguments."
        ),
        input_model=OwnerProposalIdInput,
        allowed_actor_types=OWNER,
        safety_level=AIToolSafetyLevel.CONSEQUENTIAL_MUTATION,
        requires_confirmation=True,
        handler=owner_confirm_availability_proposal,
    ),
]
