"""
Verify layer — handlers for the Verify workflow.

Endpoints:
  /verify/data   — fetch pending chain_conclusions row + all referenced extractions
  /verify/write  — update chain_conclusions.verify_status and verify_objections

Intentionally does NOT fetch investigation_trace — Verify evaluates the
conclusion against evidence only, with no knowledge of how it was produced.
"""
import json
from datetime import date, datetime

from database.db import get_conn, dict_cursor


def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _serialize(d) -> dict:
    return json.loads(json.dumps(d, default=_json_serial))


def _extract_referenced_ids(conclusion: dict) -> set[int]:
    """Pull every extraction_id cited anywhere in the conclusion."""
    ids = set()

    refs = conclusion.get("acquisition_document_refs") or {}

    primary = refs.get("primary_document") or {}
    if primary.get("extraction_id"):
        ids.add(int(primary["extraction_id"]))

    chain_back = refs.get("chain_back_document") or {}
    if chain_back and chain_back.get("extraction_id"):
        ids.add(int(chain_back["extraction_id"]))

    for doc in (refs.get("supporting_documents") or []):
        if doc.get("extraction_id"):
            ids.add(int(doc["extraction_id"]))

    vesting = conclusion.get("vesting_evidence") or {}
    if vesting.get("extraction_id"):
        ids.add(int(vesting["extraction_id"]))

    for owner in (conclusion.get("current_owners") or []):
        for signal in (owner.get("deceased_signals") or []):
            if signal.get("evidence_extraction_id"):
                ids.add(int(signal["evidence_extraction_id"]))

    return ids


def verify_data(data: dict) -> tuple[int, dict]:
    """
    Fetch the pending chain_conclusions row and every document_extraction
    it references. Does NOT include investigation_trace.

    Required: conclusion_id
    """
    conclusion_id = data.get("conclusion_id")
    if not conclusion_id:
        return 400, {"error": "conclusion_id is required"}
    try:
        conclusion_id = int(conclusion_id)
    except (TypeError, ValueError):
        return 400, {"error": "conclusion_id must be an integer"}

    conn = get_conn()
    try:
        cur = dict_cursor(conn)

        cur.execute(
            "SELECT * FROM chain_conclusions WHERE id = %s",
            (conclusion_id,),
        )
        conclusion = cur.fetchone()
        if not conclusion:
            return 404, {"error": f"No chain_conclusion found with id={conclusion_id}"}
        conclusion = dict(conclusion)

        if conclusion.get("verify_status") != "pending":
            return 409, {
                "error": f"conclusion {conclusion_id} is not pending "
                         f"(current verify_status={conclusion['verify_status']})"
            }

        # Parse JSONB fields that psycopg2 may return as strings
        for field in ("current_owners", "acquisition_document_refs",
                      "vesting_evidence", "supporting_document_refs",
                      "flags", "verify_objections"):
            val = conclusion.get(field)
            if isinstance(val, str):
                conclusion[field] = json.loads(val)

        # Collect every extraction_id cited in the conclusion
        referenced_ids = _extract_referenced_ids(conclusion)

        extractions = []
        if referenced_ids:
            placeholders = ",".join(["%s"] * len(referenced_ids))
            cur.execute(
                f"SELECT * FROM document_extractions WHERE id IN ({placeholders}) ORDER BY id",
                tuple(referenced_ids),
            )
            rows = cur.fetchall()
            for row in rows:
                ext = dict(row)
                for field in ("grantor_names", "grantee_names", "flags"):
                    if isinstance(ext.get(field), str):
                        ext[field] = json.loads(ext[field])
                extractions.append(ext)

        return 200, _serialize({
            "conclusion": conclusion,
            "referenced_extractions": extractions,
            "referenced_extraction_ids": sorted(referenced_ids),
        })
    finally:
        conn.close()


def verify_write(data: dict) -> tuple[int, dict]:
    """
    Write Verify agent output back to chain_conclusions.

    Required: conclusion_id, verdict
    Optional: objections (list), reviewer_notes (str)

    verdict must be: approved | objection_raised | flagged_for_human
    """
    conclusion_id = data.get("conclusion_id")
    verdict = (data.get("verdict") or "").strip().lower()

    if not conclusion_id:
        return 400, {"error": "conclusion_id is required"}
    try:
        conclusion_id = int(conclusion_id)
    except (TypeError, ValueError):
        return 400, {"error": "conclusion_id must be an integer"}

    valid_verdicts = {"approved", "objection_raised", "flagged_for_human"}
    if verdict not in valid_verdicts:
        return 400, {"error": f"verdict must be one of: {', '.join(valid_verdicts)}"}

    conn = get_conn()
    try:
        cur = conn.cursor()
        dict_cur = dict_cursor(conn)

        dict_cur.execute(
            "SELECT id, verify_status FROM chain_conclusions WHERE id = %s",
            (conclusion_id,),
        )
        row = dict_cur.fetchone()
        if not row:
            return 404, {"error": f"No chain_conclusion found with id={conclusion_id}"}
        if dict(row)["verify_status"] != "pending":
            return 409, {"error": f"conclusion {conclusion_id} is not pending — cannot write verdict"}

        objections = data.get("objections") or []
        reviewer_notes = (data.get("reviewer_notes") or "").strip() or None

        cur.execute(
            """
            UPDATE chain_conclusions
            SET verify_status     = %s,
                verify_objections = %s,
                updated_at        = NOW()
            WHERE id = %s
            """,
            (
                verdict,
                json.dumps({"objections": objections, "reviewer_notes": reviewer_notes}),
                conclusion_id,
            ),
        )
        conn.commit()

        return 200, {
            "conclusion_id": conclusion_id,
            "verdict": verdict,
            "objection_count": len(objections),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
