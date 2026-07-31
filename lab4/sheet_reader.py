"""
Read registration rows from the Google Sheet named in the payload.

Parameterized entirely by `SheetParam` — no hardcoded sheet id. Default path uses the
CSV export (works for link-viewable sheets, server-side follows the redirect fine).
For a PRIVATE sheet, swap `read_rows` for the Sheets API branch with a service-account
credential resolved from Parameter Store (see the commented stub).
"""

from __future__ import annotations

import csv
import io
import urllib.request

from params import SheetParam

# Sheet header -> canonical row key used by the form filler.
HEADER_MAP = {
    "Email": "email",
    "First Name": "first",
    "Last Name": "last",
    "Email ID": "emailid",
    "Phone Number": "phone",
    "Preferred Food": "food",
    "T-Shirt Size": "size",
    "Event Attendance Time": "time",
}


def read_rows(sheet: SheetParam) -> list[dict]:
    """Return a list of canonical-keyed row dicts from the sheet's full CSV export."""
    with urllib.request.urlopen(sheet.csv_url) as resp:
        text = resp.read().decode("utf-8", "ignore")
    # Fail loudly if the sheet isn't link-viewable: Google returns an HTML login page
    # instead of CSV, which would otherwise parse into garbage rows.
    if text.lstrip().startswith("<"):
        raise RuntimeError(
            f"Sheet {sheet.id} did not return CSV (got HTML). Make it link-viewable "
            f"('Anyone with the link' -> Viewer), or switch read_rows to the Sheets-API "
            f"service-account path.")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        row = {}
        for header, value in raw.items():
            key = HEADER_MAP.get((header or "").strip(), (header or "").strip())
            row[key] = (value or "").strip()
        rows.append(row)
    return rows


# --- Private-sheet variant (Sheets API + service account) ------------------------
# def read_rows(sheet: SheetParam) -> list[dict]:
#     import json, boto3
#     from google.oauth2.service_account import Credentials
#     from googleapiclient.discovery import build
#     sa = json.loads(boto3.client("ssm").get_parameter(
#         Name="/lab4/google/service_account", WithDecryption=True)["Parameter"]["Value"])
#     creds = Credentials.from_service_account_info(
#         sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
#     svc = build("sheets", "v4", credentials=creds)
#     grid = svc.spreadsheets().values().get(
#         spreadsheetId=sheet.id, range="A:Z").execute().get("values", [])
#     headers, *data = grid
#     keys = [HEADER_MAP.get(h.strip(), h.strip()) for h in headers]
#     return [dict(zip(keys, r + [""] * (len(keys) - len(r)))) for r in data]
