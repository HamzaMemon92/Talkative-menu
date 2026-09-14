from __future__ import annotations

from typing import Any, Protocol

from ainza_restaurant.payment.models import PaymentIntent


class PaymentProviderAdapter(Protocol):
    """Protocol for provider-independent online payment integrations (Razorpay, Cashfree, etc.)."""

    async def create_intent(self, intent: PaymentIntent) -> dict[str, Any]:
        """Create an online payment session/order with the provider."""
        ...

    def verify_webhook(
        self, raw_body: bytes, headers: dict[str, str], secret: str
    ) -> dict[str, Any]:
        """Verify the webhook signature and extract canonical event data."""
        ...
