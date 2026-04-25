"""
Custom validator functions for the Robust PDF Parsing System.

This module defines custom validation functions that can be referenced
in validation configuration files.
"""


def positive_number(value) -> bool:
    """
    Check if value is a positive number (> 0).
    
    Args:
        value: Value to check
        
    Returns:
        True if value is positive, False otherwise
    """
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def valid_claim_price(value) -> bool:
    """
    Check if claim price is valid (0 for non-claiming or >= 2500).
    
    Args:
        value: Claim price value
        
    Returns:
        True if value is 0 or >= 2500, False otherwise
    """
    try:
        price = int(value)
        return price == 0 or price >= 2500
    except (TypeError, ValueError):
        return False


# Registry of custom validators for use in ValidationConfig.from_json()
CUSTOM_VALIDATORS = {
    'positive_number': positive_number,
    'valid_claim_price': valid_claim_price,
}
