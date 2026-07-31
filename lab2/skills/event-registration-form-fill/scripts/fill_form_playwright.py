#!/usr/bin/env python3
"""
Skill 1 — Event Registration form fill, BROWSER-PRIMARY.

Drives the live Google Form viewform UI inside an Amazon Bedrock AgentCore Browser
session using Playwright (connected over CDP). The rendered UI is the primary path so
every submit is captured by AgentCore session replay; the formResponse HTTP POST is
used ONLY as a per-row fallback when the UI path fails, so a bulk run never stalls on
one flaky page.

Runtime: Amazon Bedrock AgentCore (Browser tool). AWS credentials come from the
AgentCore execution role — nothing secret is stored in this file.

Row shape (keys):
    email, first, last, emailid, phone, food, size, time
`food` may be a comma-separated list for the multi-select checkbox question.

NOTE: the BrowserClient import path / helper names can vary slightly by
bedrock-agentcore SDK version — confirm against the AgentCore Browser starter toolkit
for your version. The Playwright automation below is SDK-independent.
"""

import re
import time
import urllib.parse
import urllib.request

from bedrock_agentcore.tools.browser_client import BrowserClient
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --------------------------------------------------------------------------- config
REGION = "us-east-1"
FORM_PUBLIC_ID = "1FAIpQLScZGPkNU_nigHHQbwcYZJBaAvDrO-pL4ezXneFFA-RFhlSWyg"
VIEWFORM_URL = f"https://docs.google.com/forms/d/e/{FORM_PUBLIC_ID}/viewform"
FORMRESPONSE_URL = f"https://docs.google.com/forms/d/e/{FORM_PUBLIC_ID}/formResponse"

# Question title (as shown on the form)  ->  row key
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

# entry.* ids for the POST fallback only (re-discover from FB_PUBLIC_LOAD_DATA_ data[1][1])
ENTRY = {
    "first": "520551456", "last": "169424613", "emailid": "1357075434",
    "phone": "1176306994", "food": "1659502571", "size": "241215804", "time": "529097327",
}

# Allowed option strings — validated before clicking so we never submit a dropped answer
OPTIONS = {
    "food": {"Vegetarian", "Non-Vegetarian", "Vegan", "Gluten-Free"},
    "size": {"XS", "S", "M", "L", "XL", "XXL"},
    "time": {"8:00 AM - 12:00 PM", "1:00 PM - 4:00 PM"},
}

STEP_PAUSE = 0.35  # seconds between rows


# ---------------------------------------------------------------- UI helper functions
def _listitem_for(page, title):
    """The role=listitem container for a question, located by its visible heading."""
    heading = page.get_by_role("heading", name=title, exact=True)
    return heading.locator("xpath=ancestor::div[@role='listitem'][1]")


def fill_text(page, title, value):
    box = _listitem_for(page, title).locator("input[type=text], textarea").first
    box.click()
    box.fill(str(value))


def choose_radio(page, title, value):
    item = _listitem_for(page, title)
    item.locator(f'div[role=radio][aria-label="{value}"]').first.click()


def choose_checkbox(page, title, values):
    item = _listitem_for(page, title)
    for v in [s.strip() for s in str(values).split(",") if s.strip()]:
        item.locator(f'div[role=checkbox][aria-label="{v}"]').first.click()


def fill_email(page, value):
    box = page.locator("input[type=email]").first
    if box.count():
        box.fill(str(value))


def click_submit(page):
    page.get_by_role("button", name=re.compile(r"submit", re.I)).first.click()
    page.wait_for_load_state("networkidle")


def is_confirmed(page):
    if "formResponse" in page.url:
        return True
    return page.get_by_text(re.compile(r"response has been recorded", re.I)).count() > 0


def validate_options(row):
    """Fail loudly before touching the UI if a choice value isn't an allowed option."""
    for key, allowed in OPTIONS.items():
        val = str(row.get(key, "")).strip()
        if not val:
            continue
        vals = [s.strip() for s in val.split(",")] if key in CHECKBOX_FIELDS else [val]
        for v in vals:
            if v not in allowed:
                raise ValueError(f"{key}: '{v}' is not an allowed option {sorted(allowed)}")


def fill_row_ui(page, row):
    """Primary path: drive the rendered form for one row. Returns True on confirmation."""
    validate_options(row)
    page.goto(VIEWFORM_URL, wait_until="domcontentloaded")
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


# ------------------------------------------------------------------- POST fallback path
def post_fallback(row):
    """Per-row fallback only. Returns True on a clean formResponse 200."""
    pairs = [("fvv", "1"), ("pageHistory", "0")]
    if row.get("email"):
        pairs.append(("emailAddress", row["email"]))
    for key in ("first", "last", "emailid", "phone", "size", "time"):
        pairs.append((f"entry.{ENTRY[key]}", str(row.get(key, ""))))
    for v in [s.strip() for s in str(row.get("food", "")).split(",") if s.strip()]:
        pairs.append((f"entry.{ENTRY['food']}", v))  # one param per checkbox selection

    data = urllib.parse.urlencode(pairs).encode()
    req = urllib.request.Request(
        FORMRESPONSE_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8", "ignore")
        ok = resp.status == 200 and "formResponse" in resp.geturl()
        return ok and not re.search(r"is a required question|errorMessage", body, re.I)


# --------------------------------------------------------------------------- driver
def run(rows):
    """Fill every row. UI first, POST fallback per failed row. Returns a result list."""
    client = BrowserClient(region=REGION)
    client.start()  # keep session recording ON for auditable replay
    results = []
    try:
        ws_url, headers = client.generate_ws_headers()
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(ws_url, headers=headers)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            for i, row in enumerate(rows):
                via, ok, err = "ui", False, ""
                try:
                    ok = fill_row_ui(page, row)
                except ValueError as e:            # bad option — do NOT fall back, skip
                    via, err = "skipped", str(e)
                    results.append({"row": i, "email": row.get("email", ""),
                                    "ok": False, "via": via, "error": err})
                    continue
                except PWTimeout as e:
                    ok, err = False, f"ui timeout: {e}"
                if not ok:                          # UI failed -> POST fallback for this row
                    via = "post-fallback"
                    try:
                        ok = post_fallback(row)
                    except Exception as e:          # noqa: BLE001 - record and continue
                        err = f"{err}; fallback error: {e}".strip("; ")
                results.append({"row": i, "email": row.get("email", ""),
                                "ok": ok, "via": via, "error": err})
                time.sleep(STEP_PAUSE)
            browser.close()
    finally:
        client.stop()

    submitted = [r for r in results if r["ok"]]
    print(f"Submitted {len(submitted)}/{len(results)} "
          f"(UI: {sum(r['via']=='ui' for r in submitted)}, "
          f"fallback: {sum(r['via']=='post-fallback' for r in submitted)})")
    for r in results:
        if not r["ok"]:
            print(f"  ROW {r['row']} ({r['email']}): {r['via']} — {r['error']}")
    return results


if __name__ == "__main__":
    # Rows normally come from the sheet read (Step 1). Example shape:
    demo = [
        {"email": "test@example.com", "first": "Test", "last": "User",
         "emailid": "test@example.com", "phone": "9988116965",
         "food": "Vegetarian", "size": "M", "time": "8:00 AM - 12:00 PM"},
    ]
    run(demo)
