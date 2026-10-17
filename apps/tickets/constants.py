"""
Ticket inventory caps — single source of truth for every "sold out" check.

Matchday passes (single + bundle) are pooled per division+week: both tiers
draw from the same MATCHDAY_CAP, with the bundle additionally restricted to
its own smaller BUNDLE_SUB_CAP inside that pool. League-wide passes
(season/playoff/finale) each have their own flat, independent cap.
"""

MATCHDAY_CAP = 40
BUNDLE_SUB_CAP = 10
SEASON_PASS_CAP = 20
PLAYOFF_PASS_CAP = 60
FINALE_PASS_CAP = 200

LEAGUE_WIDE_CAPS = {
    "season_pass": SEASON_PASS_CAP,
    "playoff_pass": PLAYOFF_PASS_CAP,
    "finale_pass": FINALE_PASS_CAP,
}

MIN_WEEK_NUMBER = 1
MAX_WEEK_NUMBER = 16

# Prices are set server-side only — never trust a client-supplied amount.
TIER_PRICES_CENTS = {
    "single_match": 1000,
    "supporter_bundle": 6000,
    "season_pass": 8000,
    "playoff_pass": 1500,
    "finale_pass": 2500,
}

TIER_LABELS = {
    "single_match": "Single Match Pass",
    "supporter_bundle": "Supporter Bundle",
    "season_pass": "Season Access Pass",
    "playoff_pass": "Playoff Match Pass",
    "finale_pass": "Finale Celebration Pass",
}

# Finale Celebration Pass CTA is "Coming Soon" / disabled per the client's spec —
# not sellable yet. Enforced server-side too, not just hidden on the frontend.
PURCHASABLE_TIERS = {"single_match", "supporter_bundle", "season_pass", "playoff_pass"}
MATCHDAY_TIERS = {"single_match", "supporter_bundle"}

# The Supporter Bundle's apparel item is picked from the shop's division
# catalog — mirrors the product data in tekky-futbol-nextjs/data/divisionProducts.js.
# Kept server-side too so a tampered request can't inject an arbitrary
# product name/description into the Stripe checkout page or stored order.
SUPPORTER_BUNDLE_MERCH = {
    "north": {
        "north-hoodie": {"name": "Pitch Side Hoodie", "description": "Season 01 North Drop", "product_type": "Hoodie"},
        "north-pant": {"name": "Pitch Warm-Up Trouser", "description": "Season 01 North Drop", "product_type": "Pant"},
        "north-short": {"name": "S01 Match Shorts", "description": "Season 01 North Drop", "product_type": "Short"},
        "north-tshirt": {"name": "S01 Match Jersey", "description": "Season 01 North Drop", "product_type": "Tshirt"},
    },
    "south": {
        "south-hoodie": {"name": "Pitch Side Hoodie", "description": "Season 01 South Drop", "product_type": "Hoodie"},
        "south-pant": {"name": "Pitch Warm-Up Trouser", "description": "Season 01 South Drop", "product_type": "Pant"},
        "south-short": {"name": "S01 Match Shorts", "description": "Season 01 South Drop", "product_type": "Short"},
        "south-tshirt": {"name": "S01 Match Jersey", "description": "Season 01 South Drop", "product_type": "Tshirt"},
    },
}

# Mirrors components/shop/ColorSwatches.js PRODUCT_COLORS keys — image filenames
# live at public/images/divisions/<division>/<productType>/<color>.jpg.
SUPPORTER_BUNDLE_COLORS = {
    "blue": "Blue",
    "purple": "Purple",
    "sky-blue": "Sky Blue",
    "green": "Green",
    "orange": "Orange",
}
