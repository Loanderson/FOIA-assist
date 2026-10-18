"""Data handling levels and model-endpoint authorization.

The single most important control in a government GenAI deployment: content
never reaches a model endpoint that isn't authorized for its sensitivity.
Here that is enforced in code, before any request is built, and every
decision is written to the audit log.

The levels and endpoint authorizations below are EXAMPLES. Real values come
from the agency's ATO, its CUI program, and the authorization (e.g. FedRAMP
level) of each specific service. Set them in config/endpoints.json.
"""

LEVELS = ("PUBLIC", "INTERNAL", "CUI")
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}


class PolicyViolation(Exception):
    """Raised when code tries to send content above an endpoint's authorization."""


def rank(level: str) -> int:
    if level not in _RANK:
        raise ValueError(f"unknown handling level {level!r}; expected one of {LEVELS}")
    return _RANK[level]


def max_level(levels) -> str:
    levels = list(levels)
    return max(levels, key=rank) if levels else "PUBLIC"


def allowed(content_level: str, endpoint_level: str) -> bool:
    return rank(content_level) <= rank(endpoint_level)


def check(content_levels, endpoint: dict) -> None:
    """Raise unless every piece of content is within the endpoint's authorization."""
    top = max_level(content_levels)
    if not allowed(top, endpoint["authorized_level"]):
        raise PolicyViolation(
            f"{top} content cannot be sent to endpoint {endpoint['name']!r} "
            f"(authorized up to {endpoint['authorized_level']})")
