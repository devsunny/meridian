from __future__ import annotations

import contextlib
import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from edp_connector_sdk import ConnectorError, RawAsset

PII_PATTERNS = {
    "email": re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"),
    "phone": re.compile(r"^\+?[0-9][0-9 ()\-]{7,}$"),
    "ssn": re.compile(r"^\d{3}-?\d{2}-?\d{4}$"),
    "credit_card": re.compile(r"^(?:\d[ -]*?){13,19}$"),
    "ip_address": re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$"),
}
PII_NAMES = {
    "email": "email",
    "e_mail": "email",
    "phone": "phone",
    "mobile": "phone",
    "ssn": "ssn",
    "social_security": "ssn",
    "credit_card": "credit_card",
    "card_number": "credit_card",
    "dob": "date_of_birth",
    "date_of_birth": "date_of_birth",
    "address": "address",
    "first_name": "name",
    "last_name": "name",
    "full_name": "name",
    "salary": "financial",
    "iban": "financial",
    "passport": "government_id",
}
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}


@dataclass
class ParsedAsset:
    records: list[dict[str, Any]]
    schema: list[dict[str, Any]]
    kind: str = "table"  # table | document
    source_uri: str = ""
    media_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False

    @property
    def pii_columns(self) -> list[str]:
        return [column["name"] for column in self.schema if column.get("pii")]


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def parse_asset(raw: RawAsset, max_records: int = 200_000) -> ParsedAsset:
    filename = raw.filename or "source"
    suffix = Path(filename).suffix.lower()
    media = (raw.media_type or "").lower()
    try:
        if suffix in {".csv", ".tsv"} or "csv" in media or "tab-separated" in media:
            return _parse_delimited(raw, "\t" if suffix == ".tsv" else ",", max_records)
        if suffix in {".json"} or "application/json" in media:
            return _parse_json(raw, max_records)
        if suffix in {".jsonl", ".ndjson"} or "ndjson" in media:
            return _parse_jsonl(raw, max_records)
        if suffix in {".xlsx", ".xlsm"} or "spreadsheetml" in media:
            return _parse_xlsx(raw, max_records)
        if suffix == ".xml" or media in {"application/xml", "text/xml"} or media.endswith("+xml"):
            return _parse_xml(raw, max_records)
        if suffix == ".pdf" or "pdf" in media:
            return _parse_pdf(raw, max_records)
        if suffix == ".docx" or "wordprocessingml" in media:
            return _parse_docx(raw, max_records)
        if suffix in {".html", ".htm"} or "html" in media:
            return _parse_html(raw, max_records)
        if suffix in DOCUMENT_SUFFIXES or media.startswith("text/"):
            return _parse_text_document(raw, max_records)
    except ConnectorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(
            f"Unable to parse {filename} as {suffix or media or 'unknown'}: {exc.__class__.__name__}",
            code="parse_error",
        ) from exc
    raise ConnectorError(
        f"Unsupported file type '{suffix or media}'. Supported: CSV, JSON, JSONL, XML, XLSX, PDF, DOCX, HTML, text.",
        code="unsupported_format",
    )


def _base(raw: RawAsset, records: list[dict[str, Any]], max_records: int, **meta: Any) -> ParsedAsset:
    flat = [flatten_record(record) for record in records[:max_records]]
    schema = infer_schema(flat)
    flat = coerce_records(flat, schema)
    truncated = len(records) > max_records
    return ParsedAsset(
        records=flat,
        schema=schema,
        source_uri=raw.source_uri or raw.filename,
        media_type=raw.media_type,
        metadata={"filename": raw.filename, "rows": len(flat), **meta},
        truncated=truncated,
    )


def _parse_delimited(raw: RawAsset, delimiter: str, max_records: int) -> ParsedAsset:
    text = decode_text(raw.content).lstrip("\ufeff")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    records = []
    for row in reader:
        records.append({str(key or f"column_{index}"): value for index, (key, value) in enumerate(row.items())})
        if len(records) >= max_records + 1:
            break
    if not records:
        raise ConnectorError("CSV/TSV file contained no data rows.", code="empty_file")
    return _base(raw, records, max_records, delimiter=delimiter)


def _parse_json(raw: RawAsset, max_records: int) -> ParsedAsset:
    payload = json.loads(decode_text(raw.content))
    if isinstance(payload, list):
        records = [item if isinstance(item, dict) else {"value": item} for item in payload]
    elif isinstance(payload, dict):
        records = None
        for key in ("data", "items", "records", "results", "rows"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                records = [item if isinstance(item, dict) else {"value": item} for item in candidate]
                break
        if records is None:
            records = [payload]
    else:
        records = [{"value": payload}]
    return _base(raw, records, max_records)


def _parse_jsonl(raw: RawAsset, max_records: int) -> ParsedAsset:
    records = []
    for line in decode_text(raw.content).splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        records.append(item if isinstance(item, dict) else {"value": item})
        if len(records) >= max_records + 1:
            break
    return _base(raw, records, max_records)


def _parse_xlsx(raw: RawAsset, max_records: int) -> ParsedAsset:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(raw.content), read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration as exc:
        raise ConnectorError("Workbook is empty.", code="empty_file") from exc
    names = [str(value).strip() if value not in (None, "") else f"column_{i + 1}" for i, value in enumerate(header)]
    records = []
    for values in rows:
        record = {}
        for index, value in enumerate(values):
            key = names[index] if index < len(names) else f"column_{index + 1}"
            record[key] = _cell_value(value)
        records.append(record)
        if len(records) >= max_records + 1:
            break
    workbook.close()
    return _base(raw, records, max_records, sheet=sheet.title)


def _cell_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _parse_xml(raw: RawAsset, max_records: int) -> ParsedAsset:
    from defusedxml import ElementTree as ET

    root = ET.fromstring(raw.content)
    children = list(root)
    if not children:
        return _base(raw, [{root.tag: (root.text or "").strip()}], max_records)
    tag_counts: dict[str, int] = {}
    for child in children:
        tag_counts[child.tag] = tag_counts.get(child.tag, 0) + 1
    repeated_tag = max(tag_counts, key=tag_counts.get)
    candidates = [child for child in children if child.tag == repeated_tag]
    if len(candidates) == 1:
        nested = list(candidates[0])
        if nested:
            candidates = nested
    records = [_xml_element_to_record(element) for element in candidates[: max_records + 1]]
    return _base(raw, records, max_records, root=root.tag)


def _xml_element_to_record(element: Any, depth: int = 0) -> dict[str, Any]:
    record: dict[str, Any] = {}
    if element.attrib:
        for key, value in element.attrib.items():
            record[f"@{key}"] = value
    child_elements = list(element)
    text = (element.text or "").strip()
    if not child_elements:
        record["value"] = text
        return record
    counts: dict[str, int] = {}
    for child in child_elements:
        counts[child.tag] = counts.get(child.tag, 0) + 1
    for child in child_elements:
        key = child.tag.split("}")[-1]
        value = _xml_element_to_record(child, depth + 1)
        if list(value.keys()) == ["value"]:
            value = value["value"]
        if counts[child.tag] > 1:
            record.setdefault(key, [])
            assert isinstance(record[key], list)
            record[key].append(value)
        else:
            record[key] = value
    if text:
        record["text"] = text
    return record


def _parse_pdf(raw: RawAsset, max_records: int) -> ParsedAsset:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw.content))
    if reader.is_encrypted:
        raise ConnectorError("Encrypted PDFs require a password and are not supported yet.", code="encrypted_pdf")
    total_chunks = 0
    records: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        for _chunk_index, chunk in enumerate(chunk_text(text)):
            records.append(
                {
                    "doc_id": _document_id(raw),
                    "filename": raw.filename,
                    "page": page_number,
                    "chunk_index": total_chunks,
                    "text": chunk,
                    "source_uri": raw.source_uri,
                }
            )
            total_chunks += 1
            if len(records) >= max_records:
                break
        if len(records) >= max_records:
            break
    parsed = _base(raw, records, max_records, pages=len(reader.pages), chunks=len(records))
    parsed.kind = "document"
    return parsed


def _parse_docx(raw: RawAsset, max_records: int) -> ParsedAsset:
    import docx

    document = docx.Document(io.BytesIO(raw.content))
    blocks: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            blocks.append(paragraph.text.strip())
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))
    text = "\n\n".join(blocks)
    records = [
        {
            "doc_id": _document_id(raw),
            "filename": raw.filename,
            "page": None,
            "chunk_index": index,
            "text": chunk,
            "source_uri": raw.source_uri,
        }
        for index, chunk in enumerate(chunk_text(text))
    ][:max_records]
    parsed = _base(raw, records, max_records, chunks=len(records), paragraphs=len(document.paragraphs))
    parsed.kind = "document"
    return parsed


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _parse_html(raw: RawAsset, max_records: int) -> ParsedAsset:
    parser = _TextExtractor()
    parser.feed(decode_text(raw.content))
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    return _text_records(raw, text, max_records, kind="document")


def _parse_text_document(raw: RawAsset, max_records: int) -> ParsedAsset:
    return _text_records(raw, decode_text(raw.content).strip(), max_records, kind="document")


def _text_records(raw: RawAsset, text: str, max_records: int, kind: str) -> ParsedAsset:
    records = [
        {
            "doc_id": _document_id(raw),
            "filename": raw.filename,
            "page": None,
            "chunk_index": index,
            "text": chunk,
            "source_uri": raw.source_uri,
        }
        for index, chunk in enumerate(chunk_text(text))
    ][:max_records]
    parsed = _base(raw, records, max_records, chunks=len(records), characters=len(text))
    parsed.kind = kind
    return parsed


def _document_id(raw: RawAsset) -> str:
    import hashlib

    return hashlib.sha256((raw.source_uri + raw.filename).encode()).hexdigest()[:16]


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    if not text.strip():
        return []
    normalized = re.sub(r"[ \t]+", " ", text)
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind("\n", start + size // 2, end)
            if boundary == -1:
                boundary = normalized.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def flatten_record(record: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and depth < 4:
            flat.update(flatten_record(value, name, depth + 1))
        elif isinstance(value, list) and value and isinstance(value[0], dict) and depth < 3:
            flat[name] = json.dumps(value, default=str)
        elif isinstance(value, (datetime, date)):
            flat[name] = value.isoformat()
        else:
            flat[name] = value
    return flat


def infer_schema(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for record in records[:500]:
        for key in record:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    schema: list[dict[str, Any]] = []
    sample = records[:200]
    for key in keys:
        values = [record.get(key) for record in sample if record.get(key) not in (None, "")]
        types = {_infer_type(value) for value in values}
        if types <= {"integer"}:
            inferred = "integer"
        elif types <= {"integer", "number"}:
            inferred = "number"
        else:
            inferred = next(iter(types)) if len(types) == 1 else ("mixed" if types else "string")
        pii, pii_kind = _detect_pii(key, values)
        nullable = len(values) < len(sample)
        schema.append(
            {
                "name": key,
                "type": inferred,
                "nullable": nullable,
                "pii": pii,
                "pii_kind": pii_kind,
                "classification": "confidential" if pii else "internal",
                "description": "",
            }
        )
    return schema


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (datetime, date)):
        return "timestamp"
    if isinstance(value, str):
        stripped = value.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}([T ]|$)", stripped):
            return "timestamp"
        if stripped.lower() in {"true", "false"}:
            return "boolean"
        if re.match(r"^-?(0|[1-9]\d{0,17})$", stripped):
            return "integer"
        if re.match(r"^-?(0|[1-9]\d{0,17})\.\d+$", stripped):
            return "number"
        return "string"
    if value is None:
        return "null"
    return "string"


def coerce_records(records: list[dict[str, Any]], schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert numeric/boolean strings to JSON-native values after schema inference.

    This keeps the source faithful while giving DuckDB and BI consumers real types. Values with
    leading zeros (postcodes, account numbers) are deliberately left as strings.
    """
    casts: dict[str, str] = {
        column["name"]: column["type"]
        for column in schema
        if column.get("type") in {"integer", "number", "boolean"}
    }
    if not casts:
        return records
    for record in records:
        for name, kind in casts.items():
            value = record.get(name)
            if value is None or value == "":
                continue
            if kind == "boolean" and isinstance(value, str):
                record[name] = value.strip().lower() == "true"
            elif kind == "integer" and isinstance(value, str):
                with contextlib.suppress(ValueError):
                    record[name] = int(value)
            elif kind == "number" and isinstance(value, str):
                with contextlib.suppress(ValueError):
                    record[name] = float(value)
    return records


def _detect_pii(column: str, values: list[Any]) -> tuple[bool, str | None]:
    normalized = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
    for token, kind in PII_NAMES.items():
        if token in normalized:
            return True, kind
    # Date/time columns otherwise collide with the phone-number pattern (2026-10-01).
    if re.search(r"(^|_)(date|time|timestamp|at)($|_)", normalized):
        return False, None
    sample = [str(value) for value in values[:30] if value is not None]
    sample = [value for value in sample if not re.match(r"^\d{4}-\d{2}-\d{2}", value)]
    if not sample:
        return False, None
    for kind, pattern in PII_PATTERNS.items():
        if kind == "phone":
            matches = sum(
                1
                for value in sample
                if re.search(r"[ +()\-]", value) and pattern.match(value)
            )
        else:
            matches = sum(1 for value in sample if pattern.match(value))
        if matches >= max(2, len(sample) // 3):
            return True, kind
    return False, None


def profile_records(records: list[dict[str, Any]], schema: list[dict[str, Any]]) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "sample_size": min(len(records), 1000),
        "row_count": len(records),
        "columns": {},
    }
    for column in schema:
        name = column["name"]
        values = [record.get(name) for record in records[:1000]]
        non_null = [value for value in values if value not in (None, "")]
        distinct = len({str(value) for value in non_null})
        entry: dict[str, Any] = {
            "null_pct": round((len(values) - len(non_null)) / len(values) * 100, 2) if values else 0,
            "distinct_sample": distinct,
            "min": None,
            "max": None,
        }
        numeric = [value for value in non_null if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if numeric:
            entry["min"] = min(numeric)
            entry["max"] = max(numeric)
        profile["columns"][name] = entry
    return profile


def classification_for(schema: list[dict[str, Any]], requested: str | None = None) -> str:
    if requested and requested != "auto":
        return requested
    if any(column.get("pii") for column in schema):
        return "confidential"
    return "internal"
