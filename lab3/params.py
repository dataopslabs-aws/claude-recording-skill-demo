"""
The composability seam for Lab 1.

Everything that varies between runs is ONE payload: the Google Sheet to read and the
Google Form to fill. EventBridge delivers this JSON as the runtime input; changing the
schedule's payload retargets the whole pipeline with no code change.

    {
      "sheet": { "id": "<sheetId>", "gid": "<tabGid>" },
      "form":  { "public_id": "<formPublicId>" },
      "region": "us-east-1"          # optional, defaults to us-east-1
    }
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SheetParam:
    id: str
    gid: str = "0"

    @property
    def csv_url(self) -> str:
        # Full CSV export — returns ALL rows. (Do NOT use the gviz endpoint: it stops at
        # the first blank row and silently drops everything below a gap in the sheet.)
        # For a PRIVATE sheet, read via the Sheets API + service account (see sheet_reader).
        return (f"https://docs.google.com/spreadsheets/d/{self.id}"
                f"/export?format=csv&gid={self.gid}")


@dataclass(frozen=True)
class FormParam:
    public_id: str

    @property
    def viewform_url(self) -> str:
        return f"https://docs.google.com/forms/d/e/{self.public_id}/viewform"


@dataclass(frozen=True)
class Job:
    """A single fill run. Built from the EventBridge payload."""
    sheet: SheetParam
    form: FormParam
    region: str = "us-east-1"
    limit: int | None = None      # optional: cap rows (safety for test runs)

    @classmethod
    def from_payload(cls, p: dict) -> "Job":
        if "sheet" not in p or "form" not in p:
            raise ValueError("payload must contain 'sheet' and 'form'")
        limit = p.get("limit")
        return cls(
            sheet=SheetParam(id=p["sheet"]["id"], gid=str(p["sheet"].get("gid", "0"))),
            form=FormParam(public_id=p["form"]["public_id"]),
            region=p.get("region", "us-east-1"),
            limit=int(limit) if limit not in (None, "") else None,
        )
