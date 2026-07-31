---
name: "event-registration-form-fill"
description: "Submit rows from the event_registration_entries Google Sheet into the Event Registration Google Form, one response per row. Use when asked to bulk-fill, populate, or submit this event registration form from the sheet."
---

# Event Registration Form — bulk fill from sheet (browser-primary)

Take each row of the **event_registration_entries** Google Sheet and record it as one
response to the **Event Registration Form** by driving the live form UI in a real
browser, one field at a time, then clicking **Submit**.

**Runtime: Amazon Bedrock AgentCore Browser + Playwright.** Each row is filled inside a
managed, isolated AgentCore Browser session (microVM per session) that Playwright
connects to over CDP. This is deliberately the *browser* path — every submission goes
through the rendered form, so **session replay** gives you an auditable recording of
each side-effecting submit, and there is no cookie/session to smuggle in from a human's
Chrome. See `scripts/fill_form_playwright.py` for the reference implementation.

**Primary = browser UI. Fallback = HTTP POST.** Google Forms also accepts a response
over a plain POST to its `formResponse` endpoint; that path is faster but bypasses the
UI. Here it is used **only as a per-row fallback** when the UI path fails (flaky render,
timeout) so a bulk run doesn't stall on one bad page. The UI is always tried first.

## Known IDs (this form)

- Form public ID (`/forms/d/e/<ID>/viewform`): `1FAIpQLScZGPkNU_nigHHQbwcYZJBaAvDrO-pL4ezXneFFA-RFhlSWyg`
- Source sheet ID: `1sx-l0SXU9StXStkVsI1BrAtuQoFy7a4pOaHAduC3vuI` (tab gid `1213611642`).
  Note the easily-confused characters: `...VsI1...` (capital I) and trailing `...C3vuI`.

## Field mapping (sheet column → form key)

| Sheet column          | Form key                | Type            | Valid options |
|-----------------------|-------------------------|-----------------|---------------|
| Email                 | `emailAddress`          | email collect   | — |
| First Name            | `entry.520551456`       | text            | — |
| Last Name             | `entry.169424613`       | text            | — |
| Email ID              | `entry.1357075434`      | text            | — |
| Phone Number          | `entry.1176306994`      | text            | — |
| Preferred Food        | `entry.1659502571`      | checkbox        | Vegetarian, Non-Vegetarian, Vegan, Gluten-Free |
| T-Shirt Size          | `entry.241215804`       | radio           | XS, S, M, L, XL, XXL |
| Event Attendance Time | `entry.529097327`       | radio           | 8:00 AM - 12:00 PM, 1:00 PM - 4:00 PM |

Email is collected by the form, so it posts as `emailAddress` (not an `entry.*` key).
Radio/checkbox values must **exactly** match an option string above — validate before
posting and fail loudly on any mismatch rather than submitting a silently-dropped answer.
If the form is ever edited, re-discover IDs from the viewform's `FB_PUBLIC_LOAD_DATA_`
(`data[1][1]`), don't trust this table blindly.

## Before submitting — confirm

Submitting is side-effecting and hard to undo. Confirm with the user:
- **Which rows** (all, or a subset). If some were already submitted, offer to skip them
  to avoid duplicate responses.
- **Real vs. test data** — flag if the emails/phones look like real people's data.

Then submit **one row as a test**, confirm success, and only then do the rest.

## Steps

1. **Read the sheet rows.** Prefer an attached/exported copy of the sheet, or read it
   with the Sheets API (server-side, read-only). Note: the modern Sheets grid is
   canvas-rendered, so scraping the page DOM returns nothing — don't read rows by
   screen-scraping. Always sanity-check the row count against what the user expects.

2. **Start an AgentCore Browser session and attach Playwright over CDP.** Credentials
   come from the AgentCore execution role — never hard-code them. The connection
   pattern (see the script) is:

```python
from bedrock_agentcore.tools.browser_client import BrowserClient
from playwright.sync_api import sync_playwright

client = BrowserClient(region="us-east-1"); client.start()
ws_url, headers = client.generate_ws_headers()
with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp(ws_url, headers=headers)
    page = (browser.contexts[0] if browser.contexts else browser.new_context()).new_page()
    # ... fill each row ...
client.stop()
```

3. **Fill the UI per row (primary path).** For each row: `page.goto(VIEWFORM_URL)`, then
   locate each question by its **visible title** (robust to `entry.*` id changes) and
   set its value by field type:
   - **text** (First/Last/Email ID/Phone) → find the question's `input`/`textarea`, `fill()`.
   - **radio** (T-Shirt Size, Attendance Time) → click `div[role=radio][aria-label="<option>"]`.
   - **checkbox** (Preferred Food) → click `div[role=checkbox][aria-label="<option>"]` once per selected option.
   - **email collected** → fill the `input[type=email]` / Email question.

   Validate every radio/checkbox value against the option strings in the mapping table
   **before** clicking, and fail the row loudly on any mismatch rather than submitting a
   dropped answer. Then click the **Submit** button and wait for the confirmation page
   ("Your response has been recorded" / a `formResponse` URL). Pace ~350 ms between rows.

4. **POST fallback (only if the UI path fails for a row).** If a row times out or the UI
   can't be driven (unusual field render, transient error), fall back to the
   `formResponse` POST for *that row only*, then continue:

```python
# entry ids: first 520551456 · last 169424613 · emailid 1357075434 · phone 1176306994
#            food 1659502571 · size 241215804 · time 529097327   (+ fvv=1, pageHistory=0)
# POST to https://docs.google.com/forms/d/e/<FORM_PUBLIC_ID>/formResponse
# success = HTTP 200 at a .../formResponse URL AND body lacks "is a required question"
```

   Treat a re-rendered viewform with a "required question" message as a failed row.

5. **Verify.** A confirmation page (UI) or a 200 at `.../formResponse` (fallback) is the
   submit signal, but confirm persistence too: open the form's Responses tab (owner
   access — the public `/e/` ID can't reach it) or the linked response sheet and
   spot-check the count and a few names. Report exactly which rows were submitted, which
   used the fallback, and which were skipped.

## Notes on the browser path

- **Audit:** keep AgentCore Browser **session recording on** so every submit is
  replayable — the point of choosing the UI path over the raw POST.
- **Throughput:** the UI path is sequential and slower than parallel POSTs; for very
  large batches, size the session timeout (default 15 min, up to 8 h) accordingly.
- **Locate by title, not by `entry.*`:** driving the UI means you match on the visible
  question text, so the skill survives `entry.*` id changes. If the form is restructured,
  re-check the question titles (and re-discover `entry.*` ids for the fallback from the
  viewform's `FB_PUBLIC_LOAD_DATA_`, `data[1][1]`).
