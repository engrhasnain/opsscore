"""Bulk import of sites and assets from CSV, the way clients actually export them.

Handles what real spreadsheets throw at you:
- Excel's UTF-8 byte-order mark, and Windows-1252 files from older Excel.
- Semicolon-separated files (Excel's default where the decimal mark is a comma,
  which is most of Latin America), and decimal commas in numbers ("-38,5476").
- Header spelling ("Site Code", "site_code", "SITE CODE").
- Unknown columns, which are kept as free-form attributes instead of dropped.

The import is all-or-nothing: any row error means nothing is written, and every
error is reported with its row number so the file can be fixed in one pass.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import PayloadTooLarge, ValidationFailed
from app.models import Asset, Site
from app.services import attributes as attr
from app.services import audit
from app.services import validation as v
from app.services.context import Ctx

_HEADER_CLEAN = re.compile(r"[^a-z0-9]+")


@dataclass
class RowError:
    row: int
    field: str | None
    message: str


@dataclass
class ImportResult:
    dry_run: bool
    rows: int
    created: int = 0
    updated: int = 0
    errors: list[RowError] = field(default_factory=list)


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationFailed("The file is not UTF-8 or Windows-1252 text.", code="BAD_ENCODING")


def _header(name: str) -> str:
    return _HEADER_CLEAN.sub("_", name.strip().lower()).strip("_")


def _read_rows(raw: bytes) -> tuple[list[str], list[dict[str, str]], str]:
    settings = get_settings()
    if len(raw) > settings.import_max_bytes:
        raise PayloadTooLarge(f"The file is larger than {settings.import_max_bytes} bytes.")
    text = decode(raw)
    if not text.strip():
        raise ValidationFailed("The file is empty.", code="EMPTY_FILE")
    first_line = text.lstrip().splitlines()[0]
    try:
        delimiter = csv.Sniffer().sniff(first_line, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ValidationFailed("The file is empty.", code="EMPTY_FILE") from None
    columns = [_header(h) for h in header]
    if len(set(c for c in columns if c)) != len([c for c in columns if c]):
        raise ValidationFailed("The header has duplicate column names.", code="DUPLICATE_COLUMNS")

    rows: list[dict[str, str]] = []
    for index, values in enumerate(reader, start=2):
        if not any(cell.strip() for cell in values):
            continue  # blank lines at the end of spreadsheets
        if len(rows) >= settings.import_max_rows:
            raise PayloadTooLarge(f"The file has more than {settings.import_max_rows} rows.")
        if len(values) > len(columns) and not any(cell.strip() for cell in values[len(columns) :]):
            values = values[: len(columns)]  # trailing empty cells from spreadsheet exports
        row = {"__row__": str(index)}
        if len(values) != len(columns):
            row["__shape__"] = f"expected {len(columns)} columns, found {len(values)}"
        for column, value in zip(columns, values, strict=False):
            if column:
                row[column] = value.strip()
        rows.append(row)
    if not rows:
        raise ValidationFailed("The file has a header but no rows.", code="EMPTY_FILE")
    return columns, rows, delimiter


def _number(value: str, delimiter: str) -> str:
    """'-38,5476' -> '-38.5476' when a comma is clearly the decimal mark."""
    value = value.strip().replace(" ", "")
    if value.count(",") == 1 and "." not in value:
        return value.replace(",", ".")
    if delimiter == ";" and value.count(",") == 1 and value.count(".") >= 1:
        return value.replace(".", "").replace(",", ".")  # 1.234,5
    return value


def _extras(row: dict[str, str], known: set[str]) -> dict[str, str]:
    extras = {}
    for column, value in row.items():
        if column.startswith("__") or column in known or not value:
            continue
        if attr.ATTR_NAME.match(column):
            extras[column] = value[: attr.MAX_STRING]
    return extras


def _missing(columns: list[str], required: list[str]) -> None:
    missing = [c for c in required if c not in columns]
    if missing:
        raise ValidationFailed(
            "The file is missing required columns.",
            code="MISSING_COLUMNS",
            details={"missing": missing, "found": [c for c in columns if c]},
        )


# ------------------------------------------------------------------- sites

_SITE_COLUMNS = {"code", "name", "kind", "latitude", "longitude", "timezone"}


def import_sites(session: Session, ctx: Ctx, raw: bytes, *, upsert: bool, dry_run: bool) -> ImportResult:
    columns, rows, delimiter = _read_rows(raw)
    _missing(columns, ["code", "name"])
    result = ImportResult(dry_run=dry_run, rows=len(rows))

    existing = {s.code: s for s in session.scalars(select(Site).where(Site.org_id == ctx.org_id))}
    seen: dict[str, int] = {}
    planned: list[tuple[Site | None, dict]] = []

    for row in rows:
        line = int(row["__row__"])
        if "__shape__" in row:
            result.errors.append(RowError(line, None, row["__shape__"]))
            continue
        try:
            site_code = v.code(row.get("code", ""))
            values = {
                "code": site_code,
                "name": v.text(row.get("name"), field="name", max_length=200),
                "kind": v.kind(row.get("kind") or None),
                "latitude": v.coordinate(
                    _number(row.get("latitude", ""), delimiter), field="latitude", low=-90, high=90
                ),
                "longitude": v.coordinate(
                    _number(row.get("longitude", ""), delimiter), field="longitude", low=-180, high=180
                ),
                "timezone": v.timezone(row.get("timezone") or None),
                "attributes": _extras(row, _SITE_COLUMNS),
            }
            if (values["latitude"] is None) != (values["longitude"] is None):
                raise ValidationFailed("give both latitude and longitude, or neither")
        except ValidationFailed as exc:
            field_name = exc.details.get("field") if isinstance(exc.details, dict) else None
            result.errors.append(RowError(line, field_name, exc.message))
            continue
        if site_code in seen:
            result.errors.append(RowError(line, "code", f"{site_code} also appears on row {seen[site_code]}"))
            continue
        seen[site_code] = line
        current = existing.get(site_code)
        if current is not None and not upsert:
            result.errors.append(RowError(line, "code", f"{site_code} already exists (use upsert to update)"))
            continue
        planned.append((current, values))

    if result.errors:
        return result
    for current, values in planned:
        if current is None:
            result.created += 1
            if not dry_run:
                session.add(Site(org_id=ctx.org_id, **values))
        else:
            result.updated += 1
            if not dry_run:
                for name, value in values.items():
                    setattr(current, name, value)
    if not dry_run:
        session.flush()
        audit.record(
            session,
            ctx,
            "site.imported",
            "site",
            None,
            {"rows": result.rows, "created": result.created, "updated": result.updated},
        )
    return result


# ------------------------------------------------------------------ assets

_ASSET_COLUMNS = {"code", "name", "site_code", "asset_type", "type", "criticality"}


def import_assets(session: Session, ctx: Ctx, raw: bytes, *, upsert: bool, dry_run: bool) -> ImportResult:
    columns, rows, delimiter = _read_rows(raw)
    if "asset_type" not in columns and "type" in columns:
        for row in rows:
            row["asset_type"] = row.get("type", "")
        columns = [*columns, "asset_type"]
    _missing(columns, ["code", "name", "site_code", "asset_type"])
    result = ImportResult(dry_run=dry_run, rows=len(rows))

    sites = {s.code: s for s in session.scalars(select(Site).where(Site.org_id == ctx.org_id))}
    existing = {a.code: a for a in session.scalars(select(Asset).where(Asset.org_id == ctx.org_id))}
    seen: dict[str, int] = {}
    planned: list[tuple[Asset | None, dict]] = []

    for row in rows:
        line = int(row["__row__"])
        if "__shape__" in row:
            result.errors.append(RowError(line, None, row["__shape__"]))
            continue
        try:
            asset_code = v.code(row.get("code", ""))
            site_code = v.code(row.get("site_code", ""), field="site_code")
            site = sites.get(site_code)
            if site is None:
                raise ValidationFailed(f"no site with code {site_code}", details={"field": "site_code"})
            criticality_raw = (row.get("criticality") or "3").strip()
            try:
                criticality = int(float(_number(criticality_raw, delimiter)))
            except ValueError:
                raise ValidationFailed("criticality must be 1-5", details={"field": "criticality"}) from None
            if not 1 <= criticality <= 5:
                raise ValidationFailed("criticality must be 1-5", details={"field": "criticality"})
            values = {
                "code": asset_code,
                "site_id": site.id,
                "name": v.text(row.get("name"), field="name", max_length=200),
                "asset_type": v.kind(row.get("asset_type"), default="equipment"),
                "criticality": criticality,
                "attributes": _extras(row, _ASSET_COLUMNS),
            }
        except ValidationFailed as exc:
            field_name = exc.details.get("field") if isinstance(exc.details, dict) else None
            result.errors.append(RowError(line, field_name, exc.message))
            continue
        if asset_code in seen:
            result.errors.append(RowError(line, "code", f"{asset_code} also appears on row {seen[asset_code]}"))
            continue
        seen[asset_code] = line
        current = existing.get(asset_code)
        if current is not None and not upsert:
            result.errors.append(RowError(line, "code", f"{asset_code} already exists (use upsert to update)"))
            continue
        planned.append((current, values))

    if result.errors:
        return result
    for current, values in planned:
        if current is None:
            result.created += 1
            if not dry_run:
                session.add(Asset(org_id=ctx.org_id, **values))
        else:
            result.updated += 1
            if not dry_run:
                for name, value in values.items():
                    setattr(current, name, value)
    if not dry_run:
        session.flush()
        audit.record(
            session,
            ctx,
            "asset.imported",
            "asset",
            None,
            {"rows": result.rows, "created": result.created, "updated": result.updated},
        )
    return result
