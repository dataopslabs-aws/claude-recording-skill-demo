# Playwright walkthrough — `form_filler.py` in plain English

How the browser step works, side by side: **code ↔ what a human does on the form.** No LLM —
fixed selectors matched on each question's *visible label*, success confirmed by the
"response recorded" page.

---

### 1. Open the browser (attach Playwright to the AgentCore Browser)

```python
client = BrowserClient(region=region)             # ask AWS for a managed Chrome
client.start()                                     # start it (session recording ON → audit)
ws_url, headers = client.generate_ws_headers()     # signed connection to that browser
browser = pw.chromium.connect_over_cdp(ws_url, headers=headers)
page = (browser.contexts[0] or browser.new_context()).new_page()
```
🧑 *Open Chrome, get a blank tab.*

---

### 2. Find a question by its visible title

```python
def _item(page, title):
    return page.locator("div[role=listitem]").filter(
        has=page.get_by_text(title, exact=True)).first
```
🧑 *Scroll to the card labelled e.g. "First Name."* We match the label a human reads, not
brittle internal IDs — so the script survives Google changing those IDs.

---

### 3. The three field types

```python
def fill_text(page, title, value):        # First / Last / Email ID / Phone
    box = _item(page, title).get_by_role("textbox").first
    box.click(); box.fill(str(value))

def choose_radio(page, title, value):     # T-Shirt Size, Attendance Time
    _item(page, title).get_by_role("radio", name=value, exact=True).click()

def choose_checkbox(page, title, values): # Preferred Food (one or more)
    item = _item(page, title)
    for v in [s.strip() for s in str(values).split(",") if s.strip()]:
        item.get_by_role("checkbox", name=v, exact=True).click()
```
🧑 *Type into text boxes · click the radio option whose label matches · tick each named
checkbox.*

---

### 4. Fill one whole row (the full human sequence)

```python
def fill_row_ui(page, form, row):
    validate_options(row)                 # refuse bad values BEFORE touching the UI
    page.goto(form.viewform_url)          # open the form
    if row.get("email"):
        fill_email(page, row["email"])    # the collected-email field
    for title, key in QUESTION.items():   # go question by question
        val = row.get(key, "")
        if not str(val).strip(): continue # skip blanks
        if   key in TEXT_FIELDS:     fill_text(page, title, val)
        elif key in RADIO_FIELDS:    choose_radio(page, title, val)
        elif key in CHECKBOX_FIELDS: choose_checkbox(page, title, val)
    click_submit(page)                    # press Submit
    return is_confirmed(page)             # did it go through?
```
🧑 *Open form → fill every field top to bottom → press Submit.*

---

### 5. Submit and confirm it landed

```python
def click_submit(page):
    page.get_by_role("button", name=re.compile("submit", re.I)).first.click()
    page.wait_for_load_state("networkidle")

def is_confirmed(page):
    return ("formResponse" in page.url or
            page.get_by_text(re.compile("response has been recorded", re.I)).count() > 0)
```
🧑 *Click Submit, then check for the "Your response has been recorded" page.*

---

### How each row is processed (the driver)

For every sheet row, in order:

1. **Dedup check** — `reserve(form, email)` does a DynamoDB conditional write.
   Already submitted? → mark `duplicate`, skip. New? → continue.
2. **Fill + submit** via `fill_row_ui` above.
3. **On failure** — `release()` the reservation so the row retries next run; record it as
   `failed` (no silent drop, no HTTP fallback).

Result per run: `{ "submitted": N (new), "duplicates": M (skipped), "failed": [...] }`.

> **Selector rule of thumb:** always locate by the *visible question title*
> (`get_by_text(..., exact=True)`) and act via ARIA role
> (`get_by_role("textbox"/"radio"/"checkbox", name=…)`). Do **not** match the heading's
> accessible name — Google Forms folds "Required question"/"*" into it, so an exact match
> never hits.
