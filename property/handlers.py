"""
Property layer — full research data for a property.

Endpoint:
  /property/full-research — fetch ALL research data for a property by parcel_id + county
"""
import json
from datetime import date, datetime

from database.db import get_conn, dict_cursor


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _serialize(d) -> dict:
    return json.loads(json.dumps(d, default=_json_serial))


def property_full_research(data: dict) -> tuple[int, dict]:
    """
    Return everything the scraper has researched about a property.
    Accepts: { parcel_id, county, state_code (optional, default NC) }
    """
    parcel_id = data.get("parcel_id")
    county = data.get("county")
    state_code = data.get("state_code", "NC")

    if not parcel_id or not county:
        return 400, {"error": "parcel_id and county are required"}

    conn = get_conn()
    try:
        cur = dict_cursor(conn)

        # Core property record (case-insensitive county match)
        cur.execute(
            """
            SELECT * FROM properties
            WHERE parcel_id = %s AND LOWER(county) = LOWER(%s) AND state_code = %s
            """,
            (parcel_id, county, state_code),
        )
        prop = cur.fetchone()
        if not prop:
            return 404, {"error": f"No property found for parcel_id={parcel_id} county={county}"}
        prop = dict(prop)
        property_id = prop["id"]

        # Active chain conclusion (ownership + vesting summary)
        cur.execute(
            """
            SELECT * FROM chain_conclusions
            WHERE property_id = %s AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (property_id,),
        )
        conclusion = cur.fetchone()
        conclusion = dict(conclusion) if conclusion else None

        # County assessor transfer history (deed chain from assessor)
        cur.execute(
            """
            SELECT * FROM appraiser_transfer_history
            WHERE property_id = %s ORDER BY recorded_date ASC
            """,
            (property_id,),
        )
        transfers = _rows_to_dicts(cur.fetchall())

        # All document extractions (deeds, court docs, etc.)
        cur.execute(
            """
            SELECT de.*,
                   rc.source_url AS rod_source_url,
                   rc.ocr_text   AS rod_ocr_text,
                   cc.source_url AS court_source_url,
                   cc.ocr_text   AS court_ocr_text,
                   cc.court_case_number
            FROM document_extractions de
            LEFT JOIN rod_captures    rc ON rc.id = de.rod_capture_id
            LEFT JOIN court_captures  cc ON cc.id = de.court_capture_id
            WHERE de.property_id = %s
            ORDER BY de.recorded_date ASC NULLS LAST, de.id ASC
            """,
            (property_id,),
        )
        extractions = _rows_to_dicts(cur.fetchall())

        # Incidental records (mortgages, liens, releases)
        cur.execute(
            """
            SELECT ir.*, de.document_type, de.recorded_date
            FROM incidental_records ir
            JOIN document_extractions de ON ir.extraction_id = de.id
            WHERE ir.property_id = %s ORDER BY ir.id
            """,
            (property_id,),
        )
        incidentals = _rows_to_dicts(cur.fetchall())

        # Latest investigation session + questions
        cur.execute(
            """
            SELECT * FROM investigation_sessions
            WHERE property_id = %s ORDER BY id DESC LIMIT 1
            """,
            (property_id,),
        )
        inv_session = cur.fetchone()
        inv_session = dict(inv_session) if inv_session else None

        investigation_questions = []
        if inv_session:
            cur.execute(
                "SELECT * FROM investigation_questions WHERE session_id = %s ORDER BY id",
                (inv_session["id"],),
            )
            investigation_questions = _rows_to_dicts(cur.fetchall())

        # Heir research session (latest)
        cur.execute(
            """
            SELECT * FROM heir_research_sessions
            WHERE property_id = %s ORDER BY id DESC LIMIT 1
            """,
            (property_id,),
        )
        heir_session = cur.fetchone()
        heir_session = dict(heir_session) if heir_session else None

        # All researched persons (skip genie results, obituaries, dob/dod)
        heir_persons = []
        if heir_session:
            cur.execute(
                """
                SELECT * FROM heir_research_persons
                WHERE session_id = %s ORDER BY id
                """,
                (heir_session["id"],),
            )
            heir_persons = _rows_to_dicts(cur.fetchall())

        return 200, _serialize({
            "property": prop,
            "chain_conclusion": conclusion,
            "appraiser_transfers": transfers,
            "document_extractions": extractions,
            "incidental_records": incidentals,
            "investigation_session": inv_session,
            "investigation_questions": investigation_questions,
            "heir_research_session": heir_session,
            "heir_research_persons": heir_persons,
        })

    finally:
        conn.close()
