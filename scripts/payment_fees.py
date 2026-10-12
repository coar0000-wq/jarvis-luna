#!/usr/bin/env python3
"""Explicit payment costs only; unproven supplemental fees are not zero costs."""
from decimal import Decimal, ROUND_HALF_UP

PAYMENT_FEE_SOURCE = "user instruction2026-10-11"
PAYMENT_FEE_RATE = 0.02
PAYMENT_FEE_FIXED_USD = 0.0
PAYMENT_FEE_NOTE = "판매 후 카드사 결제 수수료 (사용자 확인 2026-10-11) = 2%"
UNKNOWN_SUPPLEMENTAL_FEES = ("shopify_supplemental_transaction_fee", "managed_markets_fee")
PROFIT_BASIS = "modeled_after_known_costs_only_not_full_verified_profit"


def payment_fee_usd(sale_usd):
    """Charge the single known component once, rounded to cents."""
    sale = Decimal(str(sale_usd))
    if not sale.is_finite() or sale < 0:
        raise ValueError("sale_usd must be finite and nonnegative")
    return (sale * Decimal(str(PAYMENT_FEE_RATE)) + Decimal(str(PAYMENT_FEE_FIXED_USD))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def profit_flags():
    return {"unknown_fees": list(UNKNOWN_SUPPLEMENTAL_FEES), "has_unknown_fees": True,
            "profit_basis": PROFIT_BASIS, "full_profit_verified": False}


def payment_cost_basis():
    """Fresh JSON-safe metadata; UNKNOWN fees are excluded, never assumed absent."""
    return {
        "payment_fee": PAYMENT_FEE_NOTE,
        "payment_fee_rate": PAYMENT_FEE_RATE,
        "payment_fee_fixed_usd": PAYMENT_FEE_FIXED_USD,
        "payment_fee_source": PAYMENT_FEE_SOURCE,
        "payment_fee_components": [
            {"name": "card_processor_after_sale", "status": "KNOWN", "rate": PAYMENT_FEE_RATE,
             "fixed_usd": PAYMENT_FEE_FIXED_USD, "source": PAYMENT_FEE_SOURCE, "included": True},
            *[{"name": name, "status": "UNKNOWN", "rate": None, "fixed_usd": None,
               "source": None, "included": False} for name in UNKNOWN_SUPPLEMENTAL_FEES],
        ],
        **profit_flags(),
    }
