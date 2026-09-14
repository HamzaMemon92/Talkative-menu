from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time

GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


class OperatingHoursError(ValueError):
    """Raised when a weekly schedule is ambiguous or overlapping."""


@dataclass(frozen=True)
class IntervalForValidation:
    weekday: int
    opens_at: time | None
    closes_at: time | None
    is_full_day: bool = False


def normalize_slug(value: str) -> str:
    """Return a stable, URL-safe slug without silently inventing a suffix."""

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    if not normalized:
        raise ValueError("slug must contain at least one letter or number")
    return normalized[:220].rstrip("-")


def time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _segments(interval: IntervalForValidation) -> list[tuple[int, int]]:
    if not 0 <= interval.weekday <= 6:
        raise OperatingHoursError("weekday must be between 0 (Monday) and 6 (Sunday)")

    day_start = interval.weekday * MINUTES_PER_DAY
    if interval.is_full_day:
        if interval.opens_at is not None or interval.closes_at is not None:
            if interval.opens_at != interval.closes_at:
                raise OperatingHoursError("full-day intervals must have matching times")
        return [(day_start, day_start + MINUTES_PER_DAY)]

    if interval.opens_at is None or interval.closes_at is None:
        raise OperatingHoursError("opens_at and closes_at are required unless is_full_day is true")
    if interval.opens_at == interval.closes_at:
        raise OperatingHoursError(
            "opens_at and closes_at must differ; set is_full_day=true for a full day"
        )

    start = day_start + time_to_minutes(interval.opens_at)
    close_minutes = time_to_minutes(interval.closes_at)
    end = day_start + close_minutes
    if end > start:
        return [(start, end)]
    return [
        (start, day_start + MINUTES_PER_DAY),
        (day_start + MINUTES_PER_DAY, end + MINUTES_PER_DAY),
    ]


def validate_weekly_intervals(intervals: Iterable[IntervalForValidation]) -> None:
    """Validate half-open weekly intervals on a circular seven-day clock."""

    indexed_segments = [
        (index, segment)
        for index, interval in enumerate(intervals)
        for segment in _segments(interval)
    ]
    for left_position, (left_index, left) in enumerate(indexed_segments):
        for right_index, right in indexed_segments[left_position + 1 :]:
            # Segments belonging to one overnight interval touch at midnight and
            # must not be compared with one another.
            if left_index == right_index:
                continue
            for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
                shifted_left = (left[0] + shift, left[1] + shift)
                if max(shifted_left[0], right[0]) < min(shifted_left[1], right[1]):
                    raise OperatingHoursError(
                        f"operating intervals {min(left_index, right_index) + 1} "
                        f"and {max(left_index, right_index) + 1} overlap"
                    )


def validate_gstin(value: str | None) -> str | None:
    """Validate GSTIN shape only; no checksum or registration lookup is performed."""

    if value is None:
        return None
    normalized = value.strip().upper()
    if not re.fullmatch(GSTIN_PATTERN, normalized):
        raise ValueError("gstin must match the 15-character GSTIN format")
    return normalized
