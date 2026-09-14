from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ainza_restaurant.menu_ingestion.schemas import MenuImportDraft


class MenuIngestionProvider(Protocol):
    """Provider-neutral boundary for future OCR / Vision menu extraction implementations.

    Concrete implementations for PaddleOCR or Gemini Vision will implement this protocol
    in subsequent development sprints without altering domain ingestion business logic.
    """

    async def extract_menu_draft(
        self,
        *,
        outlet_id: UUID,
        file_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> MenuImportDraft:
        """Extract unstructured photo/PDF menu into normalized,
        confidence-scored MenuImportDraft.
        """
        ...
