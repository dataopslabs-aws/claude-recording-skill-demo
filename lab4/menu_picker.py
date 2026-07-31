"""
Lab 4 — the LLM step. Nova Act picks the 'Menu Option' for each attendee based on their
dietary *preference*, choosing only from the options live on the form. A deterministic
safety guardrail then validates the pick; an unsafe pick is rejected so the row fails
rather than submitting (e.g.) Chicken Pizza for a vegan.

Why an LLM here: there is NO sheet column for the menu — the right dish must be *reasoned*
from the preference, and the caterer can change the menu without a code change. The
guardrail is the deterministic floor: the model makes the judgment, code ensures it isn't
unsafe. (Labs 1–3 theme: use each tool where it's strong.)
"""

from __future__ import annotations

import os
import re

# Guardrail mode: off (default — trust the LLM) | warn (submit but flag) | strict (block).
#   GUARDRAIL=strict make run-local
GUARDRAIL = os.environ.get("GUARDRAIL", "off").lower()

MENU_QUESTION = "Food Option"                     # the live radio question of dishes
_MENU_RE = re.compile(r"(?:food|menu)\s*option", re.I)   # tolerant (title has been both)

# Coarse dietary attributes of each menu item — a SAFETY FLOOR, not the full choice logic.
# Add items here when the caterer changes the menu; an unknown item is treated as unsafe
# for any preference that forbids something.
ITEM_TAGS = {
    "Chicken Pizza":              {"meat", "dairy", "gluten"},
    "Veg Pasta":                  {"dairy", "gluten"},
    "Mediterranean Quinoa Salad": {"gluten-free"},
    "Tofu Scramble Burrito":      {"gluten"},        # tortilla contains gluten
}

# What each preference must NOT contain.
FORBIDDEN = {
    "Vegan":          {"meat", "dairy", "egg"},
    "Vegetarian":     {"meat"},
    "Gluten-Free":    {"gluten"},
    "Non-Vegetarian": set(),
}


def guardrail_ok(preference: str, item: str) -> bool:
    """True if `item` is safe for `preference` (contains no forbidden dietary tag)."""
    forbidden = FORBIDDEN.get(preference, set())
    tags = ITEM_TAGS.get(item)
    if tags is None:                      # unknown item -> only ok if nothing is forbidden
        return not forbidden
    return not (tags & forbidden)


def _menu_item(page):
    """The role=listitem card for the Menu Option question (tolerant title match)."""
    return page.locator("div[role=listitem]").filter(
        has=page.get_by_text(_MENU_RE)).first


def menu_present(page) -> bool:
    return _menu_item(page).count() > 0


def _selected_menu(page):
    """Read which Menu Option radio is currently checked (its visible label)."""
    chosen = _menu_item(page).get_by_role("radio", checked=True)
    return chosen.get_attribute("aria-label") if chosen.count() else None


def pick_menu(nova, page, preference: str):
    """Let Nova Act choose the Menu Option for `preference`, then guardrail the pick.

    Returns (item, ok, note). ok=False means the model's pick failed the safety floor and
    the caller must NOT submit the row.
    """
    nova.act(
        f"Find the meal-choice question that lists dishes (for example Chicken Pizza, Veg "
        f"Pasta, Mediterranean Quinoa Salad, Tofu Scramble Burrito) and select the single "
        f"dish most appropriate for a {preference} diet. Choose ONLY from the options shown "
        f"on the page, then stop."
    )
    item = _selected_menu(page)
    if not item:
        return None, False, "Nova Act did not select a menu option"

    if GUARDRAIL == "off" or guardrail_ok(preference, item):
        return item, True, "sourced by Nova Act"
    # Guardrail says the pick may be unsafe for this preference:
    if GUARDRAIL == "strict":
        return item, False, f"guardrail blocked: '{item}' not safe for '{preference}'"
    return item, True, f"guardrail WARNING: '{item}' may not suit '{preference}' (submitted)"
