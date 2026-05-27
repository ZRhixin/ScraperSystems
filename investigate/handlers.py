"""
Investigate layer — all tool-call handlers for the Investigate agent.

Each function accepts a dict (parsed request body) and returns (status_code, dict).

Endpoints:
  /investigate/property-state          — full DB snapshot for one property
  /investigate/save-capture            — persist a downloaded PDF to rod_captures
  /investigate/read-document           — run document-read subroutine
  /investigate/update-appraiser-verification
  /investigate/log-trace               — append investigation_trace row
  /investigate/log-incidental          — insert incidental_records row
  /investigate/open-question           — insert investigation_questions row
  /investigate/resolve-question        — update investigation_questions row
  /investigate/settle-chain            — mark session settled
  /investigate/flag-review             — mark session flagged_for_review
  /investigate/court-pull              — store court case capture
"""
import base64
import json
import tempfile
from datetime import date, datetime

from database.db import get_conn, dict_cursor
from document_read.subroutine import read_document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _serialize(d: dict) -> dict:
    return json.loads(json.dumps(d, default=_json_serial))


# ---------------------------------------------------------------------------
# 1. /investigate/property-state
# ---------------------------------------------------------------------------

def property_state(data: dict) -> tuple[int, dict]:
    """
    Returns full DB snapshot for one property:
      - property row
      - appraiser_transfer_history rows
      - document_extractions rows
      - investigation_session (created if missing)
    """
    property_id = data.get("property_id")
    if not property_id:
        return 400, {"error": "property_id is required"}

    try:
        property_id = int(property_id)
    except (TypeError, ValueError):
        return 400, {"error": "property_id must be an integer"}

    conn = get_conn()
    try:
        cur = dict_cursor(conn)

        cur.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
        prop = cur.fetchone()
        if not prop:
            return 404, {"error": f"No property found with id={property_id}"}
        prop = dict(prop)

        cur.execute(
            "SELECT * FROM appraiser_transfer_history WHERE property_id = %s ORDER BY id",
            (property_id,),
        )
        transfers = _rows_to_dicts(cur.fetchall())

        cur.execute(
            "SELECT * FROM document_extractions WHERE property_id = %s ORDER BY id",
            (property_id,),
        )
        raw_extractions = _rows_to_dicts(cur.fetchall())
        # Deduplicate by (book, page) — keep the first (lowest id) occurrence of each pair
        _seen_bp = set()
        extractions = []
        for ex in raw_extractions:
            key = (ex.get("book"), ex.get("page"))
            if key not in _seen_bp:
                _seen_bp.add(key)
                extractions.append(ex)

        cur.execute(
            "SELECT * FROM investigation_sessions WHERE property_id = %s ORDER BY id DESC LIMIT 1",
            (property_id,),
        )
        session_row = cur.fetchone()

        if session_row is None:
            cur2 = conn.cursor()
            cur2.execute(
                """
                INSERT INTO investigation_sessions
                    (property_id, status, current_phase, started_at)
                VALUES (%s, 'in_progress', 'A', NOW())
                RETURNING id
                """,
                (property_id,),
            )
            session_id = cur2.fetchone()[0]
            conn.commit()

            cur.execute("SELECT * FROM investigation_sessions WHERE id = %s", (session_id,))
            session_row = cur.fetchone()

        session = dict(session_row)

        return 200, _serialize({
            "property":      prop,
            "transfers":     transfers,
            "extractions":   extractions,
            "session":       session,
        })

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. /investigate/save-capture
# ---------------------------------------------------------------------------

def save_capture(data: dict) -> tuple[int, dict]:
    """
    Persist a deed PDF (already downloaded by the county deeds tool) to rod_captures.

    The agent calls the county deeds endpoint first to get pdf_base64 + pdf_url,
    then calls this endpoint to save it to the DB.

    Required: property_id, pdf_base64, source_url
    Optional: book, page, instrument_number, capture_type (default: document_image)
    """
    property_id = data.get("property_id")
    pdf_base64  = (data.get("pdf_base64") or "").strip()
    source_url  = (data.get("source_url") or "").strip()

    if not property_id:
        return 400, {"error": "property_id is required"}
    if not pdf_base64:
        return 400, {"error": "pdf_base64 is required"}
    if not source_url:
        return 400, {"error": "source_url is required"}

    try:
        property_id = int(property_id)
    except (TypeError, ValueError):
        return 400, {"error": "property_id must be an integer"}

    book             = (data.get("book") or "").strip() or None
    page             = (data.get("page") or "").strip() or None
    instrument_number = (data.get("instrument_number") or "").strip() or None
    capture_type     = (data.get("capture_type") or "document_image").strip()

    try:
        pdf_bytes = base64.b64decode(pdf_base64)
    except Exception:
        return 400, {"error": "pdf_base64 is not valid base64"}

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(pdf_bytes)
    tmp.close()

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rod_captures
                (property_id, source_url, capture_type, book, page, instrument_number,
                 raw_content, captured_at, parse_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 'captured')
            RETURNING id
            """,
            (property_id, source_url, capture_type, book, page, instrument_number, tmp.name),
        )
        capture_id = cur.fetchone()[0]
        conn.commit()
        return 200, {"capture_id": capture_id, "property_id": property_id, "source_url": source_url}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. /investigate/read-document
# ---------------------------------------------------------------------------

def read_document_handler(data: dict) -> tuple[int, dict]:
    """
    Run the document-read subroutine on an existing capture row.

    Required: capture_id, capture_table (rod_captures | court_captures)
    Required: parcel_reference dict with parcel_id and county
    """
    capture_id = data.get("capture_id")
    capture_table = (data.get("capture_table") or "rod_captures").strip()
    parcel_reference = data.get("parcel_reference") or {}

    if not capture_id:
        return 400, {"error": "capture_id is required"}
    if capture_table not in ("rod_captures", "court_captures"):
        return 400, {"error": "capture_table must be rod_captures or court_captures"}

    try:
        capture_id = int(capture_id)
    except (TypeError, ValueError):
        return 400, {"error": "capture_id must be an integer"}

    extraction = read_document(capture_id, capture_table, parcel_reference)
    return 200, _serialize(extraction)


# ---------------------------------------------------------------------------
# 4. /investigate/update-appraiser-verification
# ---------------------------------------------------------------------------

def update_appraiser_verification(data: dict) -> tuple[int, dict]:
    """
    Update the verification_status (and optional notes) on an
    appraiser_transfer_history row.

    Required: transfer_id, verification_status
    Optional: verification_notes
    """
    transfer_id = data.get("transfer_id")
    status = (data.get("verification_status") or "").strip()

    if not transfer_id:
        return 400, {"error": "transfer_id is required"}
    if not status:
        return 400, {"error": "verification_status is required"}

    valid_statuses = ("pending", "verified", "verified_with_discrepancy", "not_findable")
    if status not in valid_statuses:
        return 400, {"error": f"verification_status must be one of: {', '.join(valid_statuses)}"}

    try:
        transfer_id = int(transfer_id)
    except (TypeError, ValueError):
        return 400, {"error": "transfer_id must be an integer"}

    notes = (data.get("verification_notes") or "").strip() or None

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE appraiser_transfer_history
               SET verification_status = %s,
                   verification_notes  = %s,
                   verified_at         = NOW(),
                   updated_at          = NOW()
             WHERE id = %s
            RETURNING id
            """,
            (status, notes, transfer_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return 404, {"error": f"No transfer row with id={transfer_id}"}
        conn.commit()
        return 200, {"transfer_id": transfer_id, "verification_status": status}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. /investigate/log-trace
# ---------------------------------------------------------------------------

def log_trace(data: dict) -> tuple[int, dict]:
    """
    Append a row to investigation_trace (audit log, never update).

    Required: session_id, step_number, action
    Optional: input (any JSON), output (any JSON)
    """
    session_id = data.get("session_id")
    step_number = data.get("step_number")
    action = (data.get("action") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    if step_number is None:
        return 400, {"error": "step_number is required"}
    if not action:
        return 400, {"error": "action is required"}

    try:
        session_id = int(session_id)
        step_number = int(step_number)
    except (TypeError, ValueError):
        return 400, {"error": "session_id and step_number must be integers"}

    inp = data.get("input")
    out = data.get("output")

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO investigation_trace
                (session_id, step_number, action, input, output)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                session_id,
                step_number,
                action,
                json.dumps(inp) if inp is not None else None,
                json.dumps(out) if out is not None else None,
            ),
        )
        trace_id = cur.fetchone()[0]
        conn.commit()
        return 200, {"trace_id": trace_id, "session_id": session_id, "step_number": step_number}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. /investigate/log-incidental
# ---------------------------------------------------------------------------

def log_incidental(data: dict) -> tuple[int, dict]:
    """
    Insert a row into incidental_records (mortgage, lien, release, etc.).

    Required: property_id, extraction_id, record_type, summary
    """
    property_id = data.get("property_id")
    extraction_id = data.get("extraction_id")
    record_type = (data.get("record_type") or "").strip()
    summary = (data.get("summary") or "").strip()

    if not property_id:
        return 400, {"error": "property_id is required"}
    if not extraction_id:
        return 400, {"error": "extraction_id is required"}
    if not record_type:
        return 400, {"error": "record_type is required"}
    if not summary:
        return 400, {"error": "summary is required"}

    try:
        property_id = int(property_id)
        extraction_id = int(extraction_id)
    except (TypeError, ValueError):
        return 400, {"error": "property_id and extraction_id must be integers"}

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO incidental_records
                (property_id, extraction_id, record_type, summary)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (property_id, extraction_id, record_type, summary),
        )
        record_id = cur.fetchone()[0]
        conn.commit()
        return 200, {"record_id": record_id, "property_id": property_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. /investigate/open-question
# ---------------------------------------------------------------------------

def open_question(data: dict) -> tuple[int, dict]:
    """
    Insert a new open question for this investigation session.

    Required: session_id, question
    """
    session_id = data.get("session_id")
    question = (data.get("question") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not question:
        return 400, {"error": "question is required"}

    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return 400, {"error": "session_id must be an integer"}

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO investigation_questions (session_id, question)
            VALUES (%s, %s)
            RETURNING id
            """,
            (session_id, question),
        )
        question_id = cur.fetchone()[0]
        conn.commit()
        return 200, {"question_id": question_id, "session_id": session_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. /investigate/resolve-question
# ---------------------------------------------------------------------------

def resolve_question(data: dict) -> tuple[int, dict]:
    """
    Mark a question resolved (or unresolved_flagged / abandoned).

    Required: question_id, resolution
    Optional: resolution_notes, actions_taken (list)
    """
    question_id = data.get("question_id")
    resolution = (data.get("resolution") or "").strip()

    if not question_id:
        return 400, {"error": "question_id is required"}
    if not resolution:
        return 400, {"error": "resolution is required"}

    valid = ("resolved", "unresolved_flagged", "abandoned")
    if resolution not in valid:
        return 400, {"error": f"resolution must be one of: {', '.join(valid)}"}

    try:
        question_id = int(question_id)
    except (TypeError, ValueError):
        return 400, {"error": "question_id must be an integer"}

    notes = (data.get("resolution_notes") or "").strip() or None
    actions = data.get("actions_taken") or []

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE investigation_questions
               SET resolution       = %s,
                   resolution_notes = %s,
                   actions_taken    = %s,
                   updated_at       = NOW()
             WHERE id = %s
            RETURNING id
            """,
            (resolution, notes, json.dumps(actions), question_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return 404, {"error": f"No question with id={question_id}"}
        conn.commit()
        return 200, {"question_id": question_id, "resolution": resolution}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 9. /investigate/settle-chain
# ---------------------------------------------------------------------------

def settle_chain(data: dict) -> tuple[int, dict]:
    """
    Mark investigation_session as settled.

    Required: session_id
    Optional: stop_reason
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return 400, {"error": "session_id must be an integer"}

    stop_reason = (data.get("stop_reason") or "").strip() or None

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE investigation_sessions
               SET status       = 'settled',
                   current_phase = 'done',
                   completed_at  = NOW(),
                   stop_reason   = %s,
                   updated_at    = NOW()
             WHERE id = %s
            RETURNING id
            """,
            (stop_reason, session_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return 404, {"error": f"No session with id={session_id}"}
        conn.commit()
        return 200, {"session_id": session_id, "status": "settled"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 10. /investigate/flag-review
# ---------------------------------------------------------------------------

def flag_review(data: dict) -> tuple[int, dict]:
    """
    Mark investigation_session as flagged_for_review.

    Required: session_id
    Optional: stop_reason
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return 400, {"error": "session_id must be an integer"}

    stop_reason = (data.get("stop_reason") or "").strip() or None

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE investigation_sessions
               SET status        = 'flagged_for_review',
                   completed_at  = NOW(),
                   stop_reason   = %s,
                   updated_at    = NOW()
             WHERE id = %s
            RETURNING id
            """,
            (stop_reason, session_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return 404, {"error": f"No session with id={session_id}"}
        conn.commit()
        return 200, {"session_id": session_id, "status": "flagged_for_review"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 11. /investigate/court-pull
# ---------------------------------------------------------------------------

def court_pull(data: dict) -> tuple[int, dict]:
    """
    Store a court case as a court_captures row.
    The agent passes the case dict it already has from a prior court search.

    Required: property_id, case_url
    Optional: court_case_number, document_type, case_data (dict — stored as raw_content JSON)
    """
    property_id = data.get("property_id")
    case_url = (data.get("case_url") or "").strip()

    if not property_id:
        return 400, {"error": "property_id is required"}
    if not case_url:
        return 400, {"error": "case_url is required"}

    try:
        property_id = int(property_id)
    except (TypeError, ValueError):
        return 400, {"error": "property_id must be an integer"}

    court_case_number = (data.get("court_case_number") or "").strip() or None
    document_type = (data.get("document_type") or "case_summary").strip()
    case_data = data.get("case_data") or {}

    raw_content = json.dumps(case_data) if case_data else None

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO court_captures
                (property_id, source_url, capture_type, court_case_number,
                 document_type, raw_content, captured_at, parse_status)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'captured')
            RETURNING id
            """,
            (
                property_id,
                case_url,
                "case_summary",
                court_case_number,
                document_type,
                raw_content,
            ),
        )
        capture_id = cur.fetchone()[0]
        conn.commit()
        return 200, {
            "capture_id":        capture_id,
            "property_id":       property_id,
            "court_case_number": court_case_number,
            "source_url":        case_url,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 12. /investigate/pull-deed  (county-agnostic combined search + download + save)
# ---------------------------------------------------------------------------

def _pull_deed_wake(book: str, page: str) -> tuple[dict, bytes, str]:
    """Returns (hit_dict, pdf_bytes, pdf_url). Raises on failure."""
    from county.wake.deeds.search import (
        _new_session, _base_payload, _do_search,
        download_document_pdf as _download_pdf,
    )
    # Single session for both search and download — Wake ROD requires the
    # session to have gone through the search flow before serving the PDF.
    s = _new_session()
    payload = _base_payload()
    payload["field_BookPageID_DOT_Volume"] = str(book).strip()
    payload["field_BookPageID_DOT_Page"] = str(page).strip()
    results = _do_search(s, payload, 1, False)
    if not results:
        raise LookupError(f"No deed found for book={book} page={page}")
    hit = results[0]
    doc_id = hit.get("doc_id", "")
    if not doc_id:
        raise RuntimeError("Search returned a result but doc_id is missing")
    pdf_bytes, pdf_url = _download_pdf(doc_id, s=s)
    if not pdf_bytes:
        raise RuntimeError(f"PDF download returned empty bytes for doc_id={doc_id}")
    return hit, pdf_bytes, pdf_url


_COUNTY_DISPATCHERS = {
    "wake": _pull_deed_wake,
    # Add new counties here as their deeds scrapers are built:
    # "mecklenburg": _pull_deed_mecklenburg,
    # "newhanover":  _pull_deed_newhanover,
    # "buncombe":    _pull_deed_buncombe,
}


def pull_deed(data: dict) -> tuple[int, dict]:
    """
    County-agnostic deed pull.
    Combines: county ROD book/page search → PDF download → rod_captures insert.
    The agent never touches PDF bytes — only receives capture_id back.

    Required: property_id, county, book, page
    Optional: instrument_number
    Returns:  capture_id, doc_id, book, page, source_url, doc_type,
              grantor, grantee, recording_date, document_number
    """
    property_id = data.get("property_id")
    county      = (data.get("county") or "").strip().lower().removesuffix(" county")
    book        = (data.get("book") or "").strip()
    page        = (data.get("page") or "").strip()

    if not property_id:
        return 400, {"error": "property_id is required"}
    if not county:
        return 400, {"error": "county is required"}
    if not book:
        return 400, {"error": "book is required"}
    if not page:
        return 400, {"error": "page is required"}

    try:
        property_id = int(property_id)
    except (TypeError, ValueError):
        return 400, {"error": "property_id must be an integer"}

    dispatcher = _COUNTY_DISPATCHERS.get(county)
    if dispatcher is None:
        implemented = ", ".join(_COUNTY_DISPATCHERS.keys())
        return 501, {"error": f"Deeds scraper not yet implemented for county='{county}'. Implemented: {implemented}"}

    instrument_number = (data.get("instrument_number") or "").strip() or None

    try:
        hit, pdf_bytes, pdf_url = dispatcher(book, page)
    except LookupError as e:
        return 404, {"error": str(e)}
    except Exception as e:
        return 500, {"error": str(e)}

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(pdf_bytes)
    tmp.close()

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rod_captures
                (property_id, source_url, capture_type, book, page, instrument_number,
                 raw_content, captured_at, parse_status)
            VALUES (%s, %s, 'document_image', %s, %s, %s, %s, NOW(), 'captured')
            RETURNING id
            """,
            (property_id, pdf_url, book, page, instrument_number, tmp.name),
        )
        capture_id = cur.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return 200, {
        "capture_id":      capture_id,
        "property_id":     property_id,
        "county":          county,
        "doc_id":          hit.get("doc_id", ""),
        "book":            hit.get("book", book),
        "page":            hit.get("page", page),
        "source_url":      pdf_url,
        "document_number": hit.get("document_number", ""),
        "recording_date":  hit.get("recording_date", ""),
        "doc_type":        hit.get("doc_type", ""),
        "grantor":         hit.get("grantor", ""),
        "grantee":         hit.get("grantee", ""),
    }
