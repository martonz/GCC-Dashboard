"""
Rule-based risk scoring.

Categories and their keyword sets are defined here.
Each item can match multiple categories.
"""
from __future__ import annotations

CATEGORIES: dict[str, list[str]] = {
    "kinetic": [
        "airstrike", "air strike", "strike", "missile", "drone", "rocket",
        "bombing", "bomb", "attack", "explosion", "blast", "warplane",
        "fighter jet", "retaliation", "killed in action", "troops",
    ],
    "shipping": [
        "strait of hormuz", "hormuz", "tanker", "ship seized", "mine",
        "blockade", "naval", "oil tanker", "cargo ship", "maritime",
        "shipping lane", "vessel", "sea attack",
    ],
    "casualties": [
        "killed", "dead", "wounded", "casualties", "civilian", "death toll",
        "fatalities", "injured", "massacre",
    ],
    "nuclear": [
        "nuclear", "enrichment", "iaea", "uranium", "centrifuge",
        "nuclear facility", "nuclear program", "weapons grade",
        "strategic", "mobilization", "state of emergency", "irgc",
    ],
    "deescalation": [
        "ceasefire", "cease-fire", "truce", "negotiations", "talks",
        "diplomacy", "deal", "agreement", "de-escalation", "withdrawal",
        "diplomatic", "peace talks",
    ],
}

# Points per category hit (raw, before normalization)
CATEGORY_WEIGHTS: dict[str, float] = {
    "kinetic": 5.0,
    "shipping": 4.0,
    "casualties": 4.0,
    "nuclear": 6.0,
    "deescalation": -3.0,
}


def classify_item(title: str, snippet: str) -> list[str]:
    """Return list of matched category names for an item."""
    text = f"{title or ''} {snippet or ''}".lower()
    matched = []
    for cat, keywords in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            matched.append(cat)
    return matched


def item_risk_score(categories: list[str]) -> float:
    """Compute a single item's contribution to the risk index."""
    return sum(CATEGORY_WEIGHTS.get(c, 0.0) for c in categories)


def compute_risk_index(
    kinetic: int,
    shipping: int,
    nuclear: int,
    casualties: int,
    deescalation: int,
) -> float:
    """
    Compute a 0–100 RiskIndex from category hit counts.
    Base formula keeps it interpretable and tunable.
    """
    raw = (
        10.0
        + 8.0 * kinetic
        + 6.0 * shipping
        + 7.0 * nuclear
        + 5.0 * casualties
        - 4.0 * deescalation
    )
    return max(0.0, min(100.0, raw))
