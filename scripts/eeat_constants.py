"""
eeat_constants.py  -  Single source of truth for MeeeShop pen names & author validation.

Import this in every script that creates or updates article authors:
    from eeat_constants import PEN_NAMES, GENERIC_AUTHORS, needs_author_update

These names are NEVER changed once assigned to an article if they are valid MeeeShop pen names.
Generic authors, missing authors, or legacy placeholders like 'your-brand' get replaced with MeeeShop pen names.
"""

PEN_NAMES = [
    "Elena Vance, MeeeShop Lead Stylist",
    "Seraphina Croft, MeeeShop Fashion Editor",
    "Audrey Sterling, MeeeShop Style Director",
    "Maya Devereaux, MeeeShop Fashion Consultant",
    "Vivienne Vance, MeeeShop Senior Stylist",
    "Genevieve Thorne, MeeeShop Trend Forecaster",
]

# Author values that are considered generic and should be replaced
GENERIC_AUTHORS = [
    "editorial team", "meeeshop editorial team", "admin", "administrator",
    "meeeshop", "author", "staff", "staff writer", "writer",
]

# First-name fragments of PEN_NAMES used for fast pen-name detection
_PEN_FIRST_NAMES = [
    "elena vance", "seraphina croft", "audrey sterling",
    "maya devereaux", "vivienne vance", "genevieve thorne",
]


def is_valid_pen_name(author: str) -> bool:
    """
    Return True ONLY if this author is a valid MeeeShop pen name:
    - Must contain one of the recognized pen names
    - Must contain 'meeeshop'
    - Must NOT contain placeholders like 'your-brand' or 'your_brand'
    """
    if not author or not author.strip():
        return False
    lower = author.strip().lower()

    if "your-brand" in lower or "your_brand" in lower:
        return False

    if "meeeshop" not in lower:
        return False

    return any(fn in lower for fn in _PEN_FIRST_NAMES)


def is_generic_author(author: str) -> bool:
    """Return True if this author name is generic/blank/placeholder and should be replaced."""
    if not author or not author.strip():
        return True
    lower = author.strip().lower()
    if "your-brand" in lower or "your_brand" in lower:
        return True
    return any(g == lower for g in GENERIC_AUTHORS)


def needs_author_update(author: str) -> bool:
    """
    Return True when the author must be updated:
      - Blank / missing
      - Contains 'your-brand' or 'your_brand'
      - Missing 'meeeshop' branding in pen name
      - Exactly matches a generic name (e.g. 'Meeeshop', 'admin')
    Returns False when:
      - Already a valid MeeeShop pen name (e.g. 'Maya Devereaux, MeeeShop Fashion Consultant')
    """
    if is_valid_pen_name(author):
        return False   # valid MeeeShop pen name - keep it
    return True        # generic, missing, or has 'your-brand' - update it
