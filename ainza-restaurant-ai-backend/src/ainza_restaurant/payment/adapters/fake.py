from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ainza_restaurant.payment.models import PaymentIntent


class FakeDeterministicPaymentAdapter:
    """Fake deterministic payment provider for unit & integration testing
    with zero external calls.
    """

    async def create_intent(self, intent: PaymentIntent) -> dict[str, Any]:
        ref = f"fake_order_{intent.id.hex[:12]}"
        qr_payload = f"ainza_pay:{intent.id}:{intent.amount}:{intent.currency_code}"
        checkout_url = f"https://pay.ainza.local/checkout/{ref}"
        return {
            "provider_reference": ref,
            "qr_payload": qr_payload,
            "checkout_url": checkout_url,
        }

    def verify_webhook(
        self, raw_body: bytes, headers: dict[str, str], secret: Any
    ) -> dict[str, Any]:
        signature = headers.get("X-Ainza-Signature") or headers.get("x-ainza-signature")
        if not signature:
            raise ValueError("missing_signature")

        secret_str = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        )
        expected = hmac.new(secret_str.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad_signature")

        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid_payload")
        return payload

    @staticmethod
    def sign_payload(payload_bytes: bytes, secret: Any) -> str:
        secret_str = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        )
        return hmac.new(secret_str.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
