"""
Document-read subroutine — orchestrates the full pipeline:
  download → text/image extraction → Claude extraction → DB write

Entry points:
  read_document(capture_id, capture_table, parcel_reference)
      — reads an existing rod_captures / court_captures row, runs full pipeline
  read_document_from_url(url, property_id, parcel_reference, capture_table)
      — downloads URL, creates capture row, runs full pipeline (useful for testing)
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import psycopg2.extras
from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv

from database.db import get_conn, dict_cursor
from document_read.pdf import pdf_bytes_to_images, pdf_has_text_layer, pdf_extract_text
from document_read.extract import extract_from_images, extract_from_text

load_dotenv()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_OCR_CONFIDENCE_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def read_document(
    capture_id: int,
    capture_table: str,          # "rod_captures" or "court_captures"
    parcel_reference: dict,
) -> dict:
    """
    Full document-read pipeline for an existing capture row.
    Returns the document_extractions dict that was written to DB.
    """
    if capture_table not in ("rod_captures", "court_captures"):
        raise ValueError(f"capture_table must be rod_captures or court_captures, got: {capture_table}")

    conn = get_conn()
    try:
        cur = dict_cursor(conn)
        cur.execute(f"SELECT * FROM {capture_table} WHERE id = %s", (capture_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No row found in {capture_table} with id={capture_id}")
        capture = dict(row)

        # Download PDF if not already stored
        pdf_bytes = _get_pdf_bytes(capture, capture_id, capture_table, conn)

        # Extract text or images
        extraction, ocr_confidence = _run_extraction(pdf_bytes, parcel_reference)

        # Update capture with OCR results
        _update_capture_ocr(conn, capture_table, capture_id, ocr_confidence, extraction)

        # Write document_extractions row
        extraction_id = _write_extraction(
            conn=conn,
            property_id=capture["property_id"],
            capture_id=capture_id,
            capture_table=capture_table,
            extraction=extraction,
        )

        conn.commit()
        extraction["_extraction_id"] = extraction_id
        return extraction

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_document_from_url(
    url: str,
    property_id: int,
    parcel_reference: dict,
    capture_table: str = "rod_captures",
    capture_type: str = "document_image",
    book: str = None,
    page: str = None,
    instrument_number: str = None,
    pdf_bytes: bytes = None,        # pass pre-downloaded bytes to skip re-download
) -> dict:
    """
    Download a document URL, create a capture row, then run the full pipeline.
    Useful for testing and for rod_pull / court_pull tool calls.

    Pass pdf_bytes directly when the source requires an authenticated session
    (e.g. Wake ROD) — download with the right session first, then pass bytes here.
    """
    if pdf_bytes is None:
        pdf_bytes = _download_url(url)

    # Save PDF bytes to a temp file so read_document can find them
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(pdf_bytes)
    tmp.close()
    raw_content_path = tmp.name

    conn = get_conn()
    try:
        cur = conn.cursor()

        if capture_table == "rod_captures":
            cur.execute(
                """
                INSERT INTO rod_captures
                    (property_id, source_url, capture_type, book, page, instrument_number,
                     raw_content, captured_at, parse_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 'captured')
                RETURNING id
                """,
                (property_id, url, capture_type, book, page, instrument_number,
                 raw_content_path),
            )
        else:
            cur.execute(
                """
                INSERT INTO court_captures
                    (property_id, source_url, capture_type, raw_content, captured_at, parse_status)
                VALUES (%s, %s, %s, %s, NOW(), 'captured')
                RETURNING id
                """,
                (property_id, url, capture_type, raw_content_path),
            )

        capture_id = cur.fetchone()[0]
        conn.commit()

        # Now run the full pipeline using the existing entry point
        # Re-open connection to get the newly created row
        conn.close()
        return read_document(capture_id, capture_table, parcel_reference)

    except Exception:
        conn.rollback()
        raise
    finally:
        if not conn.closed:
            conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_pdf_bytes(capture: dict, capture_id: int, capture_table: str, conn) -> bytes:
    """Download the document if not already in raw_content as bytes."""
    raw = capture.get("raw_content") or ""

    # If raw_content looks like a URL or file path, download/read it
    if raw.startswith("http"):
        return _download_url(raw)

    if raw and os.path.isfile(raw):
        with open(raw, "rb") as f:
            return f.read()

    # Fall back to source_url
    source_url = capture.get("source_url") or ""
    if source_url.startswith("http"):
        return _download_url(source_url)

    raise ValueError(
        f"Cannot locate PDF for {capture_table} id={capture_id}. "
        "raw_content and source_url are both empty or unresolvable."
    )


def _download_url(url: str) -> bytes:
    s = cffi_requests.Session(impersonate="chrome124")
    r = s.get(url, headers={"User-Agent": _UA}, timeout=30)
    r.raise_for_status()
    return r.content


def _run_extraction(pdf_bytes: bytes, parcel_reference: dict) -> tuple[dict, float]:
    """
    Choose text-layer or Vision path, run Claude extraction.
    Returns (extraction_dict, ocr_confidence).
    """
    if pdf_has_text_layer(pdf_bytes):
        text, confidence = pdf_extract_text(pdf_bytes)
        extraction = extract_from_text(text, parcel_reference, ocr_confidence=confidence)
        return extraction, confidence
    else:
        # Scanned document — Vision path
        images = pdf_bytes_to_images(pdf_bytes)
        confidence = 0.9  # Vision path; actual confidence returned by Claude in extraction_confidence
        extraction = extract_from_images(images, parcel_reference, ocr_confidence=confidence)
        return extraction, confidence


def _update_capture_ocr(conn, capture_table: str, capture_id: int, ocr_confidence: float, extraction: dict):
    parse_status = "extracted"
    if extraction.get("extraction_confidence") == "low" or ocr_confidence < _OCR_CONFIDENCE_THRESHOLD:
        parse_status = "needs_human"

    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE {capture_table}
           SET ocr_confidence = %s,
               parse_status   = %s,
               updated_at     = NOW()
         WHERE id = %s
        """,
        (ocr_confidence, parse_status, capture_id),
    )


def _write_extraction(
    conn,
    property_id: int,
    capture_id: int,
    capture_table: str,
    extraction: dict,
) -> int:
    """Insert document_extractions row and return its id."""
    rod_capture_id = capture_id if capture_table == "rod_captures" else None
    court_capture_id = capture_id if capture_table == "court_captures" else None

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO document_extractions (
            property_id,
            rod_capture_id,
            court_capture_id,
            document_type,
            grantor_names,
            grantee_names,
            recorded_date,
            instrument_date,
            book,
            page,
            instrument_number,
            vesting_language,
            legal_description_full,
            legal_description_short,
            plat_book,
            plat_page,
            conveys_multiple_parcels,
            parcels_conveyed_count,
            references_prior_deed_book,
            references_prior_deed_page,
            references_prior_deed_language,
            legal_match_to_parcel,
            legal_match_method,
            legal_match_notes,
            extraction_confidence,
            summary,
            flags
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            property_id,
            rod_capture_id,
            court_capture_id,
            extraction.get("document_type"),
            json.dumps(extraction.get("grantor_names") or []),
            json.dumps(extraction.get("grantee_names") or []),
            _parse_date(extraction.get("recorded_date")),
            _parse_date(extraction.get("instrument_date")),
            extraction.get("book"),
            extraction.get("page"),
            extraction.get("instrument_number"),
            extraction.get("vesting_language"),
            extraction.get("legal_description_full"),
            extraction.get("legal_description_short"),
            extraction.get("plat_book"),
            extraction.get("plat_page"),
            bool(extraction.get("conveys_multiple_parcels", False)),
            int(extraction.get("parcels_conveyed_count") or 1),
            extraction.get("references_prior_deed_book"),
            extraction.get("references_prior_deed_page"),
            extraction.get("references_prior_deed_language"),
            extraction.get("legal_match_to_parcel"),
            extraction.get("legal_match_method"),
            extraction.get("legal_match_notes"),
            extraction.get("extraction_confidence"),
            extraction.get("summary"),
            json.dumps(extraction.get("flags") or []),
        ),
    )
    return cur.fetchone()[0]


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None
