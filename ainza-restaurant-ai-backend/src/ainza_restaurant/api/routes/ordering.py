# ruff: noqa: B008
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ainza_restaurant.db.session import get_db_session
from ainza_restaurant.ordering.schemas import (
    CartItemCreate,
    CartItemPatch,
    CartItemRemoveRequest,
    CartOfferSelect,
    CartRead,
    CartSubmitRequest,
    OrderRead,
)
from ainza_restaurant.ordering.service import CartConflict, CartNotFound, CartService

router = APIRouter(tags=["cart and dining orders"])


def service(session: AsyncSession = Depends(get_db_session)) -> CartService:
    return CartService(session)


def _not_found(exc: CartNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})


def _conflict(exc: CartConflict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


@router.get("/api/v1/dining-sessions/{session_token}/cart", response_model=CartRead)
async def get_cart(session_token: str, cart: CartService = Depends(service)) -> CartRead:
    try:
        return await cart.get_cart(session_token)
    except CartNotFound as exc:
        raise _not_found(exc) from exc
    except CartConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/dining-sessions/{session_token}/cart/items", response_model=CartRead)
async def add_cart_item(
    session_token: str,
    payload: CartItemCreate,
    cart: CartService = Depends(service),
) -> CartRead:
    try:
        return await cart.add_item(session_token, payload)
    except CartNotFound as exc:
        raise _not_found(exc) from exc
    except CartConflict as exc:
        raise _conflict(exc) from exc


@router.patch(
    "/api/v1/dining-sessions/{session_token}/cart/items/{cart_item_id}",
    response_model=CartRead,
)
async def patch_cart_item(
    session_token: str,
    cart_item_id: UUID,
    payload: CartItemPatch,
    cart: CartService = Depends(service),
) -> CartRead:
    try:
        return await cart.patch_item(session_token, cart_item_id, payload)
    except CartNotFound as exc:
        raise _not_found(exc) from exc
    except CartConflict as exc:
        raise _conflict(exc) from exc


@router.delete(
    "/api/v1/dining-sessions/{session_token}/cart/items/{cart_item_id}",
    response_model=CartRead,
)
async def remove_cart_item(
    session_token: str,
    cart_item_id: UUID,
    payload: CartItemRemoveRequest | None = None,
    cart: CartService = Depends(service),
) -> CartRead:
    try:
        return await cart.remove_item(
            session_token,
            cart_item_id,
            expected_version=payload.expected_version if payload else None,
        )
    except CartNotFound as exc:
        raise _not_found(exc) from exc
    except CartConflict as exc:
        raise _conflict(exc) from exc


@router.put("/api/v1/dining-sessions/{session_token}/cart/offer", response_model=CartRead)
async def select_cart_offer(
    session_token: str,
    payload: CartOfferSelect,
    cart: CartService = Depends(service),
) -> CartRead:
    try:
        return await cart.select_offer(session_token, payload)
    except CartNotFound as exc:
        raise _not_found(exc) from exc
    except CartConflict as exc:
        raise _conflict(exc) from exc


@router.post("/api/v1/dining-sessions/{session_token}/cart/submit", response_model=OrderRead)
async def submit_cart(
    session_token: str,
    payload: CartSubmitRequest,
    cart: CartService = Depends(service),
) -> OrderRead:
    try:
        return await cart.submit_cart(session_token, payload)
    except CartNotFound as exc:
        raise _not_found(exc) from exc
    except CartConflict as exc:
        raise _conflict(exc) from exc


@router.get("/api/v1/dining-sessions/{session_token}/orders", response_model=list[OrderRead])
async def list_orders(
    session_token: str,
    cart: CartService = Depends(service),
) -> list[OrderRead]:
    try:
        return await cart.list_orders(session_token)
    except CartNotFound as exc:
        raise _not_found(exc) from exc
