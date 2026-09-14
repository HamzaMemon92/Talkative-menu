from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.ai.context import AIActorType
from ainza_restaurant.audit.models import AuditLog
from ainza_restaurant.domain.enums import AuditActionType


class AuditService:
    """Records authoritative mutation audit logs for all owner and administrative actions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        outlet_id: UUID,
        action_type: AuditActionType,
        target_type: str,
        target_id: str,
        previous_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        actor_type: AIActorType = AIActorType.OWNER,
        actor_id: str | None = None,
        source: str = "api",
        confirmation_reference: str | None = None,
    ) -> AuditLog:
        log = AuditLog(
            outlet_id=outlet_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            previous_value=previous_value,
            new_value=new_value,
            source=source,
            confirmation_reference=confirmation_reference,
        )
        self.session.add(log)
        await self.session.flush()
        return log
