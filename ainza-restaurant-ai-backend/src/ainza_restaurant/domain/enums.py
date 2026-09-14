from enum import StrEnum


class RestaurantStatus(StrEnum):
    """Lifecycle state of a restaurant record, independent of onboarding."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class OnboardingStatus(StrEnum):
    """The deterministic onboarding state exposed to restaurant owners."""

    DRAFT = "draft"
    READY_FOR_MENU = "ready_for_menu"


class RestaurantType(StrEnum):
    """Explicit tax-profile classification; no rate is inferred from it."""

    STANDALONE = "standalone"
    HOTEL_RESTAURANT = "hotel_restaurant"
    SPECIFIED_PREMISES = "specified_premises"
    OTHER = "other"


class HalalStatus(StrEnum):
    """Owner-declared halal status; unknown is intentionally the first state."""

    UNKNOWN = "unknown"
    HALAL = "halal"
    NOT_HALAL = "not_halal"
    PARTIAL = "partial"


class HalalPolicy(StrEnum):
    UNKNOWN = "unknown"
    ALL_NONVEG_MEAT_RESTAURANT_DECLARED_HALAL = "all_nonveg_meat_restaurant_declared_halal"
    SELECTED_ITEMS_ONLY = "selected_items_only"
    RESTAURANT_DECLARED_NOT_HALAL = "restaurant_declared_not_halal"


class HalalCertificationStatus(StrEnum):
    """Certification is separate from a halal status and is never inferred."""

    UNKNOWN = "unknown"
    RESTAURANT_CLAIMS_CERTIFIED = "restaurant_claims_certified"
    # Compatibility value; this is never platform verification.
    CERTIFIED = "certified"
    NOT_CERTIFIED = "not_certified"
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"


# Short names retained for callers that use the policy field terminology.
HalalCertification = HalalCertificationStatus
CertificationStatus = HalalCertificationStatus


class PorkPolicy(StrEnum):
    UNKNOWN = "unknown"
    YES = "yes"
    NO = "no"
    # Compatibility values from Task 002C's first naming.
    SERVED = "served"
    NOT_SERVED = "not_served"


class AlcoholPolicy(StrEnum):
    UNKNOWN = "unknown"
    YES = "yes"
    NO = "no"
    # Compatibility values from Task 002C's first naming.
    SERVED = "served"
    NOT_SERVED = "not_served"


class MenuStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AllergenStatus(StrEnum):
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    RESTAURANT_CONFIRMED = "restaurant_confirmed"
    # Legacy values retained for clients of the initial catalog API.
    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "does_not_contain"


class AvailabilityStatus(StrEnum):
    """Explicit tri-state availability; unknown is never treated as negative."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"


class ItemType(StrEnum):
    FOOD = "food"
    BEVERAGE = "beverage"


class DietaryClassification(StrEnum):
    UNKNOWN = "unknown"
    VEGETARIAN = "vegetarian"
    NON_VEGETARIAN = "non_vegetarian"
    EGGETARIAN = "eggetarian"


class HalalOverride(StrEnum):
    UNKNOWN = "unknown"
    RESTAURANT_CONFIRMED_HALAL = "restaurant_confirmed_halal"
    RESTAURANT_CONFIRMED_NOT_HALAL = "restaurant_confirmed_not_halal"
    # Compatibility values from the first catalog API.
    HALAL = "halal"
    NOT_HALAL = "not_halal"
    NOT_APPLICABLE = "not_applicable"


class SpiceLevel(StrEnum):
    UNKNOWN = "unknown"
    NONE = "none"
    MILD = "mild"
    MEDIUM = "medium"
    HOT = "hot"
    EXTRA_HOT = "extra_hot"


class DietaryStatus(StrEnum):
    UNKNOWN = "unknown"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    EGGETARIAN = "eggetarian"
    JAIN = "jain"
    NON_VEGETARIAN = "non_vegetarian"


class ProvenanceSource(StrEnum):
    MANUAL = "manual"
    MENU_IMPORT = "menu_import"
    API = "api"
    # Compatibility values from the first implementation.
    UNKNOWN = "unknown"
    OWNER_ENTERED = "owner_entered"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    # Compatibility values from the first implementation.
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ImageApprovalStatus(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BadgeCode(StrEnum):
    CHEF_RECOMMENDED = "chef_recommended"
    SIGNATURE = "signature"
    HOUSE_SPECIAL = "house_special"
    NEW = "new"


class AvailabilityProposalStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AvailabilityTargetType(StrEnum):
    DISH = "dish"
    INGREDIENT = "ingredient"


class AvailabilityAction(StrEnum):
    MARK_UNAVAILABLE = "mark_unavailable"
    RESTORE = "restore"


class AvailabilityDurationMode(StrEnum):
    UNTIL_NEXT_OPENING = "until_next_opening"
    UNTIL_TIMESTAMP = "until_timestamp"
    INDEFINITE = "indefinite"


class AvailabilityReasonCode(StrEnum):
    OUT_OF_STOCK = "out_of_stock"
    KITCHEN_ISSUE = "kitchen_issue"
    OWNER_PAUSED = "owner_paused"
    OTHER = "other"


class MerchandisingStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    DEACTIVATED = "deactivated"


class SpecialDurationMode(StrEnum):
    UNTIL_SERVICE_END = "until_service_end"
    UNTIL_TIMESTAMP = "until_timestamp"


class OfferType(StrEnum):
    PERCENTAGE = "percentage"
    FLAT = "flat"
    COMBO_FIXED_PRICE = "combo_fixed_price"


class OfferScopeType(StrEnum):
    ALL_ITEMS = "all_items"
    SELECTED_DISHES = "selected_dishes"
    SELECTED_CATEGORIES = "selected_categories"


class DiningSessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class DiningSessionStartedVia(StrEnum):
    QR = "qr"
    MANUAL = "manual"


class DiningOrderStatus(StrEnum):
    SUBMITTED = "submitted"
    IN_PREPARATION = "in_preparation"
    READY = "ready"
    SERVED = "served"


class KitchenTicketStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    SERVED = "served"


class KitchenTicketItemStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    READY = "ready"
    SERVED = "served"


class DiningInvoiceStatus(StrEnum):
    FINALIZED = "finalized"
