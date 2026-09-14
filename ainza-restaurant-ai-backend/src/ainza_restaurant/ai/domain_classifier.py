from __future__ import annotations

import re
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class CustomerDomainCategory(StrEnum):
    RESTAURANT_OPERATION = "restaurant_operation"
    RESTAURANT_CONVERSATION = "restaurant_conversation"
    OUT_OF_DOMAIN = "out_of_domain"
    ABUSE_OR_SPAM = "abuse_or_spam"


class CustomerDomainClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: CustomerDomainCategory
    confidence: float = Field(ge=0.0, le=1.0)
    redirect_message: str | None = None
    reason: str


class CustomerDomainClassifier:
    """Classifies customer utterances into domain categories to enforce product boundaries."""

    CANONICAL_REDIRECT: ClassVar[str] = (
        "I'm your restaurant assistant, so I can help with food, the menu, "
        "recommendations, your order and your bill. What are you in the mood for?"
    )

    SPAM_REDIRECT: ClassVar[str] = (
        "Please allow me a moment. How can I help you with your dining order or our menu?"
    )

    # Patterns indicating non-restaurant topics: cars, coding, crypto, politics, academic, etc.
    _OUT_OF_DOMAIN_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # Coding and technology development
        re.compile(
            r"\b(write|generate|fix|debug)\s+(python|java|javascript|c\+\+|code|script|sql|regex|html|css)\b",
            re.I,
        ),
        re.compile(
            r"\b(coding|programmer|programming|software engineer|github|"
            r"docker compose|algorithm|leetcode)\b",
            re.I,
        ),
        re.compile(r"\b(def\s+[a-zA-Z_]|function\s*\(|import\s+[a-zA-Z_]|console\.log)\b"),
        # Cars & Automotive purchasing
        re.compile(
            r"\b(which|what)\s+(car|vehicle|suv|sedan|bike|motorcycle)\s+"
            r"(should i buy|to buy|is best)\b",
            re.I,
        ),
        re.compile(
            r"\b(buy a car|electric vehicle|tesla|hyundai|maruti|toyota|mileage of)\b", re.I
        ),
        # Business & Startup advising
        re.compile(
            r"\b(which|what)\s+(business|startup|side hustle|company)\s+"
            r"(should i start|to launch)\b",
            re.I,
        ),
        re.compile(
            r"\b(how to start a business|crypto|cryptocurrency|bitcoin|"
            r"ethereum|stock market|investing in stocks)\b",
            re.I,
        ),
        # Academic, Science & General Trivia
        re.compile(
            r"\b(explain|what is)\s+"
            r"(quantum physics|relativity|calculus|black hole|string theory)\b",
            re.I,
        ),
        re.compile(r"\b(write my (essay|homework|assignment|thesis)|do my homework)\b", re.I),
        re.compile(
            r"\b(who was the president of|capital of|tell me history of|who won the 20\d\d)\b", re.I
        ),

        re.compile(r"\b(politics|election|political party|prime minister of)\b", re.I),
    ]

    # Patterns indicating valid dining small talk / conversation
    _RESTAURANT_CONVERSATION_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"\b(i'm starving|starving|so hungry|hungry|famished)\b", re.I),
        re.compile(
            r"\b(what would be nice|what's good|something light|something heavy|surprise me)\b",
            re.I,
        ),
        re.compile(
            r"\b(my friend hates|i hate|don't like|can you suggest|something better)\b", re.I
        ),
        re.compile(r"\b(that sounds heavy|sounds delicious|looks good|tasty|yummy)\b", re.I),
        re.compile(
            r"\b(hello|hi|hey|good evening|good afternoon|good morning|thanks|thank you)\b", re.I
        ),
        re.compile(
            r"\b(who are you|what can you do|how are you|are you a waiter|are you ai)\b", re.I
        ),
    ]

    # Strong restaurant operational keywords
    _RESTAURANT_OPERATION_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "menu",
            "dish",
            "dishes",
            "food",
            "order",
            "orders",
            "cart",
            "bill",
            "invoice",
            "payment",
            "pay",
            "recommend",
            "recommendation",
            "special",
            "specials",
            "offer",
            "offers",
            "price",
            "available",
            "availability",
            "veg",
            "vegetarian",
            "non-veg",
            "nonveg",
            "jain",
            "vegan",
            "spicy",
            "sweet",
            "dessert",
            "drink",
            "drinks",
            "water",
            "starter",
            "main",
            "bread",
            "roti",
            "naan",
            "rice",
            "biryani",
            "paneer",
            "chicken",
            "table",
            "session",
            "tax",
            "gst",
            "total",
            "quantity",
            "remove",
            "add",
            "checkout",
        }
    )

    def classify(self, text: str) -> CustomerDomainClassification:
        normalized = text.strip()
        if not normalized:
            return CustomerDomainClassification(
                category=CustomerDomainCategory.RESTAURANT_CONVERSATION,
                confidence=1.0,
                reason="empty_input",
            )

        # Check for abuse / spam patterns
        if len(normalized) > 1000:
            return CustomerDomainClassification(
                category=CustomerDomainCategory.ABUSE_OR_SPAM,
                confidence=0.95,
                redirect_message=self.SPAM_REDIRECT,
                reason="excessive_length",
            )

        # Check for Out of Domain triggers
        for pattern in self._OUT_OF_DOMAIN_PATTERNS:
            if pattern.search(normalized):
                # Verify that it isn't specifically combined with a strong restaurant request
                # e.g. "code" word in "discount code" or "promo code"
                lower = normalized.lower()
                if "promo code" in lower or "discount code" in lower or "coupon code" in lower:
                    continue
                return CustomerDomainClassification(
                    category=CustomerDomainCategory.OUT_OF_DOMAIN,
                    confidence=0.98,
                    redirect_message=self.CANONICAL_REDIRECT,
                    reason=f"matched_pattern_{pattern.pattern[:30]}",
                )

        # Check explicit out of domain keywords
        words = set(re.findall(r"\b[a-zA-Z]+\b", normalized.lower()))
        out_of_domain_keywords = {
            "python",
            "javascript",
            "sql",
            "coding",
            "programmer",
            "programming",
            "leetcode",
            "docker",
            "bitcoin",
            "crypto",
            "tesla",
            "car",
            "cars",
            "suv",
            "sedan",
            "startup",
            "homework",
            "physics",
            "calculus",
        }
        if words.intersection(out_of_domain_keywords) and not words.intersection(
            {"discount", "promo", "coupon"}
        ):
            return CustomerDomainClassification(
                category=CustomerDomainCategory.OUT_OF_DOMAIN,
                confidence=0.95,
                redirect_message=self.CANONICAL_REDIRECT,
                reason="out_of_domain_keywords_matched",
            )

        # Check for Restaurant Operation keywords
        if words.intersection(self._RESTAURANT_OPERATION_KEYWORDS):
            return CustomerDomainClassification(
                category=CustomerDomainCategory.RESTAURANT_OPERATION,
                confidence=0.90,
                reason="restaurant_operation_keywords_matched",
            )

        # Check for dining small talk
        for pattern in self._RESTAURANT_CONVERSATION_PATTERNS:
            if pattern.search(normalized):
                return CustomerDomainClassification(
                    category=CustomerDomainCategory.RESTAURANT_CONVERSATION,
                    confidence=0.92,
                    reason="restaurant_conversation_matched",
                )

        # Default short or casual conversational queries default to RESTAURANT_CONVERSATION
        if len(words) <= 6:
            return CustomerDomainClassification(
                category=CustomerDomainCategory.RESTAURANT_CONVERSATION,
                confidence=0.75,
                reason="short_conversational_default",
            )

        # Fallback: if words don't indicate restaurant at all and sentence is long,
        # redirect politely
        return CustomerDomainClassification(
            category=CustomerDomainCategory.OUT_OF_DOMAIN,

            confidence=0.80,
            redirect_message=self.CANONICAL_REDIRECT,
            reason="unrecognized_long_utterance_without_restaurant_context",
        )


_default_classifier: CustomerDomainClassifier | None = None


def get_customer_domain_classifier() -> CustomerDomainClassifier:
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = CustomerDomainClassifier()
    return _default_classifier
