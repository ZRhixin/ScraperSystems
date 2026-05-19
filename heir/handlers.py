"""
Heir tracer handlers — endpoints for the heir tracer n8n workflow.

Routes (registered in server.py):
  POST /heir/session        — create a new heir research session
  POST /heir/write-person   — write one Orchestrator result for a relative
  POST /heir/persons        — load all researched persons for a property/session
  POST /heir/obituary-text  — load full obituary texts for a session (Family Assembler)
  POST /heir/write          — Geneologist writes the final compiled heir tree
"""
import json
from datetime import datetime, date

from database.db import get_conn, dict_cursor


def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _dump(v) -> str:
    return json.dumps(v, default=_json_serial)


# ---------------------------------------------------------------------------
# POST /heir/session
# ---------------------------------------------------------------------------
def create_session(data: dict) -> tuple[int, dict]:
    """
    Create a new heir research session.
    Called by the Code in JavaScript node before the loop starts.

    Required: property_id, root_decedent_name
    Optional: conclusion_id, root_decedent_dod
    Returns:  { session_id }
    """
    property_id = data.get("property_id")
    root_decedent_name = (data.get("root_decedent_name") or "").strip()

    if not property_id:
        return 400, {"error": "property_id is required"}
    if not root_decedent_name:
        root_decedent_name = "Unknown"

    conclusion_id = data.get("conclusion_id") or None
    root_decedent_dod = (data.get("root_decedent_dod") or "").strip() or None

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO heir_research_sessions
                    (property_id, conclusion_id, root_decedent_name, root_decedent_dod)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at
            """, (property_id, conclusion_id, root_decedent_name, root_decedent_dod))
            row = cur.fetchone()
            conn.commit()

    return 200, {
        "session_id": row["id"],
        "property_id": property_id,
        "root_decedent_name": root_decedent_name,
        "created_at": row["created_at"].isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /heir/write-person
# ---------------------------------------------------------------------------
def write_person(data: dict) -> tuple[int, dict]:
    """
    Write one relative's Orchestrator research output to heir_research_persons.
    Called by the Orchestrator (via Write Family Tree Database tool) after
    completing all research phases for one person.

    Required: session_id, property_id, input_name
    Optional: all other fields from the Orchestrator JSON output
    Returns:  { person_id }
    """
    session_id = data.get("session_id")
    property_id = data.get("property_id")
    input_name = (data.get("name") or data.get("input_name") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not property_id:
        return 400, {"error": "property_id is required"}
    if not input_name:
        return 400, {"error": "name or input_name is required"}

    # Pull matched identity block
    identity = data.get("matched_identity") or {}

    # Pull deceased facts block
    deceased = data.get("deceased_facts") or {}

    # Pull source-of-evidence fields
    obituary_url  = (data.get("obituary_url") or "").strip() or None
    obituary_text = (data.get("obituary_text") or "").strip() or None
    claim_sources = data.get("claim_sources") or {}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO heir_research_persons (
                    session_id, property_id,
                    input_name, relationship_hint, age_estimate, phone, input_address,
                    matched_full_name, matched_dob, matched_dod, matched_address, match_confidence,
                    vital_status,
                    date_of_death, marital_status_at_death, surviving_spouse_name,
                    estate_filed, had_will, family_alive_at_death,
                    deed_transfers, cascade_needed,
                    obituary_url, obituary_text, claim_sources,
                    orchestrator_output, notes
                ) VALUES (
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                RETURNING id
            """, (
                session_id, property_id,
                input_name,
                data.get("relationship_hint"),
                data.get("age"),
                data.get("phone"),
                data.get("address"),
                identity.get("full_name"),
                identity.get("dob"),
                identity.get("dod"),
                identity.get("address"),
                identity.get("confidence"),
                data.get("vital_status"),
                deceased.get("date_of_death"),
                deceased.get("marital_status_at_death"),
                deceased.get("surviving_spouse_name"),
                deceased.get("estate_filed"),
                deceased.get("had_will"),
                _dump(deceased.get("family_alive_at_death") or []),
                _dump(data.get("deed_transfers") or []),
                bool(data.get("cascade_needed", False)),
                obituary_url,
                obituary_text,
                _dump(claim_sources),
                _dump(data),
                data.get("notes"),
            ))
            row = cur.fetchone()
            conn.commit()

    return 200, {
        "person_id": row["id"],
        "session_id": session_id,
        "input_name": input_name,
        "vital_status": data.get("vital_status"),
        "cascade_needed": bool(data.get("cascade_needed", False)),
    }


# ---------------------------------------------------------------------------
# POST /heir/persons
# ---------------------------------------------------------------------------
def load_persons(data: dict) -> tuple[int, dict]:
    """
    Load all researched persons for a property or session.
    Called by the Load Family Dataset tool (Family Tree Expert / Geneologist).

    Required: property_id  OR  session_id
    Returns:  { session_id, persons: [...], cascade_count, living_count, deceased_count }
    """
    property_id = data.get("property_id")
    session_id = data.get("session_id")

    if not property_id and not session_id:
        return 400, {"error": "property_id or session_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            if session_id:
                cur.execute("""
                    SELECT * FROM heir_research_persons
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                """, (session_id,))
            else:
                # Get persons from the single most recent session for this property only
                cur.execute("""
                    SELECT p.*
                    FROM heir_research_persons p
                    WHERE p.property_id = %s
                      AND p.session_id = (
                          SELECT id FROM heir_research_sessions
                          WHERE property_id = %s
                          ORDER BY created_at DESC
                          LIMIT 1
                      )
                    ORDER BY p.created_at ASC
                """, (property_id, property_id))

            rows = cur.fetchall()

            # Also get session info
            if rows:
                cur.execute("""
                    SELECT id, root_decedent_name, root_decedent_dod, status
                    FROM heir_research_sessions
                    WHERE id = %s
                """, (rows[0]["session_id"],))
                session_row = cur.fetchone()
            else:
                session_row = None

    persons = []
    for r in rows:
        # Extract cascade_relatives from stored orchestrator_output — avoids a separate DB column
        orch_out = r.get("orchestrator_output") or {}
        if isinstance(orch_out, str):
            try:
                orch_out = json.loads(orch_out)
            except Exception:
                orch_out = {}
        cascade_relatives = orch_out.get("cascade_relatives") or []

        # Extract skip_genie structured fields — stored in orchestrator_output by Person Compiler
        skip_genie_possible_relatives = orch_out.get("skip_genie_possible_relatives") or \
            [r["name"] for r in cascade_relatives if isinstance(r, dict) and r.get("name")]
        skip_genie_known_addresses = orch_out.get("skip_genie_known_addresses") or []
        skip_genie_birth_year = orch_out.get("skip_genie_birth_year")

        persons.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "input_name": r["input_name"],
            "relationship_hint": r["relationship_hint"],
            "matched_full_name": r["matched_full_name"],
            "vital_status": r["vital_status"],
            "date_of_death": r["date_of_death"],
            "marital_status_at_death": r["marital_status_at_death"],
            "surviving_spouse_name": r["surviving_spouse_name"],
            "estate_filed": r["estate_filed"],
            "had_will": r["had_will"],
            "family_alive_at_death": r["family_alive_at_death"],
            "cascade_needed": r["cascade_needed"],
            "cascade_relatives": cascade_relatives,
            "computed_share_percentage": str(r["computed_share_percentage"]) if r["computed_share_percentage"] else None,
            "share_fraction": r["share_fraction"],
            "branch_status": r["branch_status"],
            "deed_transfers": r["deed_transfers"],
            # Evidence columns — needed by Family Assembler to map relationships
            "obituary_url": r["obituary_url"],
            "obituary_text": r["obituary_text"],
            "claim_sources": r["claim_sources"],
            "notes": r["notes"],
            # SkipGenie structured fields for Family Assembler identity confirmation
            "skip_genie_birth_year": skip_genie_birth_year,
            "skip_genie_known_addresses": skip_genie_known_addresses,
            "skip_genie_possible_relatives": skip_genie_possible_relatives,
        })

    living_count = sum(1 for p in persons if p["vital_status"] == "living")
    deceased_count = sum(1 for p in persons if p["vital_status"] == "deceased")
    cascade_count = sum(1 for p in persons if p["cascade_needed"])

    return 200, {
        "session_id": session_row["id"] if session_row else None,
        "root_decedent_name": session_row["root_decedent_name"] if session_row else None,
        "session_status": session_row["status"] if session_row else None,
        "total_persons": len(persons),
        "living_count": living_count,
        "deceased_count": deceased_count,
        "cascade_count": cascade_count,
        "persons": persons,
    }


# ---------------------------------------------------------------------------
# POST /heir/write
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# POST /heir/filter-cascade
# ---------------------------------------------------------------------------
def filter_cascade(data: dict) -> tuple[int, dict]:
    """
    Given a session_id and a list of candidate names, return only the names
    that have NOT yet been researched in this session.

    Required: session_id, candidate_names (list of strings)
    Returns:  { new_persons: [...], already_researched: [...] }
    """
    session_id = data.get("session_id")
    candidate_names = data.get("candidate_names") or []

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not candidate_names:
        return 200, {"new_persons": [], "already_researched": [], "session_id": session_id}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                SELECT input_name, matched_full_name
                FROM heir_research_persons
                WHERE session_id = %s
            """, (session_id,))
            rows = cur.fetchall()

    # Build a normalized set of already-researched names
    researched = set()
    for r in rows:
        if r["input_name"]:
            researched.add(r["input_name"].upper().strip())
        if r["matched_full_name"]:
            researched.add(r["matched_full_name"].upper().strip())

    new_persons = []
    already_researched = []
    for name in candidate_names:
        if name.upper().strip() in researched:
            already_researched.append(name)
        else:
            new_persons.append(name)

    return 200, {
        "new_persons": new_persons,
        "already_researched": already_researched,
        "session_id": session_id,
    }


# ---------------------------------------------------------------------------
# POST /heir/obituary-text
# ---------------------------------------------------------------------------
def load_obituary_texts(data: dict) -> tuple[int, dict]:
    """
    Return full obituary text for all persons in a session.
    Called by the Family Assembler when it needs rich obituary content
    to parse relationship sentences ("son of...", "father of...").

    Required: session_id
    Returns:  { session_id, obituaries: [{ person_id, name, obituary_url, obituary_text }] }
    """
    session_id = data.get("session_id")
    person_id  = data.get("person_id")

    if not session_id and not person_id:
        return 400, {"error": "session_id or person_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            if person_id:
                cur.execute("""
                    SELECT id, input_name, matched_full_name, obituary_url, obituary_text
                    FROM heir_research_persons
                    WHERE id = %s
                """, (person_id,))
            else:
                cur.execute("""
                    SELECT id, input_name, matched_full_name, obituary_url, obituary_text
                    FROM heir_research_persons
                    WHERE session_id = %s
                      AND obituary_text IS NOT NULL
                      AND obituary_text <> ''
                    ORDER BY created_at ASC
                """, (session_id,))
            rows = cur.fetchall()

    obituaries = [
        {
            "person_id":        r["id"],
            "name":             r["matched_full_name"] or r["input_name"],
            "obituary_url":     r["obituary_url"] or "",
            "obituary_text":    r["obituary_text"] or "",
        }
        for r in rows
    ]

    return 200, {
        "session_id": session_id,
        "count": len(obituaries),
        "obituaries": obituaries,
    }


# ---------------------------------------------------------------------------
# POST /heir/queue-persons
# ---------------------------------------------------------------------------
def queue_persons(data: dict) -> tuple[int, dict]:
    """
    Add persons to the research queue for a session, skipping anyone already
    researched or already queued (pending/processing).

    Required: session_id, property_id, persons (list of {name, relationship_hint})
    Returns:  { queued, skipped_researched, skipped_queued, queued_count }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    persons     = data.get("persons") or []

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not property_id:
        return 400, {"error": "property_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            # Already researched names
            cur.execute("""
                SELECT input_name, matched_full_name
                FROM heir_research_persons
                WHERE session_id = %s
            """, (session_id,))
            researched: set[str] = set()
            for r in cur.fetchall():
                if r["input_name"]:
                    researched.add(r["input_name"].upper().strip())
                if r["matched_full_name"]:
                    researched.add(r["matched_full_name"].upper().strip())

            # Already queued names (pending or processing)
            cur.execute("""
                SELECT person_name
                FROM heir_research_queue
                WHERE session_id = %s AND status IN ('pending', 'processing')
            """, (session_id,))
            queued_set: set[str] = {r["person_name"].upper().strip() for r in cur.fetchall()}

            queued_list:        list[dict] = []
            skipped_researched: list[str]  = []
            skipped_queued:     list[str]  = []

            for p in persons:
                name = (p.get("name") or "").strip()
                if not name or len(name) < 3:
                    continue
                name_upper = name.upper()
                if name_upper in researched:
                    skipped_researched.append(name)
                elif name_upper in queued_set:
                    skipped_queued.append(name)
                else:
                    cur.execute("""
                        INSERT INTO heir_research_queue
                            (session_id, property_id, person_name, relationship_hint)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                    """, (session_id, property_id, name, p.get("relationship_hint") or None))
                    row = cur.fetchone()
                    queued_list.append({"queue_id": row["id"], "person_name": name})
                    queued_set.add(name_upper)

            # Reset session to in_progress so the FA trigger can be re-claimed
            if queued_list:
                cur.execute("""
                    UPDATE heir_research_sessions
                    SET status = 'in_progress', updated_at = NOW()
                    WHERE id = %s AND status NOT IN ('complete', 'manual_review')
                """, (session_id,))

            conn.commit()

    return 200, {
        "session_id":         session_id,
        "queued":             queued_list,
        "skipped_researched": skipped_researched,
        "skipped_queued":     skipped_queued,
        "queued_count":       len(queued_list),
    }


# ---------------------------------------------------------------------------
# POST /heir/next-person
# ---------------------------------------------------------------------------
def next_person(data: dict) -> tuple[int, dict]:
    """
    Atomically claim the next pending queue item for a session.
    Uses SELECT FOR UPDATE SKIP LOCKED so concurrent workers never double-claim.

    Required: session_id
    Returns:  { item: { queue_id, person_name, relationship_hint, depth } }
              or { item: null } when the queue is empty.
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                UPDATE heir_research_queue
                SET status = 'processing', started_at = NOW()
                WHERE id = (
                    SELECT id FROM heir_research_queue
                    WHERE session_id = %s AND status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, person_name, relationship_hint, depth
            """, (session_id,))
            row = cur.fetchone()
            conn.commit()

    if not row:
        return 200, {"item": None, "session_id": session_id}

    return 200, {
        "item": {
            "queue_id":         row["id"],
            "person_name":      row["person_name"],
            "relationship_hint": row["relationship_hint"] or "",
            "depth":            row["depth"],
        },
        "session_id": session_id,
    }


# ---------------------------------------------------------------------------
# POST /heir/complete-person
# ---------------------------------------------------------------------------
def complete_person(data: dict) -> tuple[int, dict]:
    """
    Mark a queue item as done after the worker has written the person to DB.

    Required: queue_id
    Returns:  { queue_id, session_id, status: 'done' }
    """
    queue_id = data.get("queue_id")
    if not queue_id:
        return 400, {"error": "queue_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                UPDATE heir_research_queue
                SET status = 'done', completed_at = NOW()
                WHERE id = %s
                RETURNING id, session_id
            """, (queue_id,))
            row = cur.fetchone()
            conn.commit()

    if not row:
        return 404, {"error": "queue item not found"}

    return 200, {"queue_id": row["id"], "session_id": row["session_id"], "status": "done"}


# ---------------------------------------------------------------------------
# POST /heir/queue-status
# ---------------------------------------------------------------------------
def queue_status(data: dict) -> tuple[int, dict]:
    """
    Return queue item counts by status for a session.
    all_done=true when pending=0 AND processing=0 AND at least one item is done —
    that is the signal for the worker to attempt triggering Family Assembler.

    Required: session_id
    Returns:  { pending, processing, done, failed, total, all_done }
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                SELECT status, COUNT(*) AS cnt
                FROM heir_research_queue
                WHERE session_id = %s
                GROUP BY status
            """, (session_id,))
            rows = cur.fetchall()

    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    for r in rows:
        counts[r["status"]] = int(r["cnt"])

    all_done = (
        counts["pending"] == 0
        and counts["processing"] == 0
        and counts["done"] > 0
    )

    return 200, {
        "session_id":  session_id,
        "pending":     counts["pending"],
        "processing":  counts["processing"],
        "done":        counts["done"],
        "failed":      counts["failed"],
        "total":       sum(counts.values()),
        "all_done":    all_done,
    }


# ---------------------------------------------------------------------------
# POST /heir/claim-fa-trigger
# ---------------------------------------------------------------------------
def claim_fa_trigger(data: dict) -> tuple[int, dict]:
    """
    Atomic compare-and-swap: transition session status from 'in_progress' to
    'running_family_assembler'. Only the first caller succeeds (claimed=true);
    subsequent callers get claimed=false — preventing duplicate FA runs.

    Required: session_id
    Returns:  { session_id, claimed: bool }
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                UPDATE heir_research_sessions
                SET status = 'running_family_assembler', updated_at = NOW()
                WHERE id = %s AND status = 'in_progress'
                RETURNING id
            """, (session_id,))
            row = cur.fetchone()
            conn.commit()

    return 200, {"session_id": session_id, "claimed": row is not None}


def write_heir_tree(data: dict) -> tuple[int, dict]:
    """
    Write the final compiled heir tree after all research and Intestate Expert analysis.
    Called by the Geneologist agent when More Cascade? is done.

    Required: property_id, session_id, root_decedent_name, heir_tree
    Optional: conclusion_id, living_heir_count, total_credits_used, status, gaps,
              intestate_analysis
    Returns:  { trace_id, session_id }
    """
    property_id = data.get("property_id")
    session_id = data.get("session_id")
    root_decedent_name = (data.get("root_decedent_name") or "").strip()
    heir_tree = data.get("heir_tree")

    if not property_id:
        return 400, {"error": "property_id is required"}
    if not session_id:
        return 400, {"error": "session_id is required"}
    if not root_decedent_name:
        return 400, {"error": "root_decedent_name is required"}
    if heir_tree is None:
        return 400, {"error": "heir_tree is required"}

    status = data.get("status", "draft")
    living_heir_count = data.get("living_heir_count")
    total_credits_used = data.get("total_credits_used")
    conclusion_id = data.get("conclusion_id") or None
    gaps = data.get("gaps") or []
    intestate_analysis = data.get("intestate_analysis")

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            # Write to heir_traces
            cur.execute("""
                INSERT INTO heir_traces (
                    property_id, session_id, conclusion_id,
                    root_decedent_name, heir_tree,
                    living_heir_count, total_credits_used,
                    status, gaps
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                property_id, session_id, conclusion_id,
                root_decedent_name, _dump(heir_tree),
                living_heir_count, total_credits_used,
                status, _dump(gaps),
            ))
            trace_row = cur.fetchone()
            trace_id = trace_row["id"]

            # Update the session with final data
            cur.execute("""
                UPDATE heir_research_sessions SET
                    status = %s,
                    heir_tree = %s,
                    intestate_analysis = %s,
                    living_heir_count = %s,
                    total_credits_used = %s,
                    gaps = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                status,
                _dump(heir_tree),
                _dump(intestate_analysis) if intestate_analysis else None,
                living_heir_count,
                total_credits_used,
                _dump(gaps),
                session_id,
            ))
            conn.commit()

    return 200, {
        "trace_id": trace_id,
        "session_id": session_id,
        "property_id": property_id,
        "status": status,
        "living_heir_count": living_heir_count,
    }
