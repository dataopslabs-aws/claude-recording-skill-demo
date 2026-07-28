---
name: "event-registration-form-fill"
description: "Submit rows from the event_registration_entries Google Sheet into the Event Registration Google Form, one response per row. Use when asked to bulk-fill, populate, or submit this event registration form from the sheet."
---

# Event Registration Form — bulk fill from sheet

Take each row of the **event_registration_entries** Google Sheet and record it as one
response to the **Event Registration Form**. Do NOT click through the live form per
row — Google Forms accepts responses over a plain HTTP POST to its `formResponse`
endpoint, so the reliable path is: read the data once, then POST one request per row.
Runs inside the user's authenticated Chrome session via the Claude-in-Chrome tools
(both Sheets and Forms share the `docs.google.com` origin, so same-origin fetches
carry the user's cookies automatically).

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

1. Open a Chrome tab (Claude-in-Chrome) and navigate to the form viewform URL.
2. Read the sheet rows. Preferred: an attached/exported copy of the sheet.
   Note: in some sandboxes the CSV export (`export?format=csv&gid=...`) is blocked —
   it uses a query string and cross-origin-redirects to `googleusercontent.com`, and
   the modern Sheets grid is canvas-rendered so DOM/`get_page_text` reads return
   nothing. If so, obtain the values another way (attached file, or the user pasting
   them) and always sanity-check the row count against what the user expects.
3. From a `docs.google.com` tab, POST one row at a time:

```js
async function submit(FORM, MAP, r){
  const p = new URLSearchParams();
  if (r.email) p.append('emailAddress', r.email);
  p.append('entry.'+MAP.first, r.first);
  p.append('entry.'+MAP.last,  r.last);
  p.append('entry.'+MAP.emailid, r.emailid);
  p.append('entry.'+MAP.phone, r.phone);
  p.append('entry.'+MAP.food,  r.food);   // checkbox: append once per selected option
  p.append('entry.'+MAP.size,  r.size);
  p.append('entry.'+MAP.time,  r.time);
  p.append('fvv','1'); p.append('pageHistory','0');
  const res = await fetch('/forms/d/e/'+FORM+'/formResponse', {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:p.toString()});
  const txt = await res.text();
  return { ok: res.status===200 && /formResponse/.test(res.url),
           validationError: /is a required question|errorMessage/i.test(txt) };
}
```

   `MAP = {first:'520551456', last:'169424613', emailid:'1357075434', phone:'1176306994',
   food:'1659502571', size:'241215804', time:'529097327'}`.
   Submit sequentially with a ~350ms pause between rows. Treat `validationError:true`
   (a re-rendered viewform with a "required question" message) as a failed row.

4. **Verify.** POST 200 at the `.../formResponse` URL is Google's success signal, but
   confirm persistence too: open the form's Responses tab (owner access needed — the
   public `/e/` ID can't reach it) and spot-check the count and a few names, or check
   the linked response destination. Report exactly which rows were submitted and which
   were skipped.

## Fallback

If POSTs are rejected (unusual field types, captcha), drive the live viewform with the
Claude-in-Chrome `form_input`/`computer` tools one field at a time, then click Submit.
This is the slow path — only when the POST path fails.

