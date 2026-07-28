---
name: "form-dynamodb-reconciliation"
description: "Validate submitted event-registration form responses and reconcile them against the AWS DynamoDB table (system of record), producing a MATCH/MISMATCH/NOT_IN_DDB report. Run AFTER event-registration-form-fill has populated the form. Use when asked to reconcile, validate, or cross-check form responses against DynamoDB."
---

# Form–DynamoDB Reconciliation

Runs **after** the `event-registration-form-fill` skill (Skill 1) has populated the
Event Registration Form from the spreadsheet. Skill 1 handles the UI/submission layer;
**this** skill is the data-layer step: it validates the submitted responses and
reconciles them against an AWS DynamoDB table treated as the **system of record**.

This skill is **read-only against DynamoDB**. It must never write, update, or delete
items. It is idempotent and safe to re-run.

---

## CONFIG — edit these to point at another form/table

```
TABLE_NAME   = "claude-skillrecording-demo"
AWS_REGION   = "us-east-1"
MATCH_KEY    = "Email"          # DynamoDB partition key (HASH). Lookup via GetItem.
                                # If MATCH_KEY is NOT the partition key, Query a GSI instead.

# Source spreadsheet that drove Skill 1
SOURCE_SHEET_ID = "1sx-l0SXU9StXStkVsI1BrAtuQoFy7a4pOaHAduC3vuI"   # event_registration_entries
SOURCE_SHEET_GID = "1213611642"

# Form whose responses we are validating
FORM_PUBLIC_ID  = "1FAIpQLScZGPkNU_nigHHQbwcYZJBaAvDrO-pL4ezXneFFA-RFhlSWyg"

# Field mapping: form field  ->  DynamoDB attribute
FIELD_MAP = {
    "Email":                 "Email",              # collected email == MATCH_KEY
    "First Name":            "First Name",
    "Last Name":             "Last Name",
    "Email ID":              "Email",              # form's Email ID text field also maps to DDB Email
    "Phone Number":          "Phone Number",       # DDB stores this as Number (N)
    "Preferred Food":        "Preferred Food",
    "T-Shirt Size":          "T-Shirt Size",
    "Event Attendance Time": "Event Attendance Time",
}

REQUIRED_FIELDS = ["Email", "First Name", "Last Name", "Phone Number",
                   "Preferred Food", "T-Shirt Size", "Event Attendance Time"]

# Format rules
FORMAT_RULES = {
    "Email":                 r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    "Phone Number":          r"^\d{10}$",
    "Preferred Food":        ["Vegetarian", "Non-Vegetarian", "Vegan", "Gluten-Free"],
    "T-Shirt Size":          ["XS", "S", "M", "L", "XL", "XXL"],
    "Event Attendance Time": ["8:00 AM - 12:00 PM", "1:00 PM - 4:00 PM"],
}
```

---

## Credentials

Use the AWS session credentials already present in this Cowork session. They are
written to `~/.aws/credentials` (`[default]`) as short-lived STS session tokens
(access key + secret + session token) and are picked up automatically by `boto3`
and the AWS API MCP server — **do not** re-enter, hard-code, print, log, or echo
them anywhere in the skill, its console output, or the report. Assume the token is
scoped **read-only** to `TABLE_NAME`; never issue a write/update/delete call.

If a credentials-related error occurs (`ExpiredToken`, `InvalidClientTokenId`,
`AccessDenied`, or missing config), **stop** and report plainly that a fresh AWS
session value is needed. Never surface any partial secret in that message.

---

## Steps

### 1. Read submitted form responses
Prefer, in this order:
1. An attached/exported `.xlsx`/`.csv` of the Form's **Responses** sheet (most
   authoritative — has a Timestamp column and the true submitted values).
2. The Form's linked response sheet, read from an authenticated Chrome tab
   (Claude-in-Chrome), same origin `docs.google.com`.
3. Fallback: the `SOURCE_SHEET_ID` rows that drove Skill 1.

Sandbox caveats (learned): the Google Sheets grid is canvas-rendered so
`get_page_text`/DOM reads return nothing, and `export?format=csv` is blocked by a
query-string / cross-origin-redirect guard. If those fail, ask the user to attach
the responses as `.xlsx` and parse with `openpyxl`. Always sanity-check the row
count against what the user expects.

### 2. Validation pass (per response)
- **Required fields present & non-empty:** all of `REQUIRED_FIELDS`.
- **Format checks** from `FORMAT_RULES`: email matches the regex; phone is 10
  digits; Preferred Food / T-Shirt Size / Event Attendance Time are one of the
  allowed option strings.
- Record every failure with a specific reason (e.g. `Phone Number: '99881' not 10
  digits`). A validation failure does not stop reconciliation for that row.

### 3. Reconciliation pass (per response)
Look up the matching DynamoDB item by `MATCH_KEY`.
- If `MATCH_KEY` is the partition key → `GetItem` (or, for efficiency on the whole
  batch, `Scan` the table **once** into an in-memory dict keyed by `MATCH_KEY` and
  look up locally — still read-only).
- If `MATCH_KEY` is not the partition key → `Query` the appropriate GSI.

For each mapped field assign a status:
- **MATCH** — normalized form value equals normalized DynamoDB value.
- **MISMATCH** — both present but differ (report both values).
- **MISSING→FILLED** — form value blank but DynamoDB has it: fill the gap from
  DynamoDB, mark `sourced from system of record`.
- **NOT_IN_DDB** — no item found for that `MATCH_KEY`.
- **MISSING_BOTH** — blank in form AND absent in DynamoDB (manual follow-up).

### 4. Normalization before comparing
- Trim leading/trailing whitespace; collapse internal runs of whitespace.
- Case-insensitive for text.
- Treat numbers/currency/dates as equal when **semantically** equal
  (e.g. DDB Phone Number `9988116965` (N) == form `"9988116965"` (S);
  `"1,000"` == `1000`; `"08:00"` == `"8:00"`).

---

## Reference implementation (sandbox Python)

Run in the workspace sandbox; `boto3` reads `~/.aws/credentials` automatically.
Read-only calls only.

```python
import re, csv, boto3
from decimal import Decimal

TABLE_NAME="claude-skillrecording-demo"; AWS_REGION="us-east-1"; MATCH_KEY="Email"
FIELD_MAP={"Email":"Email","First Name":"First Name","Last Name":"Last Name",
  "Email ID":"Email","Phone Number":"Phone Number","Preferred Food":"Preferred Food",
  "T-Shirt Size":"T-Shirt Size","Event Attendance Time":"Event Attendance Time"}
REQUIRED=["Email","First Name","Last Name","Phone Number","Preferred Food","T-Shirt Size","Event Attendance Time"]
RULES={"Email":r"^[^@\s]+@[^@\s]+\.[^@\s]+$","Phone Number":r"^\d{10}$",
  "Preferred Food":["Vegetarian","Non-Vegetarian","Vegan","Gluten-Free"],
  "T-Shirt Size":["XS","S","M","L","XL","XXL"],
  "Event Attendance Time":["8:00 AM - 12:00 PM","1:00 PM - 4:00 PM"]}

def norm(v):
    if v is None: return ""
    if isinstance(v,(int,float,Decimal)): v=format(Decimal(str(v)).normalize(),'f')
    return re.sub(r"\s+"," ",str(v)).strip().lower()

def validate(row):
    errs=[]
    for f in REQUIRED:
        if not str(row.get(f,"")).strip(): errs.append(f"{f}: missing")
    for f,rule in RULES.items():
        val=str(row.get(f,"")).strip()
        if not val: continue
        if isinstance(rule,list):
            if val not in rule: errs.append(f"{f}: '{val}' not an allowed option")
        elif not re.match(rule,val): errs.append(f"{f}: '{val}' bad format")
    return errs

def load_ddb():                       # one read-only Scan, retried with backoff by caller
    ddb=boto3.resource("dynamodb",region_name=AWS_REGION).Table(TABLE_NAME)
    items,resp={}, ddb.scan()
    for it in resp["Items"]: items[norm(it.get(MATCH_KEY))]=it
    while "LastEvaluatedKey" in resp:
        resp=ddb.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        for it in resp["Items"]: items[norm(it.get(MATCH_KEY))]=it
    return items

def reconcile(responses, ddb):
    out=[]
    for row in responses:
        key=norm(row.get(MATCH_KEY)); item=ddb.get(key)
        verrs=validate(row)
        for ff,attr in FIELD_MAP.items():
            fv=str(row.get(ff,"")).strip()
            dv="" if item is None else item.get(attr,"")
            if item is None: status="NOT_IN_DDB"; note="no DynamoDB item for "+MATCH_KEY
            elif not fv and (dv in (None,"")): status="MISSING_BOTH"; note="manual follow-up"
            elif not fv: status="MISSING→FILLED"; fv=str(dv); note="sourced from system of record"
            elif str(dv)=="" : status="MISMATCH"; note="blank in DynamoDB"
            elif norm(fv)==norm(dv): status="MATCH"; note=""
            else: status="MISMATCH"; note="differs"
            out.append({"match_key":row.get(MATCH_KEY,""),"field":ff,
                        "form_value":fv,"dynamodb_value":"" if item is None else str(item.get(attr,"")),
                        "status":status,"note":note})
        if verrs:
            out.append({"match_key":row.get(MATCH_KEY,""),"field":"_validation",
                        "form_value":"","dynamodb_value":"","status":"VALIDATION_FAIL",
                        "note":"; ".join(verrs)})
    return out
# write out -> outputs/Reconciliation_Results.csv (cols below); print summary counts.
```

Wrap the `load_ddb()` / any DynamoDB call in retry-with-backoff (below).

---

## Output

- A **reconciliation report** shown as a table AND exported to
  `outputs/Reconciliation_Results.csv` (a Google Sheet named "Reconciliation
  Results" if the user prefers), with columns:
  `match_key, field, form_value, dynamodb_value, status, note`.
- A **summary**: total responses; counts per status (MATCH / MISMATCH /
  MISSING→FILLED / NOT_IN_DDB / MISSING_BOTH / VALIDATION_FAIL / ERROR); and a
  short list of rows needing manual attention (MISMATCH, NOT_IN_DDB, MISSING_BOTH,
  validation failures).
- Never include raw credentials or full DynamoDB dumps — only the compared fields.

## Error handling

- On any DynamoDB call failure (throttling `ProvisionedThroughputExceeded`,
  `ExpiredToken`, `AccessDenied`, network): retry with exponential backoff
  (e.g. 0.5s, 1s, 2s) up to **3** times. If it still fails, record the affected
  row(s) as `ERROR` with the reason and **continue** — do not abort the run.
- If credentials are missing/expired, **stop** and report that a fresh AWS session
  value is needed, exposing no partial secret.

## Notes

- Keep it idempotent and re-runnable — it only reads DynamoDB and rewrites the
  report file.
- The CONFIG block at the top is the only thing to edit to retarget another
  form/table (change `TABLE_NAME`, `AWS_REGION`, `MATCH_KEY`, IDs, and `FIELD_MAP`).

