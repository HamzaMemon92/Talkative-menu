from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ainza_restaurant.ai.models import AIMessage
from ainza_restaurant.core.config import Settings, get_settings


@dataclass
class CostMetrics:
    model_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0
    estimated_cost_usd: Decimal = Decimal("0.000000")


@dataclass
class SessionUsageRecord:
    timestamps: list[float] = field(default_factory=list)
    last_message_hash: str | None = None
    last_message_time: float = 0.0
    total_calls: int = 0
    clarification_loops: int = 0
    metrics: CostMetrics = field(default_factory=CostMetrics)


class CostGovernor:
    """Controls model costs, request rates, spam protection, and bounds context size."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_rate_limit_per_minute: int | None = None,
        outlet_rate_limit_per_minute: int | None = None,
        spam_window_seconds: float | None = None,
        session_call_budget: int | None = None,
        outlet_daily_call_budget: int | None = None,
        input_token_cost_per_million: float | None = None,
        output_token_cost_per_million: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_rate_limit_per_minute = (
            session_rate_limit_per_minute
            if session_rate_limit_per_minute is not None
            else self.settings.ai_session_rate_limit_per_minute
        )
        self.outlet_rate_limit_per_minute = (
            outlet_rate_limit_per_minute
            if outlet_rate_limit_per_minute is not None
            else getattr(self.settings, "ai_outlet_rate_limit_per_minute", 400)
        )
        self.spam_window_seconds = (
            spam_window_seconds
            if spam_window_seconds is not None
            else self.settings.ai_spam_window_seconds
        )
        self.session_call_budget = (
            session_call_budget
            if session_call_budget is not None
            else self.settings.ai_session_call_budget
        )
        self.outlet_daily_call_budget = (
            outlet_daily_call_budget
            if outlet_daily_call_budget is not None
            else self.settings.ai_outlet_daily_call_budget
        )
        self.input_token_cost_per_million = (
            Decimal(str(input_token_cost_per_million))
            if input_token_cost_per_million is not None
            else self.settings.ai_input_cost_per_million_tokens
        )
        self.output_token_cost_per_million = (
            Decimal(str(output_token_cost_per_million))
            if output_token_cost_per_million is not None
            else self.settings.ai_output_cost_per_million_tokens
        )
        self._session_records: dict[str, SessionUsageRecord] = defaultdict(SessionUsageRecord)
        self._outlet_timestamps: dict[str, list[float]] = defaultdict(list)
        self._outlet_daily_calls: dict[str, int] = defaultdict(int)
        self._daily_reset_date: str = datetime.now(UTC).strftime("%Y-%m-%d")

    def _get_session_record(self, session_key: str) -> SessionUsageRecord:
        return self._session_records[session_key]

    def _check_daily_reset(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._outlet_daily_calls.clear()
            self._daily_reset_date = today

    def check_rate_and_spam(
        self,
        session_key: str,
        message_text: str,
        now_ts: float | None = None,
        *,
        outlet_key: str | None = None,
    ) -> tuple[bool, str | None]:
        """Verify rate limits and spam prevention for a session and outlet.

        Returns: (allowed, rejection_reason)
        """
        now = now_ts or time.time()
        record = self._get_session_record(session_key)

        # 1. Spam protection: identical message in short window
        norm_text = message_text.strip().lower()
        msg_hash = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()
        if (
            self.spam_window_seconds > 0
            and record.last_message_hash == msg_hash
            and (now - record.last_message_time) < self.spam_window_seconds
        ):
            return False, "ai_spam_detected: repeated identical message"

        # 2. Session rate limit (sliding window of 60 seconds)
        cutoff = now - 60.0
        record.timestamps = [t for t in record.timestamps if t > cutoff]
        if len(record.timestamps) >= self.session_rate_limit_per_minute:
            return False, "ai_rate_limit_exceeded: per-session limit reached"

        # 3. Outlet rate limit (sliding window of 60 seconds)
        if outlet_key:
            self._outlet_timestamps[outlet_key] = [
                t for t in self._outlet_timestamps[outlet_key] if t > cutoff
            ]
            if len(self._outlet_timestamps[outlet_key]) >= self.outlet_rate_limit_per_minute:
                return False, "ai_outlet_rate_limit_exceeded: per-outlet limit reached"

        # 4. Session call budget
        if record.total_calls >= self.session_call_budget:
            return False, "ai_session_budget_exceeded: call budget exhausted"

        # Record activity
        record.timestamps.append(now)
        if outlet_key:
            self._outlet_timestamps[outlet_key].append(now)
        record.last_message_hash = msg_hash
        record.last_message_time = now
        record.total_calls += 1

        return True, None

    def check_call_budget(
        self,
        *,
        session_id: str | None = None,
        outlet_id: str | None = None,
    ) -> tuple[bool, str | None]:
        if session_id:
            record = self._get_session_record(session_id)
            if record.total_calls >= self.session_call_budget:
                return False, "ai_session_budget_exceeded: session call budget exhausted"
        if outlet_id:
            self._check_daily_reset()
            if self._outlet_daily_calls[outlet_id] >= self.outlet_daily_call_budget:
                return False, "ai_outlet_daily_budget_exceeded: outlet daily budget exhausted"
        return True, None

    def check_outlet_budget(self, outlet_id: UUID) -> bool:
        self._check_daily_reset()
        outlet_key = str(outlet_id)
        current = self._outlet_daily_calls[outlet_key]
        if current >= self.outlet_daily_call_budget:
            return False
        self._outlet_daily_calls[outlet_key] = current + 1
        return True

    def check_clarification_loop(self, session_key: str, is_clarification: bool) -> bool:
        record = self._get_session_record(session_key)
        if is_clarification:
            record.clarification_loops += 1
            if record.clarification_loops > self.settings.ai_max_clarification_loops:
                return False
        else:
            record.clarification_loops = 0
        return True

    def bound_transcript_context(
        self,
        messages: list[AIMessage],
        max_turns: int | None = None,
        *,
        max_messages: int | None = None,
    ) -> list[AIMessage]:
        """Bound recent message history to avoid exploding context and token usage."""
        if not messages:
            return []
        if max_messages is not None:
            return messages[-max_messages:] if len(messages) > max_messages else messages
        limit = max_turns or self.settings.local_llm_context_turns
        has_system = messages[0].role == "system"
        system_msg = [messages[0]] if has_system else []
        rest = messages[1:] if has_system else messages
        max_msgs = limit * 2
        bounded_rest = rest[-max_msgs:] if len(rest) > max_msgs else rest
        return system_msg + bounded_rest

    def record_usage(
        self,
        session_key: str | None = None,
        *,
        session_id: str | None = None,
        outlet_id: str | None = None,
        model_calls: int = 1,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> CostMetrics:
        """Instrument token usage, latency, and estimated cost."""
        key = session_key or session_id or "default_session"
        record = self._get_session_record(key)
        m = record.metrics
        m.model_calls += model_calls
        record.total_calls += model_calls
        m.total_input_tokens += input_tokens
        m.total_output_tokens += output_tokens
        m.total_latency_ms += latency_ms
        if outlet_id:
            self._check_daily_reset()
            self._outlet_daily_calls[outlet_id] += model_calls

        in_cost = (
            Decimal(str(input_tokens)) / Decimal("1000000")
        ) * self.input_token_cost_per_million
        out_cost = (
            Decimal(str(output_tokens)) / Decimal("1000000")
        ) * self.output_token_cost_per_million
        m.estimated_cost_usd += in_cost + out_cost
        return m


# Global singleton instance for in-memory session rate limiting / budgeting
_DEFAULT_GOVERNOR: CostGovernor | None = None


def get_cost_governor() -> CostGovernor:
    global _DEFAULT_GOVERNOR
    if _DEFAULT_GOVERNOR is None:
        _DEFAULT_GOVERNOR = CostGovernor()
    return _DEFAULT_GOVERNOR
