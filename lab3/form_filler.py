"""
Fill the Google Form named in the payload, one response per row.

Browser-only: drives the live viewform UI inside an Amazon Bedrock AgentCore Browser
session via Playwright (over CDP) so every submit goes through the rendered form and is
captured by session replay. There is no HTTP fallback — a row that can't be driven
through the UI is reported as failed for manual follow-up. Parameterized entirely by
`FormParam`; no hardcoded form id.
"""

from __future__ import annotations

import re
import time

from bedrock_agentcore.tools.browser_client import BrowserClient
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from params import FormParam
from idempotency import reserve, release

# Question title (as shown on the form) -> canonical row key.
QUESTION = {
    "First Name": "first",
    "Last Name": "last",
    "Email ID": "emailid",
    "Phone Number": "phone",
    "Preferred Food": "food",
    "T-Shirt Size": "size",
    "Event Attendance Time": "time",
}
TEXT_FIELDS = {"first", "last", "emailid", "phone"}
RADIO_FIELDS = {"size", "time"}
CHECKBOX_FIELDS = {"food"}

OPTIONS = {
    "food": {"Vegetarian", "Non-Vegetarian", "Vegan", "Gluten-Free"},
    "size": {"XS", "S", "M", "L", "XL", "XXL"},
    "time": {"8:00 AM - 12:00 PM", "1:00 PM - 4:00 PM"},
}

STEP_PAUSE = 0.35


# ------------------------------------------------------------------ UI helpers
# Locate a question by the EXACT visible title text, then act on the control inside its
# listitem via ARIA roles. We match on the title span (get_by_text exact) rather than the
# heading's accessible name, because Google Forms folds "Required question"/"*" into the
# heading name so an exact heading match never hits.
def _item(page, title):
    return page.locator("div[role=listitem]").filter(
        has=page.get_by_text(title, exact=True)).first


def fill_text(page, title, value):
    box = _item(page, title).get_by_role("textbox").first
    box.click()
    box.fill(str(value))


def choose_radio(page, title, value):
    _item(page, title).get_by_role("radio", name=value, exact=True).click()


def choose_checkbox(page, title, values):
    item = _item(page, title)
    for v in [s.strip() for s in str(values).split(",") if s.strip()]:
        item.get_by_role("checkbox", name=v, exact=True).click()


def fill_email(page, value):
    box = page.locator("input[type=email]").first
    if box.count() == 0:                       # collect-email question titled "Email"
        box = _item(page, "Email").get_by_role("textbox").first
    box.click()
    box.fill(str(value))


def click_submit(page):
    page.get_by_role("button", name=re.compile(r"submit", re.I)).first.click()
    page.wait_for_load_state("networkidle")


def is_confirmed(page):
    if "formResponse" in page.url:
        return True
    return page.get_by_text(re.compile(r"response has been recorded", re.I)).count() > 0


def validate_options(row):
    for key, allowed in OPTIONS.items():
        val = str(row.get(key, "")).strip()
        if not val:
            continue
        vals = [s.strip() for s in val.split(",")] if key in CHECKBOX_FIELDS else [val]
        for v in vals:
            if v not in allowed:
                raise ValueError(f"{key}: '{v}' not an allowed option {sorted(allowed)}")


def fill_row_ui(page, form: FormParam, row):
    validate_options(row)
    page.goto(form.viewform_url, wait_until="domcontentloaded")
    if row.get("email"):
        fill_email(page, row["email"])
    for title, key in QUESTION.items():
        val = row.get(key, "")
        if not str(val).strip():
            continue
        if key in TEXT_FIELDS:
            fill_text(page, title, val)
        elif key in RADIO_FIELDS:
            choose_radio(page, title, val)
        elif key in CHECKBOX_FIELDS:
            choose_checkbox(page, title, val)
    click_submit(page)
    return is_confirmed(page)


# ------------------------------------------------------------------ driver
def fill_form(rows, form: FormParam, region: str = "us-east-1"):
    """Browser-only, idempotent: submit each NEW (form,email) row through the rendered
    form. Rows already recorded for this form are skipped (via='duplicate'); a row that
    fails the UI releases its reservation so it can retry next run. Returns a per-row
    result list. No HTTP fallback.
    """
    client = BrowserClient(region=region)
    client.start()  # session recording ON -> auditable replay
    results = []
    try:
        ws_url, headers = client.generate_ws_headers()
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(ws_url, headers=headers)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            for i, row in enumerate(rows):
                email = row.get("email") or row.get("emailid") or ""

                # Idempotency: skip anything already submitted for this form.
                if not reserve(form.public_id, email):
                    results.append({"row": i, "email": email, "ok": True,
                                    "via": "duplicate", "error": ""})
                    continue

                ok, err = False, ""
                try:
                    ok = fill_row_ui(page, form, row)
                    if not ok:
                        err = "ui submit not confirmed"
                except ValueError as e:            # bad option
                    err = str(e)
                except PWTimeout as e:
                    err = f"ui timeout: {e}"
                except Exception as e:             # noqa: BLE001 - record and continue
                    err = f"ui error: {e}"

                if not ok:
                    release(form.public_id, email)  # allow retry on the next run
                results.append({"row": i, "email": email,
                                "ok": ok, "via": "ui", "error": err})
                time.sleep(STEP_PAUSE)
            browser.close()
    finally:
        client.stop()
    return results
