from __future__ import annotations

from typing import Any

from ainza_restaurant.ai.models import AIToolResult


class GroundedResponseRenderer:
    """Presents already-authoritative customer tool results without recalculating them."""

    def render(self, results: list[AIToolResult]) -> str:
        if not results:
            return "I couldn't verify that from the restaurant data right now. Please try again."
        failed = next((result for result in results if not result.ok), None)
        if failed is not None:
            return "I couldn't complete that from the restaurant data right now. Please try again."
        rendered = [self._render_result(result.tool, result.data) for result in results]
        return (
            "\n".join(text for text in rendered if text)
            or "I couldn't verify that from the restaurant data right now. Please try again."
        )

    @staticmethod
    def render_no_match(query: str | None) -> str:
        subject = query.strip() if query else "That item"
        return (
            f"{subject} isn't available on the current menu. "
            "You can browse the available categories below."
        )

    def _render_result(self, tool: str, data: Any) -> str:
        if tool == "menu_get" and isinstance(data, dict):
            return self._menu(data)
        if tool == "menu_search" and isinstance(data, list):
            return self._dish_matches(data)
        if tool == "meal_recommend" and isinstance(data, dict):
            return self._recommendation(data)
        if tool == "menu_get_dish" and isinstance(data, dict):
            return self._dish(data)
        if tool == "dish_get_availability" and isinstance(data, dict):
            return self._availability(data)
        if tool == "offers_get_effective" and isinstance(data, list):
            return self._offers(data)
        if tool in {
            "cart_get",
            "cart_add_item",
            "cart_add_items",
            "cart_update_item",
            "cart_remove_item",
            "cart_select_offer",
        } and isinstance(data, dict):
            if tool == "cart_add_items":
                return self._batch_cart(data)
            return self._cart(data)
        if tool == "orders_get_session" and isinstance(data, list):
            return self._orders(data)
        if tool == "bill_get_preview" and isinstance(data, dict):
            return self._bill(data)
        if tool == "customer_total_summary" and isinstance(data, dict):
            return self._customer_total(data)
        if tool == "menu_quote_selection" and isinstance(data, dict):
            return self._quote(data)
        if tool == "meal_recommend_revise" and isinstance(data, dict):
            return self._recommend_revise(data)
        if tool == "meal_recommend_accept" and isinstance(data, dict):
            return self._recommend_accept(data)
        if tool == "customer_payment_request" and isinstance(data, dict):
            return self._payment_request(data)
        return "I completed that using the restaurant data."

    def _menu(self, menu: dict[str, Any]) -> str:
        categories = menu.get("categories")
        if not isinstance(categories, list) or not categories:
            return "The restaurant has no customer-visible menu items right now."
        currency = str(menu.get("currency_code") or "")
        parts: list[str] = []
        for category in categories:
            if not isinstance(category, dict):
                continue
            name = str(category.get("name") or "Menu")
            dishes = category.get("dishes")
            if isinstance(dishes, list) and dishes:
                parts.append(
                    f"{name}: "
                    + ", ".join(
                        self._dish(dish, currency) for dish in dishes if isinstance(dish, dict)
                    )
                )
        return "Here is the current menu. " + " ".join(parts)

    def _dish_matches(self, dishes: list[Any]) -> str:
        matches = [self._dish(dish) for dish in dishes if isinstance(dish, dict)]
        if not matches:
            return "I couldn't find matching dishes in the current menu."
        return "I found: " + "; ".join(matches)

    def _recommendation(self, data: dict[str, Any]) -> str:
        items = data.get("items")
        if not isinstance(items, list) or not items:
            if data.get("budget_min") is not None or data.get("budget_max") is not None:
                return "I couldn't find an available meal combination within that budget."
            return "I couldn't find an available meal combination matching those preferences."
        currency = str(data.get("currency_code") or "")
        choices = [
            f"{item.get('name')} ({currency} {item.get('price')})"
            for item in items
            if isinstance(item, dict)
        ]
        total = data.get("total")
        return "Suggested combination: " + ", ".join(choices) + f". Total: {currency} {total}."

    def _dish(self, dish: dict[str, Any], default_currency: str = "") -> str:
        name = str(dish.get("name") or dish.get("dish_name") or "Menu item")
        pricing = dish.get("pricing")
        if not isinstance(pricing, dict):
            pricing = {}
        price = (
            pricing.get("effective_price")
            or pricing.get("configured_unit_price")
            or dish.get("price")
        )
        currency = pricing.get("currency_code") or dish.get("currency_code") or default_currency
        text = name
        if price is not None:
            text += f" ({currency} {price})"
        available = dish.get("available")
        if available is True:
            text += ", available"
        elif available is False:
            text += ", currently unavailable"
        dietary = dish.get("dietary_classification") or dish.get("dietary")
        if dietary:
            text += f", {dietary}"
        return text

    def _availability(self, data: dict[str, Any]) -> str:
        available = data.get("available")
        return (
            "This item is currently available."
            if available is True
            else "This item is currently unavailable."
        )

    def _offers(self, offers: list[Any]) -> str:
        names = [
            str(offer.get("name"))
            for offer in offers
            if isinstance(offer, dict) and offer.get("name")
        ]
        return "Current offers: " + ", ".join(names) if names else "There are no current offers."

    def _cart(self, cart: dict[str, Any]) -> str:
        items = cart.get("items")
        if not isinstance(items, list) or not items:
            return "Your cart is currently empty."
        names = [
            f"{item.get('quantity')} x {item.get('dish_name')}"
            for item in items
            if isinstance(item, dict)
        ]
        return "Your cart now has " + ", ".join(names) + "."

    def _batch_cart(self, data: dict[str, Any]) -> str:
        outcomes = data.get("items")
        if not isinstance(outcomes, list):
            return "Your cart was updated."
        added = [
            f"{item.get('requested_reference') or item.get('dish_id')}"
            for item in outcomes
            if isinstance(item, dict) and item.get("status") == "added"
        ]
        skipped = [
            str(item.get("requested_reference") or "an optional item")
            for item in outcomes
            if isinstance(item, dict) and item.get("status") == "skipped"
        ]
        if not added and skipped:
            return "No required items were added. " + "; ".join(skipped) + " was not available."
        text = "Added " + ", ".join(added) + " to your cart." if added else "Your cart was updated."
        if skipped:
            text += " I did not add " + ", ".join(skipped) + " because it was not available."
        return text

    def _orders(self, orders: list[Any]) -> str:
        return (
            "You have no submitted orders yet."
            if not orders
            else f"You have {len(orders)} submitted order round(s)."
        )

    def _bill(self, bill: dict[str, Any]) -> str:
        total = bill.get("total") or bill.get("subtotal_after_discount")
        currency = bill.get("currency_code") or ""
        return (
            f"Your current bill preview is {currency} {total}."
            if total is not None
            else "Your bill preview is available."
        )

    def _customer_total(self, summary: dict[str, Any]) -> str:
        state = summary.get("state")
        currency = summary.get("currency_code") or ""
        if state == "CART_ONLY":
            return f"Your current cart total is {currency} {summary['cart_total']}."
        if state == "SUBMITTED_ONLY":
            return (
                f"Your current submitted-order bill is "
                f"{currency} {summary['submitted_bill_total']}."
            )
        if state == "BOTH":
            return (
                f"Your submitted-order bill is {currency} {summary['submitted_bill_total']}. "
                f"Your current unsubmitted cart is {currency} {summary['cart_total']}. "
                "The cart items are not included in the submitted bill yet."
            )
        return "You don't have any items in your cart or submitted orders yet."

    def _quote(self, quote: dict[str, Any]) -> str:
        total = quote.get("subtotal_after_discount")
        currency = quote.get("currency_code") or ""
        return (
            f"That selection is {currency} {total}."
            if total is not None
            else "That selection has been quoted."
        )

    def _recommend_revise(self, data: dict[str, Any]) -> str:
        if "error" in data:
            return str(data.get("message") or "I couldn't revise the recommendation.")
        items = data.get("items", [])
        currency = str(data.get("currency_code") or "INR")
        total = data.get("total", "0.00")
        item_names = [
            f"{item.get('name')} ({currency} {item.get('price')})"
            for item in items
            if isinstance(item, dict)
        ]
        summary = str(data.get("summary") or "Revised recommendation")
        return f"{summary}: " + ", ".join(item_names) + f". Revised Total: {currency} {total}."

    def _recommend_accept(self, data: dict[str, Any]) -> str:
        if "error" in data:
            return str(data.get("message") or "I couldn't accept the recommendation.")
        currency = str(data.get("currency_code") or "INR")
        total = data.get("cart_total", "0.00")
        return f"Added recommended items to your cart! Current cart total: {currency} {total}."

    def _payment_request(self, data: dict[str, Any]) -> str:
        amount = data.get("amount", "0.00")
        currency = data.get("currency_code", "INR")
        mode = str(data.get("payment_mode", "ONLINE"))
        if mode in {"PAY_AT_TABLE", "PAY_AT_COUNTER"}:
            mode_label = mode.replace("_", " ").lower()
            return (
                f"Your payment request of {currency} {amount} via {mode_label} has been recorded. "
                "Our staff will assist you shortly."
            )
        checkout_url = data.get("checkout_url")
        extra = f" Checkout link: {checkout_url}" if checkout_url else ""
        return (
            f"Payment initiated for {currency} {amount}. Please scan the payment QR "
            f"or use the checkout link to complete payment.{extra}"
        )

