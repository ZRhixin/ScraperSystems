"""
Claude Vision extraction — Prompt 2 (Document Processing).
Sends PDF pages as images + parcel reference, returns structured document_extractions JSON.
"""
import base64
import json
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_SYSTEM_PROMPT = """You are extracting structured data from a recorded county document (deed, mortgage, court filing, etc.) using its OCR text or document images. You will also judge whether this document pertains to a specific parcel.

INPUTS (provided in user message as JSON at the end):
{
  "ocr_confidence": 0.0 to 1.0,
  "parcel_reference": {
    "short_legal_raw": "...",
    "subdivision": "...",
    "block": "...",
    "lot": "...",
    "plat_book": "...",
    "plat_page": "..."
  }
}

OUTPUT — return ONLY this JSON object. No markdown. No prose. No code fences.

{
  "document_type": "warranty_deed | quitclaim | corrective_deed | deed_of_distribution | deed_of_trust | mortgage | release | lis_pendens | judgment_lien | affidavit_of_death | estate_order | other",
  "grantor_names": [],
  "grantee_names": [],
  "recorded_date": null,
  "instrument_date": null,
  "book": null,
  "page": null,
  "instrument_number": null,
  "vesting_language": null,
  "legal_description_full": null,
  "legal_description_short": null,
  "plat_book": null,
  "plat_page": null,
  "conveys_multiple_parcels": false,
  "parcels_conveyed_count": 1,
  "references_prior_deed_book": null,
  "references_prior_deed_page": null,
  "references_prior_deed_language": null,
  "legal_match_to_parcel": "high | medium | low | none",
  "legal_match_method": "plat_reference | metes_bounds | narrative | chain_logic_only | none",
  "legal_match_notes": "",
  "summary": "",
  "flags": [],
  "extraction_confidence": "high | medium | low"
}

RULES:

1. Every field must be grounded in the document content. Do not infer beyond what is visible.

2. If ocr_confidence < 0.75, set extraction_confidence = "low" and add flag "low_input_ocr_confidence".

3. Grantor/grantee name arrays preserve names exactly as written. If a deed says "John Smith and Mary Smith, husband and wife," include that full phrase — marital status language is critical for vesting later.

4. vesting_language: capture the exact verbatim language about how the grantees hold title. Examples: "as tenants by the entirety," "as joint tenants with right of survivorship," "husband and wife," "as tenants in common." If no such language is present, null.

5. Legal description matching:
   - "high" = plat book + page + lot all match the parcel_reference, OR metes-and-bounds description explicitly confirms the same parcel
   - "medium" = subdivision name and lot number match but no plat reference available, OR short legal matches narrative
   - "low" = descriptions are similar but real ambiguity exists, OR deed conveys multiple parcels and parcel_reference is one of them
   - "none" = descriptions clearly do not correspond

6. conveys_multiple_parcels = true if the deed conveys more than one parcel. Set parcels_conveyed_count to the count.

7. references_prior_deed_*: if the deed says something like "being the same property conveyed to grantor by deed recorded at Book X Page Y," populate these fields AND copy the exact referencing language into references_prior_deed_language. This is critical for chain-back investigation.

8. summary: 1-2 sentences, plain language. Example: "Warranty deed from W.W. Holding and wife Josephine to Viola Hicks conveying Lots 19 and 19A of Country Club Estates; recorded March 1941 at Book 860 Page 53."

9. flags — raise each that applies:
   - "low_ocr_readability" (text is unreadable in places)
   - "low_input_ocr_confidence" (ocr_confidence below 0.75)
   - "handwritten_document"
   - "cursive_or_old_formatting"
   - "multi_parcel_conveyance"
   - "corrective_or_quitclaim_deed"
   - "legal_description_mismatch"
   - "references_unretrieved_prior_deed"
   - "missing_critical_field"
   - "ambiguous_vesting_language"

10. When uncertain about any field, return null and add an appropriate flag. Do not guess."""


def extract_from_images(
    images: list[bytes],
    parcel_reference: dict,
    ocr_confidence: float = 1.0,
) -> dict:
    """
    Send PDF page images to Claude and return structured document_extractions dict.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    content = []

    for i, img_bytes in enumerate(images):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(img_bytes).decode("utf-8"),
            },
        })
        content.append({
            "type": "text",
            "text": f"[Page {i + 1} of {len(images)}]",
        })

    content.append({
        "type": "text",
        "text": json.dumps({
            "ocr_confidence": ocr_confidence,
            "parcel_reference": parcel_reference,
        }),
    })

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=0.2,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wrapped it anyway
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def extract_from_text(
    text: str,
    parcel_reference: dict,
    ocr_confidence: float = 1.0,
) -> dict:
    """
    Send extracted text (from a text-layer PDF) to Claude.
    Used when pdf_has_text_layer() is True — cheaper than Vision.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    user_message = json.dumps({
        "ocr_text": text,
        "ocr_confidence": ocr_confidence,
        "parcel_reference": parcel_reference,
    })

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=0.2,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)
