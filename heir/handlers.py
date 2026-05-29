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


def _parse_bool(v) -> bool | None:
    """Coerce agent output to bool or None. Handles string 'null', 'true', 'false'."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.lower() in ("null", "none", ""):
            return None
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
    return bool(v)


# ---------------------------------------------------------------------------
# POST /heir/session
# ---------------------------------------------------------------------------
def create_session(data: dict) -> tuple[int, dict]:
    """
    Create a new heir research session.
    In v3, called BEFORE Root Research so session_id is available for DB writes.

    Required: property_id
    Optional: root_decedent_name (auto-looked-up from properties table if omitted),
              conclusion_id, root_decedent_dod
    Returns:  { session_id, property_id, root_decedent_name, county, state }
    """
    property_id = data.get("property_id")
    root_decedent_name = (data.get("root_decedent_name") or "").strip()

    if not property_id:
        return 400, {"error": "property_id is required"}

    conclusion_id = data.get("conclusion_id") or None
    root_decedent_dod = (data.get("root_decedent_dod") or "").strip() or None

    county = ""
    state  = ""

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            # Auto-lookup property details if name not provided
            if not root_decedent_name:
                cur.execute("""
                    SELECT current_owners, county, state, address
                    FROM properties WHERE id = %s
                """, (property_id,))
                prop = cur.fetchone()
                if prop:
                    county = (prop.get("county") or "").strip().title()
                    state  = (prop.get("state") or "NC").strip()
                    # current_owners is a JSON array: [{"raw_name": "HAYES, LYDIA HEIRS", ...}]
                    owners = prop.get("current_owners") or []
                    raw = (owners[0].get("raw_name") or "") if owners else ""
                    # Convert "LASTNAME, FIRSTNAME SUFFIX" → "Firstname Lastname"
                    # Strip suffixes: HEIRS, ESTATE, ET AL, DECEASED
                    _STRIP = ("HEIRS", "ESTATE OF", "ET AL", "DECEASED", "ESTATE")
                    raw_clean = raw.upper()
                    for s in _STRIP:
                        raw_clean = raw_clean.replace(s, "").strip().rstrip(",").strip()
                    if "," in raw_clean:
                        last, first = raw_clean.split(",", 1)
                        root_decedent_name = f"{first.strip().title()} {last.strip().title()}"
                    else:
                        root_decedent_name = raw_clean.title()
                    root_decedent_name = root_decedent_name.strip() or "Unknown"
                else:
                    root_decedent_name = "Unknown"

            cur.execute("""
                INSERT INTO heir_research_sessions
                    (property_id, conclusion_id, root_decedent_name, root_decedent_dod)
                VALUES (%s, %s, %s, %s)
                RETURNING id, created_at
            """, (property_id, conclusion_id, root_decedent_name, root_decedent_dod))
            row = cur.fetchone()
            conn.commit()

    return 200, {
        "session_id":          row["id"],
        "property_id":         property_id,
        "root_decedent_name":  root_decedent_name,
        "county":              county,
        "state":               state or "NC",
        "created_at":          row["created_at"].isoformat(),
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
    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return 400, {"error": f"session_id must be an integer, got {session_id!r}"}
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
    maiden_name   = (data.get("maiden_name") or "").strip() or None

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
                    orchestrator_output, notes, maiden_name
                ) VALUES (
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s
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
                maiden_name,
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

    if session_id is not None:
        try:
            session_id = int(session_id)
        except (ValueError, TypeError):
            return 400, {"error": f"session_id must be an integer, got {session_id!r}"}

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

            # Also get session info — look up by rows first, fall back to the requested session_id
            session_lookup_id = rows[0]["session_id"] if rows else session_id
            if session_lookup_id:
                cur.execute("""
                    SELECT id, root_decedent_name, root_decedent_dod, status
                    FROM heir_research_sessions
                    WHERE id = %s
                """, (session_lookup_id,))
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

            _JUNK_PREFIXES = ("HEIRS OF", "HEIR OF", "ESTATE OF")
            _JUNK_EXACT    = {"ESTATE", "UNKNOWN", "N/A", "NA", "NONE", "NULL"}
            MAX_DEPTH = 5

            def _is_junk(n: str) -> bool:
                u = n.upper().strip()
                if len(u) < 3 or u.isdigit():
                    return True
                if u in _JUNK_EXACT:
                    return True
                return any(u == p or u.startswith(p + " ") for p in _JUNK_PREFIXES)

            # Top-level depth applies to all persons unless overridden per-person
            batch_depth = int(data.get("depth") or 0)

            for p in persons:
                name = (p.get("name") or "").strip()
                if not name or _is_junk(name):
                    continue
                name_upper = name.upper()

                item_depth = int(p.get("depth") if p.get("depth") is not None else batch_depth)
                if item_depth >= MAX_DEPTH:
                    skipped_researched.append(f"{name} [depth_cap]")
                    continue

                if name_upper in researched:
                    skipped_researched.append(name)
                elif name_upper in queued_set:
                    skipped_queued.append(name)
                else:
                    maiden = (p.get("maiden_name") or "").strip() or None
                    cur.execute("""
                        INSERT INTO heir_research_queue
                            (session_id, property_id, person_name, relationship_hint, depth, maiden_name)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (session_id, property_id, name, p.get("relationship_hint") or None, item_depth, maiden))
                    row = cur.fetchone()
                    queued_list.append({"queue_id": row["id"], "person_name": name, "depth": item_depth, "maiden_name": maiden})
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
            # Auto-recover items stuck in 'processing' for >10 minutes before claiming next.
            # A worker call that takes longer than 10 min is almost certainly dead
            # (typical per-person research is 4-7 min). After 30 min, give up and mark failed
            # so the queue can drain — otherwise a single poison item blocks the session forever.
            cur.execute("""
                UPDATE heir_research_queue
                SET status = 'failed', completed_at = NOW()
                WHERE session_id = %s AND status = 'processing'
                  AND started_at < NOW() - INTERVAL '30 minutes'
            """, (session_id,))
            cur.execute("""
                UPDATE heir_research_queue
                SET status = 'pending', started_at = NULL
                WHERE session_id = %s AND status = 'processing'
                  AND started_at < NOW() - INTERVAL '10 minutes'
            """, (session_id,))
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
                RETURNING id, person_name, relationship_hint, depth, maiden_name
            """, (session_id,))
            row = cur.fetchone()
            conn.commit()

    if not row:
        return 200, {"item": None, "session_id": session_id}

    return 200, {
        "item": {
            "queue_id":          row["id"],
            "person_name":       row["person_name"],
            "relationship_hint": row["relationship_hint"] or "",
            "depth":             row["depth"],
            "maiden_name":       row["maiden_name"] or "",
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
        # Root person is triggered directly (not via queue) — no queue entry to mark done.
        return 200, {"queue_id": None, "session_id": data.get("session_id"), "status": "done", "note": "no queue entry (root person)"}

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
# POST /heir/queue-recover
# ---------------------------------------------------------------------------
def queue_recover(data: dict) -> tuple[int, dict]:
    """
    Manual queue recovery for stalled sessions.

    Re-queues items stuck in 'processing' for >threshold_minutes.
    If mark_failed=true (default false), marks them 'failed' instead so the
    session can drain past a poison-pill name.

    Required: session_id
    Optional: threshold_minutes (default 5), mark_failed (default false)
    Returns:  { session_id, recovered, action }
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    threshold = int(data.get("threshold_minutes") or 5)
    mark_failed = bool(data.get("mark_failed"))
    new_status = "failed" if mark_failed else "pending"

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            if mark_failed:
                cur.execute("""
                    UPDATE heir_research_queue
                    SET status = 'failed', completed_at = NOW()
                    WHERE session_id = %s AND status = 'processing'
                      AND started_at < NOW() - (INTERVAL '1 minute' * %s)
                    RETURNING id, person_name
                """, (session_id, threshold))
            else:
                cur.execute("""
                    UPDATE heir_research_queue
                    SET status = 'pending', started_at = NULL
                    WHERE session_id = %s AND status = 'processing'
                      AND started_at < NOW() - (INTERVAL '1 minute' * %s)
                    RETURNING id, person_name
                """, (session_id, threshold))
            rows = cur.fetchall()
            conn.commit()

    return 200, {
        "session_id": session_id,
        "recovered": [{"queue_id": r["id"], "person_name": r["person_name"]} for r in rows],
        "count": len(rows),
        "action": new_status,
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


# ---------------------------------------------------------------------------
# POST /heir/write-ancestry
# ---------------------------------------------------------------------------
def write_ancestry(data: dict) -> tuple[int, dict]:
    """
    Save Ancestry.com record findings for a person to heir_ancestry_records.
    Accepts a single record (flat fields) or a batch via records[] array.

    Required: session_id, property_id, search_name
    Optional: person_id, records[] (array of record objects), plus individual
              record fields if sending a single record directly.
    Returns:  { saved, session_id }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    search_name = (data.get("search_name") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not property_id:
        return 400, {"error": "property_id is required"}
    if not search_name:
        return 400, {"error": "search_name is required"}

    person_id        = data.get("person_id") or None
    search_first     = (data.get("search_first") or "").strip() or None
    search_last      = (data.get("search_last") or "").strip() or None
    search_birth_year = (data.get("search_birth_year") or "").strip() or None
    search_death_year = (data.get("search_death_year") or "").strip() or None
    search_state     = (data.get("search_state") or "NC").strip()

    # Support batch (records[]) or single record (flat fields)
    records = data.get("records")
    if not records:
        # Single record mode — wrap the top-level fields into a list
        records = [data]

    saved = []
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                parents  = rec.get("parents") or []
                children = rec.get("children") or []
                siblings = rec.get("siblings") or []

                cur.execute("""
                    INSERT INTO heir_ancestry_records (
                        session_id, property_id, person_id,
                        search_name, search_first, search_last,
                        search_birth_year, search_death_year, search_state,
                        record_id, collection_id, record_type, collection,
                        person_name, dob, dod,
                        birth_location, death_location,
                        spouse_name, parents, children, siblings,
                        residence, source_url, confidence, has_image, viewable,
                        relevance, relevance_notes, raw_data
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING id
                """, (
                    session_id, property_id, person_id,
                    search_name, search_first, search_last,
                    search_birth_year, search_death_year, search_state,
                    rec.get("record_id") or None,
                    rec.get("collection_id") or None,
                    rec.get("record_type") or None,
                    rec.get("collection") or None,
                    rec.get("person_name") or None,
                    rec.get("dob") or None,
                    rec.get("dod") or None,
                    rec.get("birth_location") or None,
                    rec.get("death_location") or None,
                    rec.get("spouse_name") or None,
                    _dump(parents),
                    _dump(children),
                    _dump(siblings),
                    rec.get("residence") or None,
                    rec.get("source_url") or None,
                    rec.get("confidence") or None,
                    bool(rec.get("has_image", False)),
                    bool(rec.get("viewable", False)),
                    rec.get("relevance") or None,
                    rec.get("relevance_notes") or None,
                    _dump(rec),
                ))
                row = cur.fetchone()
                saved.append(row["id"])

            conn.commit()

    return 200, {
        "saved": len(saved),
        "record_ids": saved,
        "session_id": session_id,
        "search_name": search_name,
    }


# ---------------------------------------------------------------------------
# POST /heir/ancestry-records
# ---------------------------------------------------------------------------
def load_ancestry_records(data: dict) -> tuple[int, dict]:
    """
    Load all saved Ancestry findings for a session, optionally filtered by
    person_id or relevance.

    Required: session_id
    Optional: person_id, relevance (confirmed|likely|possible|rejected)
    Returns:  { session_id, count, records: [...] }
    """
    session_id = data.get("session_id")
    person_id  = data.get("person_id")
    relevance  = data.get("relevance")

    if not session_id:
        return 400, {"error": "session_id is required"}

    filters = ["session_id = %s"]
    params: list = [session_id]

    if person_id:
        filters.append("person_id = %s")
        params.append(person_id)
    if relevance:
        filters.append("relevance = %s")
        params.append(relevance)

    where = " AND ".join(filters)

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(f"""
                SELECT
                    id, session_id, property_id, person_id,
                    search_name, search_first, search_last,
                    record_id, record_type, collection,
                    person_name, dob, dod,
                    birth_location, death_location,
                    spouse_name, parents, children, siblings,
                    residence, source_url, confidence,
                    has_image, viewable,
                    relevance, relevance_notes,
                    created_at
                FROM heir_ancestry_records
                WHERE {where}
                ORDER BY
                    CASE relevance
                        WHEN 'confirmed' THEN 1
                        WHEN 'likely'    THEN 2
                        WHEN 'possible'  THEN 3
                        ELSE 4
                    END,
                    created_at ASC
            """, params)
            rows = cur.fetchall()

    records = []
    for r in rows:
        records.append({
            "id":               r["id"],
            "person_id":        r["person_id"],
            "search_name":      r["search_name"],
            "record_id":        r["record_id"],
            "record_type":      r["record_type"],
            "collection":       r["collection"],
            "person_name":      r["person_name"],
            "dob":              r["dob"],
            "dod":              r["dod"],
            "birth_location":   r["birth_location"],
            "death_location":   r["death_location"],
            "spouse_name":      r["spouse_name"],
            "parents":          r["parents"] or [],
            "children":         r["children"] or [],
            "siblings":         r["siblings"] or [],
            "residence":        r["residence"],
            "source_url":       r["source_url"],
            "confidence":       r["confidence"],
            "relevance":        r["relevance"],
            "relevance_notes":  r["relevance_notes"],
        })

    return 200, {
        "session_id": session_id,
        "count": len(records),
        "records": records,
    }


# ---------------------------------------------------------------------------
# POST /heir/apply-probate-finding
# ---------------------------------------------------------------------------
def apply_probate_finding(data: dict) -> tuple[int, dict]:
    """
    Atomically apply a probate filing as ground truth for a session.

    - Updates the researched person: estate_filed=true, cascade_needed=false,
      cascade_relatives=named_persons, research_phase=complete
    - Retires all pending/processing queue entries NOT in named_persons
      (marks them resolved_by_probate)
    - Queues named_persons that are not yet researched or queued

    Required: session_id, property_id, person_name, named_persons (list of
              {name, relationship_hint})
    Optional: case_number, case_url, had_will
    """
    session_id   = data.get("session_id")
    property_id  = data.get("property_id")
    person_name  = (data.get("person_name") or "").strip()
    named_persons = data.get("named_persons") or []
    case_number  = (data.get("case_number") or "").strip() or None
    case_url     = (data.get("case_url") or "").strip() or None
    had_will     = _parse_bool(data.get("had_will"))

    if not session_id or not property_id or not person_name:
        return 400, {"error": "session_id, property_id, person_name required"}

    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return 400, {"error": f"session_id must be integer, got {session_id!r}"}

    named_names = [p.get("name", "").strip() for p in named_persons if p.get("name", "").strip()]
    named_upper = {n.upper() for n in named_names}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:

            # 1. Update the researched person record
            # cascade_relatives lives inside orchestrator_output JSON blob
            orch_patch = _dump({"cascade_relatives": named_persons, "estate_filed": True, "cascade_needed": False})
            cur.execute("""
                UPDATE heir_research_persons
                SET estate_filed       = true,
                    had_will           = %s,
                    cascade_needed     = false,
                    orchestrator_output = COALESCE(orchestrator_output, '{}'::jsonb) || %s::jsonb,
                    research_phase     = 'complete',
                    updated_at         = NOW()
                WHERE session_id = %s AND UPPER(input_name) = UPPER(%s)
            """, (
                had_will,
                orch_patch,
                session_id, person_name,
            ))

            # 2. Retire queue entries NOT in named_persons
            cur.execute("""
                UPDATE heir_research_queue
                SET status = 'resolved_by_probate', completed_at = NOW()
                WHERE session_id = %s
                  AND status IN ('pending', 'processing')
                  AND UPPER(person_name) != ALL(%s)
            """, (session_id, list(named_upper)))
            retired_count = cur.rowcount

            # 3. Find already-researched and already-queued names
            cur.execute("""
                SELECT UPPER(input_name) AS n FROM heir_research_persons
                WHERE session_id = %s
            """, (session_id,))
            already_researched = {r["n"] for r in cur.fetchall()}

            cur.execute("""
                SELECT UPPER(person_name) AS n FROM heir_research_queue
                WHERE session_id = %s AND status IN ('pending', 'processing')
            """, (session_id,))
            already_queued = {r["n"] for r in cur.fetchall()}

            # 4. Queue named_persons not yet researched or queued
            queued = []
            for p in named_persons:
                name = p.get("name", "").strip()
                if not name:
                    continue
                if name.upper() in already_researched or name.upper() in already_queued:
                    continue
                rel = (p.get("relationship_hint") or "heir").strip()
                cur.execute("""
                    INSERT INTO heir_research_queue
                        (session_id, property_id, person_name, relationship_hint, depth, status)
                    VALUES (%s, %s, %s, %s, 1, 'pending')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """, (session_id, property_id, name, rel))
                row = cur.fetchone()
                if row:
                    queued.append({"name": name, "queue_id": row["id"]})

        conn.commit()

    return 200, {
        "applied": True,
        "person_name": person_name,
        "named_persons": named_names,
        "retired_queue_entries": retired_count,
        "newly_queued": queued,
        "case_number": case_number,
    }


# ---------------------------------------------------------------------------
# POST /heir/write-court-findings
# ---------------------------------------------------------------------------
def write_court_findings(data: dict) -> tuple[int, dict]:
    """
    Persist probate court document findings extracted by Title Attorney.

    Required: session_id, property_id, person_name
    Optional: person_id, case_number, case_url, case_type, estate_filed, had_will,
              probate_family_tree, probate_no_issue, named_persons, documents,
              decedent_name, decedent_dod, document_type, extraction_summary, notes
    Returns:  { finding_id, session_id, person_name }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    person_name = (data.get("person_name") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not property_id:
        return 400, {"error": "property_id is required"}
    if not person_name:
        return 400, {"error": "person_name is required"}

    probate_family_tree = data.get("probate_family_tree") or []
    probate_no_issue    = data.get("probate_no_issue") or []
    named_persons       = data.get("named_persons") or []
    documents           = data.get("documents") or []

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                INSERT INTO heir_court_findings (
                    session_id, property_id, person_id, person_name,
                    case_number, case_url, case_type, estate_filed, had_will,
                    probate_family_tree, probate_no_issue, named_persons, documents,
                    decedent_name, decedent_dod, document_type, extraction_summary, notes
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                RETURNING id
            """, (
                session_id, property_id, data.get("person_id") or None, person_name,
                data.get("case_number") or None,
                data.get("case_url") or None,
                data.get("case_type") or None,
                _parse_bool(data.get("estate_filed")),
                _parse_bool(data.get("had_will")),
                _dump(probate_family_tree),
                _dump(probate_no_issue),
                _dump(named_persons),
                _dump(documents),
                data.get("decedent_name") or None,
                data.get("decedent_dod") or None,
                data.get("document_type") or None,
                data.get("extraction_summary") or None,
                data.get("notes") or None,
            ))
            row = cur.fetchone()
            conn.commit()

    return 200, {
        "finding_id": row["id"],
        "session_id": session_id,
        "person_name": person_name,
        "probate_family_tree_count": len(probate_family_tree),
        "named_persons_count": len(named_persons),
    }


# ---------------------------------------------------------------------------
# POST /heir/court-findings
# ---------------------------------------------------------------------------
def load_court_findings(data: dict) -> tuple[int, dict]:
    """
    Load all court document findings for a session.
    Called by Family Assembler to get probate data for relationship mapping.

    Required: session_id
    Returns:  { session_id, count, findings: [...] }
    """
    session_id = data.get("session_id")
    if not session_id:
        return 400, {"error": "session_id is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("""
                SELECT
                    id, person_name, case_number, case_url, case_type,
                    estate_filed, had_will,
                    probate_family_tree, probate_no_issue, named_persons,
                    decedent_name, decedent_dod, document_type, extraction_summary,
                    notes, created_at
                FROM heir_court_findings
                WHERE session_id = %s
                ORDER BY created_at ASC
            """, (session_id,))
            rows = cur.fetchall()

    findings = []
    for r in rows:
        findings.append({
            "finding_id":           r["id"],
            "person_name":          r["person_name"],
            "case_number":          r["case_number"],
            "case_url":             r["case_url"],
            "case_type":            r["case_type"],
            "estate_filed":         r["estate_filed"],
            "had_will":             r["had_will"],
            "probate_family_tree":  r["probate_family_tree"] or [],
            "probate_no_issue":     r["probate_no_issue"] or [],
            "named_persons":        r["named_persons"] or [],
            "decedent_name":        r["decedent_name"],
            "decedent_dod":         r["decedent_dod"],
            "document_type":        r["document_type"],
            "extraction_summary":   r["extraction_summary"],
            "notes":                r["notes"],
        })

    return 200, {
        "session_id": session_id,
        "count": len(findings),
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# POST /heir/recover-stuck
# ---------------------------------------------------------------------------
def recover_stuck_sessions(data: dict) -> tuple[int, dict]:
    """
    Reset any queue items stuck in 'processing' for longer than the timeout
    (default 30 minutes) back to 'pending' so the session can resume after
    an n8n crash or restart.

    Optional: session_id (limit recovery to one session), timeout_minutes (default 30)
    Returns:  { recovered, session_ids_affected }
    """
    session_id      = data.get("session_id")
    timeout_minutes = int(data.get("timeout_minutes") or 30)

    filters = ["status = 'processing'", f"started_at < NOW() - INTERVAL '{timeout_minutes} minutes'"]
    params: list = []
    if session_id:
        filters.append("session_id = %s")
        params.append(session_id)

    where = " AND ".join(filters)

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(f"""
                UPDATE heir_research_queue
                SET status = 'pending', started_at = NULL
                WHERE {where}
                RETURNING id, session_id, person_name
            """, params)
            rows = cur.fetchall()

            # Also reset session status so the worker loop re-engages
            affected_sessions = list({r["session_id"] for r in rows})
            for sid in affected_sessions:
                cur.execute("""
                    UPDATE heir_research_sessions
                    SET status = 'in_progress', updated_at = NOW()
                    WHERE id = %s AND status NOT IN ('complete', 'manual_review')
                """, (sid,))

            conn.commit()

    return 200, {
        "recovered":            len(rows),
        "session_ids_affected": affected_sessions,
        "items": [{"queue_id": r["id"], "session_id": r["session_id"], "person_name": r["person_name"]} for r in rows],
    }


# ---------------------------------------------------------------------------
# POST /heir/write-voter
# ---------------------------------------------------------------------------
def write_voter_record(data: dict) -> tuple[int, dict]:
    """
    Save NC voter registration lookup results from VSR or Surname Crosser agents.

    Required: session_id, property_id, search_name
    Optional: person_id, search_first, search_last, search_county, search_context,
              records[] (array) — or flat fields for single record
    Returns:  { saved, record_ids, session_id }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    search_name = (data.get("search_name") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return 400, {"error": f"session_id must be an integer, got {session_id!r} — pass the numeric session_id from your input context"}
    if not property_id:
        return 400, {"error": "property_id is required"}
    if not search_name:
        return 400, {"error": "search_name is required"}

    person_id     = data.get("person_id") or None
    search_first  = (data.get("search_first") or "").strip() or None
    search_last   = (data.get("search_last") or "").strip() or None
    search_county = (data.get("search_county") or "").strip() or None
    search_ctx    = (data.get("search_context") or "vital_status_researcher").strip()

    records = data.get("records")
    if not records:
        records = [data]

    saved = []
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                cur.execute("""
                    INSERT INTO heir_voter_records (
                        session_id, property_id, person_id,
                        search_name, search_first, search_last, search_county,
                        ncid, voter_reg_num, full_name, county, city_state_zip,
                        status, status_desc, search_context, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    session_id, property_id, person_id,
                    search_name,
                    search_first or (rec.get("search_first") or "").strip() or None,
                    search_last  or (rec.get("search_last")  or "").strip() or None,
                    search_county or (rec.get("search_county") or "").strip() or None,
                    rec.get("ncid") or None,
                    rec.get("voter_reg_num") or None,
                    rec.get("full_name") or rec.get("name") or None,
                    rec.get("county") or None,
                    rec.get("city_state_zip") or None,
                    rec.get("status") or None,
                    rec.get("status_desc") or None,
                    search_ctx,
                    rec.get("notes") or None,
                ))
                row = cur.fetchone()
                saved.append(row["id"])
            conn.commit()

    return 200, {
        "saved": len(saved),
        "record_ids": saved,
        "session_id": session_id,
        "search_name": search_name,
    }


# ---------------------------------------------------------------------------
# POST /heir/voter-records
# ---------------------------------------------------------------------------
def load_voter_records(data: dict) -> tuple[int, dict]:
    """
    Load voter registration records saved during this session.

    Required: session_id
    Optional: person_id, status (filter by voter status code)
    Returns:  { session_id, count, records }
    """
    session_id = data.get("session_id")
    person_id  = data.get("person_id")
    status     = data.get("status")

    if not session_id:
        return 400, {"error": "session_id is required"}

    filters = ["session_id = %s"]
    params: list = [session_id]
    if person_id:
        filters.append("person_id = %s")
        params.append(person_id)
    if status:
        filters.append("status = %s")
        params.append(status)

    where = " AND ".join(filters)

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(f"""
                SELECT id, person_id, search_name, search_first, search_last,
                       ncid, voter_reg_num, full_name, county, city_state_zip,
                       status, status_desc, search_context, notes, created_at
                FROM heir_voter_records
                WHERE {where}
                ORDER BY created_at ASC
            """, params)
            rows = cur.fetchall()

    records = [
        {
            "id":             r["id"],
            "person_id":      r["person_id"],
            "search_name":    r["search_name"],
            "ncid":           r["ncid"],
            "voter_reg_num":  r["voter_reg_num"],
            "full_name":      r["full_name"],
            "county":         r["county"],
            "city_state_zip": r["city_state_zip"],
            "status":         r["status"],
            "status_desc":    r["status_desc"],
            "search_context": r["search_context"],
            "notes":          r["notes"],
        }
        for r in rows
    ]

    return 200, {"session_id": session_id, "count": len(records), "records": records}


# ---------------------------------------------------------------------------
# POST /heir/write-deed-finding
# ---------------------------------------------------------------------------
def write_deed_finding(data: dict) -> tuple[int, dict]:
    """
    Save a deed finding from the Title Attorney agent.

    Required: session_id, property_id, person_name
    Optional: person_id, county, book, page, doc_type, grantor, grantee,
              recording_date, role, significance, notes
              findings[] array for batch save
    Returns:  { saved, record_ids }
    """
    session_id   = data.get("session_id")
    property_id  = data.get("property_id")
    person_name  = (data.get("person_name") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    if not property_id:
        return 400, {"error": "property_id is required"}
    if not person_name:
        return 400, {"error": "person_name is required"}

    person_id = data.get("person_id") or None

    findings = data.get("findings")
    if not findings:
        findings = [data]

    saved = []
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            for f in findings:
                if not isinstance(f, dict):
                    continue
                cur.execute("""
                    INSERT INTO heir_deed_findings (
                        session_id, property_id, person_id, person_name, county,
                        book, page, doc_type, grantor, grantee, recording_date,
                        role, significance, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    session_id, property_id, person_id,
                    f.get("person_name") or person_name,
                    f.get("county") or None,
                    f.get("book") or None,
                    f.get("page") or None,
                    f.get("doc_type") or None,
                    f.get("grantor") or None,
                    f.get("grantee") or None,
                    f.get("recording_date") or None,
                    f.get("role") or None,
                    f.get("significance") or None,
                    f.get("notes") or None,
                ))
                row = cur.fetchone()
                saved.append(row["id"])
            conn.commit()

    return 200, {"saved": len(saved), "record_ids": saved, "session_id": session_id}


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


# ---------------------------------------------------------------------------
# POST /heir/upsert-person
# ---------------------------------------------------------------------------
def upsert_person(data: dict) -> tuple[int, dict]:
    """
    INSERT or UPDATE a person in heir_research_persons.
    If a record with (session_id, input_name) already exists, UPDATE it.
    Otherwise INSERT a new row.

    This enables progressive DB writes during research:
      - Phase 1 (SkipGenie): matched_identity, cascade_relatives, level
      - Phase 2 (VSR): vital_status, voter_status
      - Phase 3 (ODD): obituary_url, obituary_text
      - Phase 4 (Title Attorney): estate_filed, had_will
      - Final (Person Compiler): cascade_needed, claim_sources, deceased_facts

    Required: session_id, property_id, input_name
    Returns: { person_id, session_id, property_id, input_name, created }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    input_name  = (data.get("input_name") or data.get("name") or "").strip()

    if not session_id:
        return 400, {"error": "session_id is required"}
    try:
        session_id = int(session_id)
    except (ValueError, TypeError):
        return 400, {"error": f"session_id must be an integer, got {session_id!r}"}
    if not property_id:
        return 400, {"error": "property_id is required"}
    if not input_name:
        return 400, {"error": "input_name or name is required"}

    identity      = data.get("matched_identity") or {}
    deceased      = data.get("deceased_facts") or {}
    obituary_url  = (data.get("obituary_url") or "").strip() or None
    obituary_text = (data.get("obituary_text") or "").strip() or None
    claim_sources = data.get("claim_sources") or {}
    maiden_name   = (data.get("maiden_name") or "").strip() or None
    vital_status  = (data.get("vital_status") or "").strip() or None
    vital_status_paused = bool(data.get("vital_status_paused", False))
    level         = int(data.get("level") or 1)
    branch_id     = (data.get("branch_id") or "").strip() or None
    parent_person_id = data.get("parent_person_id") or None
    cascade_needed = data.get("cascade_needed")
    research_phase = (data.get("research_phase") or "pending").strip()
    queue_id      = data.get("queue_id") or None
    relationship_hint = (data.get("relationship_hint") or "").strip() or None
    obituary_named_survivors = data.get("obituary_named_survivors") or []
    ancestry_named_children  = data.get("ancestry_named_children") or []

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            # Check for existing record
            cur.execute("""
                SELECT id FROM heir_research_persons
                WHERE session_id = %s AND UPPER(input_name) = UPPER(%s)
                LIMIT 1
            """, (session_id, input_name))
            existing = cur.fetchone()

            if existing:
                person_id = existing["id"]
                # Build partial UPDATE — only set fields that were provided
                set_clauses = ["updated_at = NOW()"]
                params: list = []

                def _maybe_set(col: str, val) -> None:
                    if val is not None:
                        set_clauses.append(f"{col} = %s")
                        params.append(val)

                _maybe_set("relationship_hint", relationship_hint)
                _maybe_set("matched_full_name",  identity.get("full_name"))
                _maybe_set("matched_dob",        identity.get("dob"))
                _maybe_set("matched_dod",        identity.get("dod"))
                _maybe_set("matched_address",    identity.get("address"))
                _maybe_set("match_confidence",   identity.get("confidence"))
                _maybe_set("vital_status",       vital_status)
                _maybe_set("date_of_death",      deceased.get("date_of_death"))
                _maybe_set("marital_status_at_death", deceased.get("marital_status_at_death"))
                _maybe_set("surviving_spouse_name",   deceased.get("surviving_spouse_name"))
                if deceased.get("estate_filed") is not None:
                    set_clauses.append("estate_filed = %s")
                    params.append(_parse_bool(deceased["estate_filed"]))
                if deceased.get("had_will") is not None:
                    set_clauses.append("had_will = %s")
                    params.append(_parse_bool(deceased["had_will"]))
                if deceased.get("family_alive_at_death") is not None:
                    set_clauses.append("family_alive_at_death = %s")
                    params.append(_dump(deceased["family_alive_at_death"]))
                if data.get("deed_transfers") is not None:
                    set_clauses.append("deed_transfers = %s")
                    params.append(_dump(data["deed_transfers"]))
                if cascade_needed is not None:
                    set_clauses.append("cascade_needed = %s")
                    params.append(bool(cascade_needed))
                _maybe_set("obituary_url",  obituary_url)
                _maybe_set("obituary_text", obituary_text)
                if claim_sources:
                    set_clauses.append("claim_sources = %s")
                    params.append(_dump(claim_sources))
                _maybe_set("maiden_name",   maiden_name)
                if vital_status_paused:
                    set_clauses.append("vital_status_paused = %s")
                    params.append(vital_status_paused)
                _maybe_set("research_phase", research_phase)
                if obituary_named_survivors:
                    set_clauses.append("obituary_named_survivors = %s")
                    params.append(_dump(obituary_named_survivors))
                if ancestry_named_children:
                    set_clauses.append("ancestry_named_children = %s")
                    params.append(_dump(ancestry_named_children))
                if branch_id:
                    set_clauses.append("branch_id = %s")
                    params.append(branch_id)
                if parent_person_id:
                    set_clauses.append("parent_person_id = %s")
                    params.append(parent_person_id)

                if len(set_clauses) > 1:
                    params.append(person_id)
                    cur.execute(
                        f"UPDATE heir_research_persons SET {', '.join(set_clauses)} WHERE id = %s",
                        params
                    )
                created = False
            else:
                # INSERT new record
                cur.execute("""
                    INSERT INTO heir_research_persons (
                        session_id, property_id,
                        input_name, relationship_hint,
                        matched_full_name, matched_dob, matched_dod, matched_address, match_confidence,
                        vital_status, vital_status_paused,
                        date_of_death, marital_status_at_death, surviving_spouse_name,
                        estate_filed, had_will, family_alive_at_death,
                        deed_transfers, cascade_needed,
                        obituary_url, obituary_text, claim_sources,
                        maiden_name, level, branch_id, parent_person_id,
                        research_phase, obituary_named_survivors, ancestry_named_children
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING id
                """, (
                    session_id, property_id,
                    input_name, relationship_hint,
                    identity.get("full_name"), identity.get("dob"), identity.get("dod"),
                    identity.get("address"), identity.get("confidence"),
                    vital_status, vital_status_paused,
                    deceased.get("date_of_death"), deceased.get("marital_status_at_death"),
                    deceased.get("surviving_spouse_name"),
                    _parse_bool(deceased.get("estate_filed")), _parse_bool(deceased.get("had_will")),
                    _dump(deceased.get("family_alive_at_death") or []),
                    _dump(data.get("deed_transfers") or []),
                    bool(cascade_needed) if cascade_needed is not None else False,
                    obituary_url, obituary_text,
                    _dump(claim_sources),
                    maiden_name, level, branch_id, parent_person_id,
                    research_phase,
                    _dump(obituary_named_survivors),
                    _dump(ancestry_named_children),
                ))
                row = cur.fetchone()
                person_id = row["id"]
                created = True

            conn.commit()

    # Echo back the key context fields so subsequent nodes can use them
    return 200, {
        "person_id":        person_id,
        "session_id":       session_id,
        "property_id":      property_id,
        "input_name":       input_name,
        "created":          created,
        # Echo fields that callers pass forward in the chain
        "name":             input_name,
        "queue_id":         queue_id,
        "relationship_hint": relationship_hint or "",
        "vital_status":     vital_status or "unknown",
        "matched_identity": identity,
        "cascade_relatives": data.get("cascade_relatives") or [],
        "vital_status_hint": data.get("vital_status_hint") or "unknown",
        "loop_context":     data.get("loop_context") or "worker",
    }


# ---------------------------------------------------------------------------
# POST /heir/load-person
# ---------------------------------------------------------------------------
def load_person(data: dict) -> tuple[int, dict]:
    """
    Load a single person record by person_id or by (session_id + input_name).

    Required: person_id  OR  (session_id + input_name)
    Returns: { person: {...full record...} }
    """
    person_id   = data.get("person_id")
    session_id  = data.get("session_id")
    input_name  = (data.get("input_name") or data.get("name") or "").strip()

    if not person_id and not (session_id and input_name):
        return 400, {"error": "person_id or (session_id + input_name) is required"}

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            if person_id:
                cur.execute("SELECT * FROM heir_research_persons WHERE id = %s", (person_id,))
            else:
                cur.execute("""
                    SELECT * FROM heir_research_persons
                    WHERE session_id = %s AND UPPER(input_name) = UPPER(%s)
                    ORDER BY created_at DESC LIMIT 1
                """, (session_id, input_name))
            row = cur.fetchone()

    if not row:
        return 404, {"error": "person not found"}

    orch_out = row.get("orchestrator_output") or {}
    if isinstance(orch_out, str):
        try:
            orch_out = json.loads(orch_out)
        except Exception:
            orch_out = {}

    return 200, {
        "person": {
            "id":               row["id"],
            "session_id":       row["session_id"],
            "property_id":      row["property_id"],
            "input_name":       row["input_name"],
            "relationship_hint": row["relationship_hint"],
            "matched_full_name": row["matched_full_name"],
            "matched_dob":       row["matched_dob"],
            "matched_dod":       row["matched_dod"],
            "matched_address":   row["matched_address"],
            "match_confidence":  row["match_confidence"],
            "vital_status":      row["vital_status"],
            "vital_status_paused": row.get("vital_status_paused", False),
            "date_of_death":     row["date_of_death"],
            "marital_status_at_death": row["marital_status_at_death"],
            "surviving_spouse_name":   row["surviving_spouse_name"],
            "estate_filed":      row["estate_filed"],
            "had_will":          row["had_will"],
            "family_alive_at_death": row["family_alive_at_death"] or [],
            "deed_transfers":    row["deed_transfers"] or [],
            "cascade_needed":    row["cascade_needed"],
            "obituary_url":      row["obituary_url"],
            "obituary_text":     row["obituary_text"],
            "claim_sources":     row["claim_sources"] or {},
            "maiden_name":       row.get("maiden_name"),
            "level":             row.get("level", 1),
            "branch_id":         row.get("branch_id"),
            "parent_person_id":  row.get("parent_person_id"),
            "research_phase":    row.get("research_phase", "pending"),
            "obituary_named_survivors": row.get("obituary_named_survivors") or [],
            "ancestry_named_children":  row.get("ancestry_named_children") or [],
            "cascade_relatives": orch_out.get("cascade_relatives") or [],
            "branch_status":     row["branch_status"],
            "share_fraction":    row["share_fraction"],
            "notes":             row["notes"],
            "created_at":        row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at":        row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    }
