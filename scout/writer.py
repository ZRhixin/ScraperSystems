"""
Scout writer — receives Prompt 1 output and writes to scraper DB.

Writes:
  - properties row (upsert on parcel_id + county + state_code)
  - appraiser_transfer_history rows (one per transfer, skip duplicates)
  - sets properties.scout_completed_at

Input shape (Prompt 1 output):
{
  "parcel_id": "",
  "secondary_parcel_id": null,
  "property_address": {"street": null, "city": null, "state": null, "zip": null},
  "county": "",
  "current_owners": [{"raw_name": "", "owner_order": 1}],
  "short_legal_raw": null,
  "short_legal_parsed": {"subdivision": null, "block": null, "lot": null},
  "plat_book": null,
  "plat_page": null,
  "full_legal_description": null,
  "last_sale_date": null,
  "transfer_history": [
    {
      "book": null, "page": null, "instrument_number": null,
      "recorded_date": null, "grantor_raw": null,
      "grantee_raw": null, "short_legal_raw": null
    }
  ],
  "extraction_notes": []
}
"""
import json
from datetime import datetime

from database.db import get_conn


def write(data: dict) -> dict:
    """
    Upsert property + insert transfer history rows.
    Returns {"property_id": int, "created": bool, "transfer_count": int}
    """
    parcel_id  = (data.get("parcel_id") or "").strip()
    county     = (data.get("county") or "").strip()
    state_code = (data.get("state_code") or "NC").strip().upper()

    if not parcel_id or not county:
        raise ValueError("parcel_id and county are required")

    addr       = _coerce_dict(data.get("property_address"))
    parsed     = _coerce_dict(data.get("short_legal_parsed"))
    last_sale  = _parse_date(data.get("last_sale_date"))

    conn = get_conn()
    try:
        cur = conn.cursor()

        # Upsert properties
        cur.execute(
            """
            INSERT INTO properties (
                parcel_id, county, state_code,
                address, street, city, state, zip,
                secondary_parcel_id,
                current_owners,
                short_legal_raw, subdivision, block, lot,
                plat_book, plat_page,
                full_legal_description,
                last_sale_date,
                extraction_notes,
                scout_completed_at,
                updated_at
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s,
                %s,
                %s, %s, %s, %s,
                %s, %s,
                %s,
                %s,
                %s,
                NOW(), NOW()
            )
            ON CONFLICT (parcel_id, county, state_code) DO UPDATE SET
                address               = EXCLUDED.address,
                street                = EXCLUDED.street,
                city                  = EXCLUDED.city,
                state                 = EXCLUDED.state,
                zip                   = EXCLUDED.zip,
                secondary_parcel_id   = EXCLUDED.secondary_parcel_id,
                current_owners        = EXCLUDED.current_owners,
                short_legal_raw       = EXCLUDED.short_legal_raw,
                subdivision           = EXCLUDED.subdivision,
                block                 = EXCLUDED.block,
                lot                   = EXCLUDED.lot,
                plat_book             = EXCLUDED.plat_book,
                plat_page             = EXCLUDED.plat_page,
                full_legal_description= EXCLUDED.full_legal_description,
                last_sale_date        = EXCLUDED.last_sale_date,
                extraction_notes      = EXCLUDED.extraction_notes,
                scout_completed_at    = NOW(),
                updated_at            = NOW()
            RETURNING id, (xmax = 0) AS created
            """,
            (
                parcel_id, county, state_code,
                _full_address(addr), addr.get("street"), addr.get("city"),
                addr.get("state"), addr.get("zip"),
                data.get("secondary_parcel_id"),
                json.dumps(_coerce_list(data.get("current_owners"))),
                data.get("short_legal_raw"),
                parsed.get("subdivision"), parsed.get("block"), parsed.get("lot"),
                data.get("plat_book"), data.get("plat_page"),
                data.get("full_legal_description"),
                last_sale,
                json.dumps(data.get("extraction_notes") or []),
            ),
        )

        row = cur.fetchone()
        property_id = row[0]
        created     = row[1]

        # Insert transfer history — skip rows with no book/page AND no instrument_number
        transfers = _coerce_list(data.get("transfer_history"))
        inserted  = 0

        for t in transfers:
            book   = (t.get("book") or "").strip() or None
            page   = (t.get("page") or "").strip() or None
            inst   = (t.get("instrument_number") or "").strip() or None

            if not book and not page and not inst:
                continue  # nothing to identify this deed by

            # Skip exact duplicates already in the table for this property
            cur.execute(
                """
                SELECT 1 FROM appraiser_transfer_history
                WHERE property_id = %s
                  AND (book IS NOT DISTINCT FROM %s)
                  AND (page IS NOT DISTINCT FROM %s)
                  AND (instrument_number IS NOT DISTINCT FROM %s)
                LIMIT 1
                """,
                (property_id, book, page, inst),
            )
            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO appraiser_transfer_history
                    (property_id, book, page, instrument_number, recorded_date,
                     grantor_raw, grantee_raw, short_legal_raw, verification_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    property_id,
                    book, page, inst,
                    _parse_date(t.get("recorded_date")),
                    t.get("grantor_raw"),
                    t.get("grantee_raw"),
                    t.get("short_legal_raw"),
                ),
            )
            inserted += 1

        conn.commit()
        return {
            "property_id":    property_id,
            "created":        created,
            "transfer_count": inserted,
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _coerce_dict(value) -> dict:
    """Return a dict — parse JSON string if needed, fall back to {}."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _coerce_list(value) -> list:
    """Return a list — parse JSON string if needed, fall back to []."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _full_address(addr: dict) -> str | None:
    parts = filter(None, [
        addr.get("street"),
        addr.get("city"),
        addr.get("state"),
        addr.get("zip"),
    ])
    result = ", ".join(parts)
    return result or None


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None
