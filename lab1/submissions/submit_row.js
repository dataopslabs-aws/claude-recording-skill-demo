// submit_row.js — the actual submission engine used in Lab 1.
//
// This is NOT a standalone Node script: it runs inside the user's authenticated
// Google Chrome session (via the Claude-in-Chrome `javascript_tool`), from a tab
// already on `docs.google.com`. Same-origin `fetch` carries the user's cookies,
// so each POST to the Google Forms `formResponse` endpoint is authenticated
// automatically — no UI clicking, one HTTP request per row.
//
// Field IDs were discovered once from the form's embedded FB_PUBLIC_LOAD_DATA_
// config; see ../skills/event-registration-form-fill/SKILL.md for the full mapping.

const FORM = "1FAIpQLScZGPkNU_nigHHQbwcYZJBaAvDrO-pL4ezXneFFA-RFhlSWyg"; // public /forms/d/e/<ID>
const MAP = {
  first:   "520551456",
  last:    "169424613",
  emailid: "1357075434",
  phone:   "1176306994",
  food:    "1659502571",   // checkbox — append once per selected option
  size:    "241215804",    // radio
  time:    "529097327",    // radio
};

// row = {email, first, last, emailid, phone, food, size, time}
async function submit(row) {
  const p = new URLSearchParams();
  if (row.email) p.append("emailAddress", row.email); // form collects email → not an entry.*
  p.append("entry." + MAP.first,   row.first);
  p.append("entry." + MAP.last,    row.last);
  p.append("entry." + MAP.emailid, row.emailid);
  p.append("entry." + MAP.phone,   row.phone);
  p.append("entry." + MAP.food,    row.food);
  p.append("entry." + MAP.size,    row.size);
  p.append("entry." + MAP.time,    row.time);
  p.append("fvv", "1");
  p.append("pageHistory", "0");

  const res = await fetch(`/forms/d/e/${FORM}/formResponse`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: p.toString(),
  });
  const txt = await res.text();
  return {
    ok: res.status === 200 && /formResponse/.test(res.url),
    validationError: /is a required question|errorMessage/i.test(txt),
  };
}

// Drive the whole sheet: submit sequentially, ~350ms apart, one test row first.
async function submitAll(rows) {
  const out = [];
  for (const r of rows) {
    const res = await submit(r);
    out.push({ name: `${r.first} ${r.last}`, ...res });
    await new Promise((s) => setTimeout(s, 350));
  }
  return out;
}
