"""Basket order executor for multi-leg options strategies."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class BasketLeg:
    """A single leg of a basket order."""

    stock_code: str
    exchange_code: str
    product: str
    action: str
    quantity: int
    order_type: str
    price: float
    expiry_date: str
    right: str
    strike_price: int
    leg_label: str = ""


@dataclass
class BasketResult:
    """Execution result for one basket leg."""

    leg: BasketLeg
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    response: Dict = field(default_factory=dict)


class BasketOrderExecutor:
    """Places multiple option legs in sequence."""

    LEG_INTERVAL_MS = 200

    def __init__(self, client: "BreezeAPIClient", stop_on_failure: bool = True, dry_run: bool = False):
        self._client = client
        self._stop_on_failure = stop_on_failure
        self._dry_run = dry_run

    def execute(self, legs: List[BasketLeg]) -> List[BasketResult]:
        """Execute all legs and return per-leg results."""
        results: List[BasketResult] = []
        for i, leg in enumerate(legs):
            if self._dry_run:
                results.append(
                    BasketResult(
                        leg=leg,
                        success=True,
                        order_id=f"DRY_RUN_{i}",
                        message="Dry run — order not placed",
                        response={},
                    )
                )
                continue

            resp = self._client.place_order_raw(
                stock_code=leg.stock_code,
                exchange_code=leg.exchange_code,
                product=leg.product,
                action=leg.action,
                quantity=str(leg.quantity),
                order_type=leg.order_type,
                price=str(leg.price) if leg.order_type == "limit" else "",
                stoploss="0",
                validity="day",
                disclosed_quantity="0",
                expiry_date=leg.expiry_date,
                right=leg.right,
                strike_price=str(leg.strike_price),
                user_remark="Basket",
            )

            success = resp.get("success", False)
            order_id = None
            if success:
                sd = (resp.get("data", {}) or {}).get("Success")
                if isinstance(sd, list) and sd:
                    order_id = str(sd[0].get("order_id", ""))

            results.append(
                BasketResult(
                    leg=leg,
                    success=success,
                    order_id=order_id,
                    message=resp.get("message", ""),
                    response=resp,
                )
            )

            log.info(
                f"Basket leg {i + 1}/{len(legs)} {'OK' if success else 'FAILED'}: "
                f"{leg.leg_label or leg.right} {leg.strike_price} {leg.action}"
            )

            if not success and self._stop_on_failure:
                remaining = len(legs) - len(results)
                log.warning(f"Basket stopped after leg {i + 1}. {remaining} leg(s) not placed.")
                break

            if i < len(legs) - 1:
                time.sleep(self.LEG_INTERVAL_MS / 1000.0)

        return results


def render_basket_results(results: List[BasketResult], st_module=None) -> None:
    """Render basket execution results in Streamlit UI."""
    st = st_module
    if st is None:
        import streamlit as st  # type: ignore

    placed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    if failed == 0:
        st.success(f"✅ All {placed} legs placed successfully!")
    elif placed == 0:
        st.error(f"❌ All {len(results)} legs failed.")
    else:
        st.warning(
            f"⚠️ Partial execution: {placed}/{len(results)} legs placed. "
            f"{failed} failed. **Check positions and close unhedged legs manually.**"
        )

    for result in results:
        leg = result.leg
        icon = "✅" if result.success else "❌"
        label = leg.leg_label or f"{leg.right.upper()} {leg.strike_price}"
        detail = f"Order ID: {result.order_id}" if result.success else f"Error: {result.message}"
        st.caption(f"{icon} {label} | {leg.action.upper()} {leg.quantity} | {detail}")
