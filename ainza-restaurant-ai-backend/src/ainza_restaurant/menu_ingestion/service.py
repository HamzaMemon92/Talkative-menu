from __future__ import annotations

from collections import Counter

from ainza_restaurant.menu_ingestion.schemas import (
    MenuImportDraft,
)


class IngestionValidationError(ValueError):
    """Raised when an invalid ingestion draft attempts publication."""

    code: str = "ingestion_validation_error"


class MenuIngestionService:
    """Validates and enforces quality and confidence boundaries on ingested menu drafts."""

    CONFIDENCE_THRESHOLD: float = 0.85

    @classmethod
    def validate_draft(
        cls,
        draft: MenuImportDraft,
        *,
        confidence_threshold: float | None = None,
    ) -> MenuImportDraft:
        threshold = confidence_threshold or cls.CONFIDENCE_THRESHOLD
        has_low_confidence = False
        all_warnings: list[str] = []
        unresolved: list[str] = []

        all_dish_names: list[str] = []

        for category in draft.categories:
            for dish in category.dishes:
                all_dish_names.append(dish.name.strip().casefold())
                dish_unresolved: list[str] = []

                if not dish.name or not dish.name.strip():
                    dish_unresolved.append("name")
                    all_warnings.append(f"Dish in category '{category.name}' is missing a name.")

                if dish.price is None and not dish.variants:
                    dish_unresolved.append("price")
                    all_warnings.append(f"Dish '{dish.name}' has no price and no variants.")

                dish.unresolved_fields = dish_unresolved
                if dish_unresolved:
                    unresolved.extend([f"{dish.name}:{f}" for f in dish_unresolved])

                # Check confidence scores
                for score in dish.confidence_scores:
                    if score.confidence_score < threshold:
                        score.requires_manual_review = True
                        has_low_confidence = True
                        dish.requires_review = True
                        all_warnings.append(
                            f"Low confidence ({score.confidence_score:.2f}) on '{dish.name}' "
                            f"field '{score.field_name}'. Manual review required."
                        )

                for variant in dish.variants:
                    if variant.confidence and variant.confidence.confidence_score < threshold:
                        variant.confidence.requires_manual_review = True
                        has_low_confidence = True
                        dish.requires_review = True
                        all_warnings.append(
                            f"Low confidence ({variant.confidence.confidence_score:.2f}) on "
                            f"variant '{variant.name}' for dish '{dish.name}'."
                        )

        # Duplicate detection
        counts = Counter(all_dish_names)
        duplicates = {name for name, count in counts.items() if count > 1}
        if duplicates:
            for category in draft.categories:
                for dish in category.dishes:
                    if dish.name.strip().casefold() in duplicates:
                        dish.duplicate_warning = (
                            f"Possible duplicate dish name '{dish.name}' found."
                        )
                        all_warnings.append(f"Possible duplicate detected: '{dish.name}'.")

        draft.has_low_confidence_fields = has_low_confidence
        draft.warnings = list(dict.fromkeys(all_warnings))  # preserve order, unique
        draft.unresolved_fields = list(dict.fromkeys(unresolved))

        # Can only publish if owner approved and all unresolved fields are resolved
        draft.can_publish = (
            draft.is_approved_by_owner
            and not draft.unresolved_fields
            and (not has_low_confidence or draft.is_approved_by_owner)
        )

        return draft

    @classmethod
    def approve_draft_by_owner(cls, draft: MenuImportDraft) -> MenuImportDraft:
        """Owner explicitly reviews and marks low-confidence draft approved."""
        draft.is_approved_by_owner = True
        return cls.validate_draft(draft)

    @classmethod
    def ensure_publishable(cls, draft: MenuImportDraft) -> None:
        """Enforces that low-confidence or unapproved drafts NEVER auto-publish."""
        if not draft.is_approved_by_owner:
            raise IngestionValidationError(
                "Ingestion draft must be explicitly reviewed and approved by owner "
                "before publishing."
            )
        if draft.unresolved_fields:
            raise IngestionValidationError(
                f"Cannot publish menu with unresolved fields: {draft.unresolved_fields}"
            )
        if draft.has_low_confidence_fields and not draft.is_approved_by_owner:
            raise IngestionValidationError(
                "Cannot auto-publish draft containing low-confidence fields."
            )
