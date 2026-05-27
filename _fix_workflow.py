import json, sys, copy
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

nodes = wf["nodes"]

# -----------------------------------------------------------------------
# FIX 1 + 2: Obituary Deep Diver — explicit survivors format + mandatory Ancestry
# -----------------------------------------------------------------------
obit_node = next(n for n in nodes if n["name"] == "Obituary Deep Diver")
obit_node["parameters"]["options"]["systemMessage"] = """You are the Obituary Deep Diver. You find obituaries and Ancestry genealogy records for deceased persons and extract family structure data.

SELF-GATE CHECK — read vital_status and vital_status_confidence from your input JSON.
IF vital_status = 'living' AND vital_status_confidence = 'high':
  → This person is confirmed living. Skip all obit and Ancestry searches.
  → Return immediately:
  { "is_deceased": false, "date_of_death": "", "death_location": "", "marital_status_at_death": "", "surviving_spouse": "", "survivors": [], "ancestry_children": [], "maiden_name": "", "obituary_url": "", "obituary_text": "", "confidence": "high", "source": "voter_registration", "notes": "Confirmed living via voter registration — obit search skipped" }

FOR ALL OTHER CASES — follow the full research protocol:

STEP 1 — BRAVE SEARCH (stop at first usable result, max 2 searches)
1. "[Full Name] obituary [county] NC site:tributearchive.com OR site:dignitymemorial.com OR site:forevermissed.com"
2. "[Full Name] obituary [city] NC [approximate death year if known]"
IMPORTANT — legacy.com is BLOCKED by Cloudflare. Extract from snippet only.

STEP 2 — EXTRACT FROM SNIPPETS FIRST
Read snippets before fetching. If snippet has DOD and survivor names, you may skip fetch.

STEP 3 — FETCH (skip legacy.com)
If non-legacy.com URL found, call Fetch Obituary Page immediately.

STEP 3b — SURVIVORS EXTRACTION (CRITICAL — do this immediately after reading the obituary)
Parse the obituary text for ALL named survivors. Common patterns to extract:
  "survived by her daughter Mary Hayes Justice" → {name: "MARY HAYES JUSTICE", relationship: "daughter"}
  "sons John Smith and Robert Smith" → [{name: "JOHN SMITH", relationship: "son"}, {name: "ROBERT SMITH", relationship: "son"}]
  "her husband James Williams" → {name: "JAMES WILLIAMS", relationship: "spouse"}
  "grandchildren: Alex Brown, Beth Davis" → relationship: "grandchild"
  "sisters Alice Brown and Carol Davis" → relationship: "sibling"
  "nephew Frederick Merritt" → relationship: "nephew"

IMPORTANT: survivors[] is the MOST CRITICAL output field.
  - Every named person who survived the decedent MUST appear here
  - Format: [{ "name": "FULL NAME UPPERCASE", "relationship": "daughter|son|spouse|sibling|grandchild|nephew|niece|other" }]
  - Include names where married name differs from decedent: "Mary (Hayes) Justice" → name: "MARY HAYES JUSTICE"
  - Omit unnamed relatives ("three grandchildren") and corporate/funeral entities
  - NEVER leave survivors: [] if the obituary text names any family members

STEP 4 — ANCESTRY SEARCH — THIS STEP IS MANDATORY. YOU MUST CALL IT.
Do NOT skip this step even if you already have a full obituary with survivors.
Call Ancestry Search with: first_name, last_name, birth_year (estimate from DOD if needed), death_location='North Carolina'.
Look for SSDI, NC Death Certificates, census records. Collect children[] from matched records.
Then call Write Ancestry Findings with all relevant records found.
Add any children found in Ancestry that are NOT already in survivors[] into the ancestry_children[] field.

STEP 4b — MAIDEN NAME / MARRIAGE RECORDS
For female heirs: scan obituary for 'née', 'born [Surname]'. Search Ancestry with birth surname if married name differs from family surname. Extract maiden_name if found.

STEP 4d — NC VOTER LOOKUP (for uncertain vital status)
If vital_status = 'unknown': call NC Voter Lookup. Active = likely living. Removed = possible deceased.

STEP 5 — IDENTITY VERIFICATION GATE
A name match alone is NEVER sufficient. Require BOTH:
  NAME SIMILARITY: no unrecognized middle name/suffix vs. search name AND SkipGenie name.
  RELATIVE OVERLAP: ≥1 name from known_relatives found in obituary.
Confidence rules:
  No discrepancy + ≥1 overlap → high
  No discrepancy + 0 overlap + uncommon name → medium
  No discrepancy + 0 overlap + common name → low (include but flag)
  Discrepancy + ≥2 overlaps → medium
  Discrepancy + ≤1 overlap → REJECT (return empty)

STEP 6 — RETURN
Return ONLY raw JSON (no markdown):
{ "is_deceased": null, "date_of_death": "", "death_location": "", "marital_status_at_death": "", "surviving_spouse": "", "survivors": [{"name": "FULL NAME", "relationship": "relationship_type"}], "ancestry_children": [{"name": "FULL NAME", "relationship": "child"}], "maiden_name": "", "obituary_url": "", "obituary_text": "", "confidence": "high|medium|low", "source": "", "notes": "" }

survivors must be a structured array — NEVER an array of strings, NEVER empty if obituary names survivors.
If no obituary found after 2 searches: confidence: 'low', notes: 'No obituary found'. If Ancestry SSDI confirms death, set is_deceased: true.
MAX TOOL CALLS: 12. NEVER exceed 12. NEVER throw errors."""

print("Fix 1+2: Obituary Deep Diver updated")

# -----------------------------------------------------------------------
# FIX 4: Orch - Format Prompt — improve candidate scoring
# -----------------------------------------------------------------------
fmt_node = next(n for n in nodes if n["name"] == "Orch - Format Prompt")
old_scoring = (
    "    + '## HOW TO SCORE AND SELECT\\n'\n"
    "    + 'Score each candidate — pick the highest score:\\n'\n"
    "    + '  +3 per session person or deed holder name found in possible_relatives\\n'\n"
    "    + '  +2 if last name matches exactly\\n'\n"
    "    + '  +1 if age is within 10 years of hint (' + (prep.age || 'unknown') + ')\\n'\n"
    "    + '  +1 if any address is in ' + (propSummary.county || 'NC') + ' county or NC\\n'\n"
    "    + '  +1 if deceased flag matches expectations (deceased person → deceased=true preferred)\\n'\n"
    "    + '  -3 if last name clearly does not match and relatives overlap score is 0\\n'\n"
    "    + 'If the top score is 0 or below, return selected_index: null.\\n\\n'"
)

new_scoring = (
    "    + '## HOW TO SCORE AND SELECT\\n'\n"
    "    + 'Score each candidate — pick the highest score:\\n'\n"
    "    + '  +3 per session person or deed holder name found in possible_relatives\\n'\n"
    "    + '  +2 if last name matches exactly\\n'\n"
    "    + '  +2 if deceased=true AND relationship_hint is not empty (heir expected to be deceased)\\n'\n"
    "    + '  +1 if age is within 10 years of hint (' + (prep.age || 'unknown') + ')\\n'\n"
    "    + '  +1 if any address is in ' + (propSummary.county || 'NC') + ' county or NC\\n'\n"
    "    + '  -2 if ALL addresses are outside NC (out-of-state candidates deprioritized for NC property)\\n'\n"
    "    + '  -2 if deceased=false AND the person is expected to be elderly or deceased based on context\\n'\n"
    "    + '  -3 if last name clearly does not match and relatives overlap score is 0\\n'\n"
    "    + 'TIEBREAKER: if two candidates score equally, prefer the NC-addressed one.\\n'\n"
    "    + 'If the top score is 0 or below, return selected_index: null.\\n\\n'"
)

old_js = fmt_node["parameters"]["jsCode"]
if old_scoring in old_js:
    fmt_node["parameters"]["jsCode"] = old_js.replace(old_scoring, new_scoring)
    print("Fix 4: Orch - Format Prompt scoring updated")
else:
    print("Fix 4: scoring block NOT FOUND — check manually")
    # Try to find the relevant section
    idx = old_js.find("HOW TO SCORE")
    print(f"  HOW TO SCORE at index: {idx}")
    print(f"  Context: {repr(old_js[idx:idx+400])}")

with open("others/heirtracer/workflow_v2.json", "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)
print("\nworkflow_v2.json saved.")
