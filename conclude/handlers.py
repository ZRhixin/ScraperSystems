"""
Conclude layer — handlers for the Conclude workflow.

Endpoints:
  /conclude/data   — fetch all DB data needed for Prompt 4 (chain conclusion)
  /conclude/write  — persist Claude's Prompt 4 output to chain_conclusions
"""
import json
from datetime import date, datetime

from database.db import get_conn, dict_cursor


def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _serialize(d) -> dict:
    return json.loads(json.dumps(d, default=_json_serial))


def conclude_data(data: dict) -> tuple[int, dict]:
    """
    Fetch all data needed for Prompt 4.
    Returns property, settled session, all extractions, incidentals, and aggregated flags.
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
            """
            SELECT * FROM investigation_sessions
            WHERE property_id = %s AND status IN ('settled', 'flagged_for_review')
            ORDER BY id DESC LIMIT 1
            """,
            (property_id,),
        )
        session = cur.fetchone()
        if not session:
            return 409, {"error": "No settled investigation session found for this property"}
        session = dict(session)

        cur.execute(
            "SELECT * FROM document_extractions WHERE property_id = %s ORDER BY id",
            (property_id,),
        )
        extractions = _rows_to_dicts(cur.fetchall())

        cur.execute(
            """
            SELECT ir.*, de.document_type
            FROM incidental_records ir
            JOIN document_extractions de ON ir.extraction_id = de.id
            WHERE ir.property_id = %s
            ORDER BY ir.id
            """,
            (property_id,),
        )
        incidentals = _rows_to_dicts(cur.fetchall())

        # Aggregate unique flags across all extractions
        seen = set()
        all_flags = []
        for ext in extractions:
            ext_flags = ext.get("flags") or []
            if isinstance(ext_flags, str):
                ext_flags = json.loads(ext_flags)
            for f in ext_flags:
                key = json.dumps(f, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    all_flags.append(f)

        return 200, _serialize({
            "property": prop,
            "session": session,
            "extractions": extractions,
            "incidentals": incidentals,
            "aggregated_flags": all_flags,
        })
    finally:
        conn.close()


def conclude_write(data: dict) -> tuple[int, dict]:
    """
    Persist Claude's Prompt 4 output to chain_conclusions.
    Supersedes any existing active conclusion for the property.
    Updates properties.chain_conclusion_id.
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
        cur = conn.cursor()
        dict_cur = dict_cursor(conn)

        dict_cur.execute("SELECT id FROM properties WHERE id = %s", (property_id,))
        if not dict_cur.fetchone():
            return 404, {"error": f"No property found with id={property_id}"}

        # Find existing active conclusion to supersede
        dict_cur.execute(
            "SELECT id FROM chain_conclusions WHERE property_id = %s AND status = 'active'",
            (property_id,),
        )
        existing = dict_cur.fetchone()
        existing_id = dict(existing)["id"] if existing else None

        # Insert new conclusion
        cur.execute(
            """
            INSERT INTO chain_conclusions (
                property_id, status,
                current_owners, acquisition_type, acquisition_document_refs,
                vesting, vesting_evidence,
                legal_description_confidence, supporting_document_refs,
                flags, verify_status
            ) VALUES (
                %s, 'active',
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, 'pending'
            )
            RETURNING id
            """,
            (
                property_id,
                json.dumps(data.get("current_owners") or []),
                data.get("acquisition_type") or "unresolved",
                json.dumps(data.get("acquisition_document_refs") or []),
                data.get("vesting") or "unresolved",
                json.dumps(data.get("vesting_evidence") or []),
                data.get("legal_description_confidence") or "low",
                json.dumps(data.get("supporting_document_refs") or []),
                json.dumps(data.get("flags") or []),
            ),
        )
        new_id = cur.fetchone()[0]

        # Supersede the old active conclusion
        if existing_id:
            cur.execute(
                """
                UPDATE chain_conclusions
                SET status = 'superseded', superseded_by_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (new_id, existing_id),
            )

        # Point property at the new conclusion
        cur.execute(
            "UPDATE properties SET chain_conclusion_id = %s, updated_at = NOW() WHERE id = %s",
            (new_id, property_id),
        )

        conn.commit()
        return 200, {"conclusion_id": new_id, "superseded_id": existing_id, "property_id": property_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
