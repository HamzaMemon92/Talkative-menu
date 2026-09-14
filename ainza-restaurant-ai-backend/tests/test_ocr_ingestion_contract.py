from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from ainza_restaurant.menu_ingestion.schemas import (
    MenuImportCategory,
    MenuImportDish,
    MenuImportDraft,
    MenuImportFieldConfidence,
    MenuImportVariant,
)
from ainza_restaurant.menu_ingestion.service import IngestionValidationError, MenuIngestionService


def test_47_import_draft_schema():
    """Verify that MenuImportDraft schema accurately represents extracted menu structure."""
    draft = MenuImportDraft(
        outlet_id=uuid4(),
        source_file_name="menu_page_1.jpg",
        source_file_type="photo",
        categories=[
            MenuImportCategory(
                name="Tandoori Starters",
                dishes=[
                    MenuImportDish(
                        name="Paneer Tikka",
                        price=Decimal("280.00"),
                        description="Cottage cheese marinated in spices",
                        confidence_scores=[
                            MenuImportFieldConfidence(field_name="name", confidence_score=0.98),
                            MenuImportFieldConfidence(field_name="price", confidence_score=0.95),
                        ],
                    ),
                    MenuImportDish(
                        name="Veg Platter",
                        variants=[
                            MenuImportVariant(
                                name="Half",
                                price=Decimal("350.00"),
                                confidence=MenuImportFieldConfidence(
                                    field_name="price", confidence_score=0.92
                                ),
                            ),
                            MenuImportVariant(
                                name="Full",
                                price=Decimal("600.00"),
                                confidence=MenuImportFieldConfidence(
                                    field_name="price", confidence_score=0.94
                                ),
                            ),
                        ],
                    ),
                ],
            )
        ],
    )

    validated = MenuIngestionService.validate_draft(draft)
    assert validated.source_file_name == "menu_page_1.jpg"
    assert len(validated.categories) == 1
    assert len(validated.categories[0].dishes) == 2
    assert validated.categories[0].dishes[0].name == "Paneer Tikka"
    assert len(validated.categories[0].dishes[1].variants) == 2


def test_48_low_confidence_field_requires_review():
    """Any field below confidence threshold (0.85) must be flagged for manual review."""
    dish_low_conf = MenuImportDish(
        name="Mystery Curry",
        price=Decimal("220.00"),
        confidence_scores=[
            MenuImportFieldConfidence(field_name="name", confidence_score=0.65),  # Low confidence
            MenuImportFieldConfidence(field_name="price", confidence_score=0.95),
        ],
    )
    draft = MenuImportDraft(
        outlet_id=uuid4(),
        source_file_name="scanned_menu.pdf",
        source_file_type="pdf",
        categories=[
            MenuImportCategory(
                name="Curries",
                dishes=[dish_low_conf],
            )
        ],
    )

    validated = MenuIngestionService.validate_draft(draft)
    assert validated.has_low_confidence_fields is True
    assert dish_low_conf.requires_review is True
    assert dish_low_conf.confidence_scores[0].requires_manual_review is True
    assert any("Low confidence (0.65)" in w for w in validated.warnings)


def test_49_duplicate_warning_structure():
    """Duplicate dish names detected during extraction produce structured duplicate warnings."""
    draft = MenuImportDraft(
        outlet_id=uuid4(),
        source_file_name="two_page_menu.pdf",
        source_file_type="pdf",
        categories=[
            MenuImportCategory(
                name="Starters",
                dishes=[
                    MenuImportDish(name="Hara Bhara Kabab", price=Decimal("240.00")),
                ],
            ),
            MenuImportCategory(
                name="Chef Specials",
                dishes=[
                    MenuImportDish(
                        name="Hara Bhara Kabab", price=Decimal("260.00")
                    ),  # Duplicate name
                ],
            ),
        ],
    )

    validated = MenuIngestionService.validate_draft(draft)
    starter_dish = validated.categories[0].dishes[0]
    special_dish = validated.categories[1].dishes[0]

    assert starter_dish.duplicate_warning is not None
    assert "Possible duplicate" in starter_dish.duplicate_warning
    assert special_dish.duplicate_warning is not None
    assert any("Possible duplicate detected" in w for w in validated.warnings)


def test_50_no_auto_publish():
    """Drafts containing low confidence or missing owner approval MUST NEVER auto-publish."""
    draft = MenuImportDraft(
        outlet_id=uuid4(),
        source_file_name="menu.jpg",
        source_file_type="photo",
        categories=[
            MenuImportCategory(
                name="Mains",
                dishes=[
                    MenuImportDish(
                        name="Dal Makhani",
                        price=Decimal("240.00"),
                        confidence_scores=[
                            MenuImportFieldConfidence(field_name="name", confidence_score=0.72),
                        ],
                    )
                ],
            )
        ],
    )

    validated = MenuIngestionService.validate_draft(draft)
    assert validated.can_publish is False

    # Attempting to ensure publishable raises IngestionValidationError
    with pytest.raises(IngestionValidationError) as exc_info:
        MenuIngestionService.ensure_publishable(validated)
    assert "explicitly reviewed and approved" in str(exc_info.value)

    # After explicit owner approval:
    approved = MenuIngestionService.approve_draft_by_owner(validated)
    assert approved.is_approved_by_owner is True
    assert approved.can_publish is True

    # Now publishing does not raise
    MenuIngestionService.ensure_publishable(approved)
