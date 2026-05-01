"""
Quick smoke test for the document-read subroutine.
Usage: python -m document_read.test_subroutine

Requires:
  - A property row in the DB (creates one if needed)
  - A publicly accessible PDF URL to test against
"""
import json
import psycopg2
from database.db import get_conn
from document_read.subroutine import read_document_from_url

# --- Test parcel reference (631 East Nelson Ave, Wake Forest NC) ---
PARCEL_REFERENCE = {
    "short_legal_raw": "LOT 19 BLK 7 COUNTRY CLUB ESTATES",
    "subdivision": "COUNTRY CLUB ESTATES",
    "block": "7",
    "lot": "19",
    "plat_book": None,
    "plat_page": None,
}

# --- A sample PDF URL (replace with a real Wake ROD document URL) ---
# To get one: search rodrecords.wake.gov, open any deed detail, copy the image/PDF link
TEST_PDF_URL = ""  # <-- fill this in before running


def _get_or_create_test_property() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO properties (parcel_id, county, state_code, address)
        VALUES ('0078899', 'Wake', 'NC', '631 E NELSON AVE, WAKE FOREST NC 27587')
        ON CONFLICT (parcel_id, county, state_code) DO UPDATE SET updated_at = NOW()
        RETURNING id
        """
    )
    prop_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return prop_id


def run():
    if not TEST_PDF_URL:
        print("Set TEST_PDF_URL in this file before running.")
        return

    print("Creating/fetching test property...")
    property_id = _get_or_create_test_property()
    print(f"  property_id = {property_id}")

    print(f"Running document-read on: {TEST_PDF_URL}")
    result = read_document_from_url(
        url=TEST_PDF_URL,
        property_id=property_id,
        parcel_reference=PARCEL_REFERENCE,
        capture_table="rod_captures",
        capture_type="document_image",
    )

    print("\n--- Extraction result ---")
    print(json.dumps(result, indent=2, default=str))
    print(f"\nExtraction ID: {result.get('_extraction_id')}")
    print(f"Document type: {result.get('document_type')}")
    print(f"Grantor: {result.get('grantor_names')}")
    print(f"Grantee: {result.get('grantee_names')}")
    print(f"Legal match: {result.get('legal_match_to_parcel')}")
    print(f"Flags: {result.get('flags')}")


if __name__ == "__main__":
    run()
