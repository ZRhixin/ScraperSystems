"""
Claude extraction for probate and court filing documents.
Separate from document_read/extract.py which is tuned for deeds.

Returns a family-tree-focused structure usable directly by the heir tracer.
"""
import base64
import json
import os

import anthropic
from dotenv import load_dotenv

from document_read.pdf import pdf_bytes_to_images, pdf_has_text_layer, pdf_extract_text

load_dotenv()

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_SYSTEM_PROMPT = """You are extracting heir and family structure data from a probate court document (petition, family tree, inventory, order of distribution, or similar filing).

Your goal is to find: who the decedent is, who their heirs/beneficiaries are, and the family tree structure (parent→children relationships with deceased/living status).

OUTPUT — return ONLY this JSON object. No markdown. No prose. No code fences.

{
  "document_type": "family_tree | petition_for_administration | inventory | order_of_distribution | affidavit | application | other",
  "decedent_name": "",
  "decedent_dod": "",
  "estate_type": "intestate | testate | unknown",
  "named_persons": [
    {
      "name": "",
      "relationship": "child | grandchild | great_grandchild | spouse | sibling | parent | great_nephew | great_niece | nephew | niece | beneficiary | executor | unknown",
      "vital_status": "living | deceased | unknown",
      "has_issue": null,
      "share": "",
      "address": "",
      "notes": ""
    }
  ],
  "family_tree": [
    {
      "name": "",
      "generation": 0,
      "parent_of": [],
      "vital_status": "living | deceased | unknown",
      "has_issue": null,
      "notes": ""
    }
  ],
  "summary": "",
  "extraction_confidence": "high | medium | low",
  "flags": []
}

RULES:

1. named_persons — every person mentioned by name in the document. Use the most specific relationship you can infer.
   - "great nephew" of the decedent → relationship = "great_nephew"
   - "daughter" → relationship = "child"
   - "executor" / "administrator" → relationship = "executor"

2. family_tree — the hierarchical structure. generation=0 is the root decedent.
   - generation 1 = decedent's children
   - generation 2 = grandchildren
   - parent_of = list of names of that person's children mentioned in the document
   - has_issue: true if document confirms children exist, false if confirmed no children, null if not stated
   - CRITICAL: if the document says "[Name] has no children" or "[Name] died without issue" → has_issue=false

3. vital_status — use explicit language: "predeceased", "deceased", "died" = deceased. Living persons are usually described without qualification.

4. If a "Family Tree" exhibit is attached, extract it fully into family_tree[].

5. has_issue=false is extremely valuable for heir tracing — always set it when the document explicitly states no children.

6. summary — 2-3 sentences covering: who died, what the key heir relationships are, and any explicit "no children" findings.

7. flags — raise each that applies:
   - "family_tree_attached" (a formal family tree document is included)
   - "no_issue_confirmed" (at least one person confirmed to have no children)
   - "minor_heirs" (any heir is a minor)
   - "missing_persons" (any heir's whereabouts unknown)
   - "out_of_state_heirs" (any heir lives outside NC)
   - "contested" (any objections or disputes noted)
   - "multiple_documents" (more than one document in this PDF)
   - "low_ocr_readability"
"""


def extract_probate(pdf_bytes: bytes) -> dict:
    """
    Run Claude extraction on a probate court document PDF.
    Returns the structured dict with family_tree and named_persons.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if pdf_has_text_layer(pdf_bytes):
        text, confidence = pdf_extract_text(pdf_bytes)
        user_content = json.dumps({
            "ocr_text": text,
            "ocr_confidence": confidence,
            "task": "Extract all heir/family structure data from this probate document.",
        })
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=0.1,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    else:
        images = pdf_bytes_to_images(pdf_bytes)
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
            content.append({"type": "text", "text": f"[Page {i + 1} of {len(images)}]"})
        content.append({
            "type": "text",
            "text": "Extract all heir/family structure data from this probate document. Return only the JSON.",
        })
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=0.1,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)
