from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ainza_restaurant.ai.db_models import (
    AIMessageRole,
    AIMessageStatus,
    AIPendingConfirmationStatus,
)
from ainza_restaurant.customer_menu.schemas import CustomerDishRead


class AIConversationCreateRead(BaseModel):
    conversation_token: str
    dining_session_id: UUID
    outlet_id: UUID
    created_at: datetime


class AIMessageRead(BaseModel):
    role: AIMessageRole
    status: AIMessageStatus
    content: str
    created_at: datetime


class AIConversationRead(BaseModel):
    conversation_token: str
    dining_session_id: UUID
    outlet_id: UUID
    messages: list[AIMessageRead] = Field(default_factory=list)


class AIConversationMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("client_message_id", "message")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class AIConfirmationRequiredRead(BaseModel):
    confirmation_token: str
    action: str
    currency_code: str
    subtotal_after_discount: str
    item_count: int
    expires_at: datetime


class AINavigationAction(StrEnum):
    BROWSE_CATEGORIES = "browse_categories"
    BROWSE_CATEGORY = "browse_category"
    ADD_MORE_CURRENT_CATEGORY = "add_more_current_category"
    VIEW_CART = "view_cart"
    REVIEW_CHECKOUT = "review_checkout"


class AINavigationRead(BaseModel):
    action: AINavigationAction
    category_id: UUID | None = None


class AIDiscoveryCategoryRead(BaseModel):
    id: UUID
    name: str
    display_order: int


class AICategoryBrowseDishRead(BaseModel):
    dish: CustomerDishRead
    addable: bool


class AICategoryBrowseRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    display_order: int
    dishes: list[AICategoryBrowseDishRead] = Field(default_factory=list)


class AIDiscoveryRead(BaseModel):
    no_match: bool = False
    requested_query: str | None = None
    categories: list[AIDiscoveryCategoryRead] = Field(default_factory=list)
    category: AICategoryBrowseRead | None = None


class AIInteractionChoiceDimension(StrEnum):
    DIETARY_CLASSIFICATION = "dietary_classification"
    CATEGORY = "category"


class AIInteractionOptionRead(BaseModel):
    label: str
    semantic_value: str
    reference_id: UUID | None = None


class AIInteractionRead(BaseModel):
    question: str
    choice_dimension: AIInteractionChoiceDimension
    options: list[AIInteractionOptionRead] = Field(min_length=1, max_length=4)


class AIConversationMessageRead(BaseModel):
    assistant_message: str
    confirmation_required: AIConfirmationRequiredRead | None = None
    tools_used: list[str] = Field(default_factory=list)
    navigation: list[AINavigationRead] = Field(default_factory=list)
    discovery: AIDiscoveryRead | None = None
    interaction: AIInteractionRead | None = None


class VoiceTranscriptRead(BaseModel):
    text: str
    detected_language: str | None = None


class VoiceTranscriptionRead(BaseModel):
    transcript: VoiceTranscriptRead


class VoiceMessageRead(AIConversationMessageRead):
    transcript: VoiceTranscriptRead


class AIConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class AIConfirmationRead(BaseModel):
    assistant_message: str
    status: AIPendingConfirmationStatus
    data: dict[str, Any] | None = None
