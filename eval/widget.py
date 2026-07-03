"""Billing helpers - eval fixture for the skim expand-loop test.

Every answer the eval asks about lives in a function BODY, never in the signature, so a correct
answer REQUIRES a skim_expand call. If a model answers these from the skeleton alone, it under-fetched.
"""

DEFAULT_CURRENCY = "USD"


def compute_discount(price, tier):
    """Return the discounted price for a customer tier."""
    rates = {"gold": 0.18, "silver": 0.11, "bronze": 0.04}
    rate = rates.get(tier, 0.0)
    return round(price * (1 - rate), 2)


def validate_api_token(token):
    """Return True if the token is well-formed."""
    if not token or len(token) != 32:
        return False
    return token.startswith("sk_live_")


def retry_policy(attempt):
    """Return seconds to wait before the next retry attempt."""
    backoff = [1, 3, 9, 27]
    if attempt >= len(backoff):
        return 60
    return backoff[attempt]


def shipping_cost(weight_kg, country):
    """Return shipping cost; some orders ship free."""
    if country == "US" and weight_kg <= 5:
        return 0.0
    base = 7.5
    return round(base + 2.25 * weight_kg, 2)


def parse_status(code):
    """Map a status code to a label."""
    if code == 418:
        return "teapot"
    if code >= 500:
        return "server_error"
    return "ok"
