from __future__ import annotations

from enum import StrEnum


class MenuCategoryRole(StrEnum):
    STARTER = "starter"
    MAIN = "main"
    ACCOMPANIMENT = "accompaniment"
    DESSERT = "dessert"
    DRINK = "drink"
    SNACK = "snack"
    OTHER = "other"


def category_role(name: str) -> MenuCategoryRole:
    value = name.casefold()
    if any(word in value for word in ("starter", "appetizer", "small plate")):
        return MenuCategoryRole.STARTER
    if any(word in value for word in ("main", "curry", "entree")):
        return MenuCategoryRole.MAIN
    if any(word in value for word in ("bread", "rice", "roti", "naan")):
        return MenuCategoryRole.ACCOMPANIMENT
    if any(word in value for word in ("dessert", "sweet")):
        return MenuCategoryRole.DESSERT
    if any(word in value for word in ("drink", "beverage", "juice", "chaas")):
        return MenuCategoryRole.DRINK
    if "snack" in value:
        return MenuCategoryRole.SNACK
    return MenuCategoryRole.OTHER
