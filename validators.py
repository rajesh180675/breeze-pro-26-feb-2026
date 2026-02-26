"""
Input validation with Pydantic v2.
Enhanced with better error messages and comprehensive validation.
"""

from pydantic import BaseModel, field_validator, Field
from typing import Literal
from datetime import date
import app_config as C


class OrderRequest(BaseModel):
    """
    Validated order request model.
    
    Ensures all order parameters meet exchange requirements before API submission.
    """
    instrument: str
    strike: int = Field(gt=0, description="Strike price must be positive")
    option_type: Literal['CE', 'PE'] = Field(description="Call (CE) or Put (PE)")
    action: Literal['buy', 'sell'] = Field(description="Buy or Sell action")
    quantity: int = Field(gt=0, description="Quantity must be positive")
    order_type: Literal['market', 'limit'] = Field(default='market')
    price: float = Field(default=0, ge=0, description="Price for limit orders")

    @field_validator('instrument')
    @classmethod
    def validate_instrument(cls, v: str) -> str:
        """Validate instrument is supported."""
        if v not in C.INSTRUMENTS:
            available = ", ".join(C.INSTRUMENTS.keys())
            raise ValueError(
                f"Unknown instrument: {v}. "
                f"Available: {available}"
            )
        return v

    @field_validator('strike')
    @classmethod
    def validate_strike(cls, v: int, info) -> int:
        """Validate strike is valid for instrument."""
        instrument = info.data.get('instrument')
        if instrument and not C.validate_strike(instrument, v):
            cfg = C.get_instrument(instrument)
            raise ValueError(
                f"Invalid strike {v} for {instrument}. "
                f"Must be multiple of {cfg.strike_gap} "
                f"between {cfg.min_strike} and {cfg.max_strike}"
            )
        return v

    @field_validator('price')
    @classmethod
    def validate_price(cls, v: float, info) -> float:
        """Validate price is provided for limit orders."""
        if info.data.get('order_type') == 'limit' and v <= 0:
            raise ValueError(
                "Price must be greater than 0 for limit orders. "
                "Use market order if you want market price."
            )
        return v

    @field_validator('quantity')
    @classmethod
    def validate_quantity(cls, v: int, info) -> int:
        """Validate quantity aligns with lot size."""
        instrument = info.data.get('instrument')
        if instrument:
            cfg = C.get_instrument(instrument)
            if v % cfg.lot_size != 0:
                raise ValueError(
                    f"Quantity {v} must be multiple of lot size {cfg.lot_size} "
                    f"for {instrument}"
                )
            max_qty = C.MAX_LOTS_PER_ORDER * cfg.lot_size
            if v > max_qty:
                raise ValueError(
                    f"Quantity {v} exceeds maximum {max_qty} "
                    f"({C.MAX_LOTS_PER_ORDER} lots)"
                )
        return v


def validate_date_range(from_date: date, to_date: date) -> bool:
    """
    Validate date range for historical data queries.
    
    Args:
        from_date: Start date
        to_date: End date
        
    Returns:
        True if valid
        
    Raises:
        ValueError: If dates are invalid
    """
    if from_date > to_date:
        raise ValueError(
            f"From date ({from_date}) cannot be after To date ({to_date})"
        )
    
    days_diff = (to_date - from_date).days
    if days_diff > 90:
        raise ValueError(
            f"Date range of {days_diff} days exceeds maximum of 90 days. "
            f"Please use a shorter range."
        )
    
    return True


def validate_api_credentials(api_key: str, api_secret: str, session_token: str) -> bool:
    """
    Validate API credential format.
    
    Args:
        api_key: Breeze API key
        api_secret: Breeze API secret
        session_token: Daily session token
        
    Returns:
        True if valid
        
    Raises:
        ValueError: If credentials are invalid
    """
    if not api_key or len(api_key.strip()) < 10:
        raise ValueError("API Key appears invalid. Should be at least 10 characters.")
    
    if not api_secret or len(api_secret.strip()) < 10:
        raise ValueError("API Secret appears invalid. Should be at least 10 characters.")
    
    if not session_token or len(session_token.strip()) < 4:
        raise ValueError(
            "Session Token appears invalid. Should be at least 4 characters. "
            "Get a new token from ICICI Breeze portal."
        )
    
    return True

