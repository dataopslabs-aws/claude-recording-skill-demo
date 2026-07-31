"""
Fill the Google Form named in the payload, one response per row — HYBRID (Lab 4).

Inside ONE Amazon Bedrock AgentCore Browser session:
  * **Deterministic Playwright** fills the fields we know (name, email, phone, size,
    time, preferred-food checkbox) using fixed selectors — same as Lab 3.
  * **Nova Act (LLM)** fills only the 'Menu Option' question, choosing the dish that fits
    each attendee's dietary preference — a judgment with no sheet column to look up.
  * A **deterministic guardrail** (menu_picker.guardrail_ok) validates the model's pick;
    an unsafe choice fails the row instead of submitting.

Nova Act owns the browser (connected to AgentCore Browser over CDP); we reuse its
Playwright `page` for the deterministic fields and `nova.act()` for the menu. No HTTP
fallback. Parameterized by `FormParam`; no hardcoded form id.
"""

from __future__ import annotations

import os
import re
import time

from bedrock_agentcore.tools.browser_client import BrowserClient
from playwright.sync_api import TimeoutError as PWTimeout
from nova_act import NovaAct
try:                                   # the AWS-IAM path wraps calls in a @workflow
    from nova_act import workflow as _nova_workflow
except Exception:                      # older/newer SDKs may expose it elsewhere
    _nova_workflow = None

from params import FormParam
from idempotency import reserve, release
from menu_picker import pick_menu, menu_present

# Nova Act auth: API key (local) if NOVA_ACT_API_KEY is set, else the AWS Service via a
# registered workflow definition (IAM — used by the deployed runtime).
NOVA_WORKFLOW = os.environ.get("NOVA_ACT_WORKFLOW", "lab4-form-fill")
NOVA_MODEL = os.environ.get("NOVA_ACT_MODEL", "nova-act-latest")

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


def _fill_known(page, form: FormParam, row):
    """Deterministic Playwright fill of every field EXCEPT the Menu Option."""
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


# ------------------------------------------------------------------ driver
def _validation_errors(page):
    """After a blocked submit, list the question titles Google flagged (role=alert text).
    Tells us exactly which required fields were left unfilled."""
    titles = []
    items = page.locator("div[role=listitem]")
    for i in range(items.count()):
        it = items.nth(i)
        alert = it.get_by_role("alert")
        if alert.count() and (alert.first.inner_text() or "").strip():
            h = it.get_by_role("heading").first
            title = (h.inner_text() if h.count() else "").strip().splitlines()
            titles.append(title[0] if title else "?")
    return titles


def _fill_session(rows, form: FormParam, ws_url, headers):
    """Open ONE Nova Act + AgentCore Browser session and fill every row; return results.
    Nova Act owns the browser (over CDP): nova.page drives the deterministic fields, and
    nova.act() (via menu_picker) drives the Menu Option judgment. Auth is set up by the
    caller (API key env for local, or the @workflow wrapper for AWS IAM)."""
    results = []
    with NovaAct(starting_page=form.viewform_url,
                 cdp_endpoint_url=ws_url, cdp_headers=headers) as nova:
        page = nova.page
        for i, row in enumerate(rows):
            email = row.get("email") or row.get("emailid") or ""

            # Idempotency: skip anything already submitted for this form.
            if not reserve(form.public_id, email):
                results.append({"row": i, "email": email, "ok": True,
                                "via": "duplicate", "menu": "", "error": ""})
                continue

            ok, err, menu = False, "", ""
            try:
                _fill_known(page, form, row)                 # deterministic (Playwright)
                pref = str(row.get("food", "")).strip()
                if menu_present(page) and pref:
                    menu, mok, note = pick_menu(nova, page, pref)  # LLM + guardrail
                    if not mok:
                        raise RuntimeError(note)             # do NOT submit an unsafe pick
                click_submit(page)
                ok = is_confirmed(page)
                if not ok:
                    ve = _validation_errors(page)
                    err = "ui submit not confirmed" + (
                        f"; required-unfilled: {ve}" if ve else "")
            except ValueError as e:            # bad deterministic option
                err = str(e)
            except PWTimeout as e:
                err = f"ui timeout: {e}"
            except Exception as e:             # noqa: BLE001 - guardrail/LLM/UI error
                err = f"{e}"

            if not ok:
                release(form.public_id, email)  # allow retry on the next run
            results.append({"row": i, "email": email, "ok": ok,
                            "via": "hybrid", "menu": menu, "error": err})
            time.sleep(STEP_PAUSE)
    return results


def fill_form(rows, form: FormParam, region: str = "us-east-1"):
    """Hybrid, idempotent fill. Selects the Nova Act auth path automatically:
      * NOVA_ACT_API_KEY set  -> API-key mode (local dev), call the session directly.
      * otherwise             -> AWS Service via IAM, wrapping the session in Nova Act's
        @workflow (needs a workflow definition named NOVA_ACT_WORKFLOW — `make nova-workflow`).
    """
    client = BrowserClient(region=region)
    client.start()  # session recording ON -> auditable replay
    try:
        ws_url, headers = client.generate_ws_headers()
        if os.environ.get("NOVA_ACT_API_KEY"):
            return _fill_session(rows, form, ws_url, headers)          # local / API key
        if _nova_workflow is None:
            raise RuntimeError(
                "No NOVA_ACT_API_KEY and the Nova Act @workflow construct is unavailable. "
                "Set NOVA_ACT_API_KEY for local runs, or upgrade nova-act and create a "
                "workflow definition (make nova-workflow) for the AWS IAM path.")
        runner = _nova_workflow(workflow_definition_name=NOVA_WORKFLOW,
                                model_id=NOVA_MODEL)(_fill_session)     # AWS IAM
        return runner(rows, form, ws_url, headers)
    finally:
        client.stop()
