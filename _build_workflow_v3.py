"""
Build workflow_v3_local.json — the v3 heir tracer workflow.

Key changes from v2:
1. Create Heir Session runs FIRST (before Root Research) so session_id exists for DB writes
2. Root Research Agent gets full pipeline (Brave Search, court, voter writes)
3. Write Root Person to DB after Root Research
4. Branch Planner Agent seeds the queue (replaces JS in Seed Queue) using NC Ch. 29
5. Orch chain replaced: SkipGenie Analyzer Agent selects best SG candidate
6. Vital Status Gate: unknown → flag person, skip rest of research
7. Person Compiler JS → Person Compiler Agent (reads from DB, smarter decisions)
8. Queue Cascade Relatives JS → Branch Decision Agent (applies NC Ch. 29)
9. All model nodes: gpt-5-mini
10. Upsert Person SG creates person record early in loop (person_id available sooner)
"""
import json
import uuid
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ─── helpers ────────────────────────────────────────────────────────────────

OPENAI_CRED = {"openAiApi": {"id": "BRiOORCgq1BegRm2", "name": "OpenAI account"}}
BASE = "http://127.0.0.1:8000"
LOCALHOST_N8N = "http://localhost:5678"

def nid(tag: str) -> str:
    """Generate a stable UUID from a tag for reproducible builds."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"heirtracer-v3-{tag}"))

def gpt_model(name: str, node_id: str) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
        "typeVersion": 1.2,
        "position": [0, 0],
        "parameters": {
            "model": {
                "__rl": True,
                "value": "gpt-5-mini",
                "mode": "list",
                "cachedResultName": "gpt-5-mini",
            },
            "options": {},
        },
        "credentials": OPENAI_CRED,
    }

def agent_node(name: str, node_id: str, system_msg: str, text_expr: str) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 3.1,
        "position": [0, 0],
        "parameters": {
            "promptType": "define",
            "text": text_expr,
            "options": {
                "systemMessage": system_msg,
                "maxIterations": 30,
            },
        },
    }

def http_tool(name: str, node_id: str, description: str, url: str, body_expr: str) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.2,
        "position": [0, 0],
        "parameters": {
            "toolDescription": description,
            "method": "POST",
            "url": url,
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body_expr,
        },
    }

def http_request(name: str, node_id: str, url: str, body_expr: str, timeout: int = 0) -> dict:
    opts = {"timeout": timeout} if timeout else {}
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [0, 0],
        "parameters": {
            "method": "POST",
            "url": url,
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body_expr,
            "options": opts,
        },
    }

def code_node(name: str, node_id: str, js_code: str) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [0, 0],
        "parameters": {"jsCode": js_code},
    }

def if_node(name: str, node_id: str, left_expr: str, operator: str, right_value, right_type: str = "string") -> dict:
    op_map = {
        "equals": {"type": right_type, "operation": "equals"},
        "notEquals": {"type": right_type, "operation": "notEquals"},
        "gt": {"type": "number", "operation": "gt"},
        "exists": {"type": "string", "operation": "exists"},
    }
    condition = {
        "id": nid(f"cond-{name}"),
        "leftValue": left_expr,
        "rightValue": right_value,
        "operator": op_map.get(operator, {"type": right_type, "operation": operator}),
    }
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": [0, 0],
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": False, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [condition],
                "combinator": "and",
            },
            "options": {},
        },
    }

# ─── load v2 to reuse existing nodes ────────────────────────────────────────

with open(
    r"C:\Users\Summer Ishi\Github\TitleMatrix\ScraperSystems\others\heirtracer\workflow_v2_local.json",
    encoding="utf-8",
) as f:
    v2 = json.load(f)

v2_by_name = {n["name"]: n for n in v2["nodes"]}

def v2node(name: str) -> dict:
    """Return a deep copy of a v2 node."""
    return json.loads(json.dumps(v2_by_name[name]))

# ─── IDs for kept v2 nodes ──────────────────────────────────────────────────
# (using their existing IDs so n8n doesn't break)

ID = {
    # Phase 1
    "Webhook":                  "9959105c-ab2e-41d0-bb48-55fd0b1e0e2c",
    "Create Heir Session":      "bab81353-0323-4b24-8cb1-48f40cef7a48",
    "Root Owner Research":      "251f3f2d-778d-4c40-81af-2d4131847cf5",
    "Root Research Model":      "bb3e5e39-0209-4d0a-98c8-4cf7f447a15f",
    "SkipGenie Root Decedent":  "7856bcf4-f058-4d5c-87ad-fbed5a1cbeba",
    "Load Property State":      "31d0b388-2083-4f6c-a499-2e83ab68f12f",
    "Ancestry Search Root":     "ancestry-search-root-001",
    "Respond to Webhook":       "d1c12ac6-7309-4623-8958-1c0c23a88b27",

    # Phase 2 – SkipGenie waterfall
    "Worker Webhook":           "5fc8f1cb-0cde-4321-a5bb-c8b2d1b1c4ae",
    "Claim Next Person":        "c6e70337-a350-4218-b19a-a4cf7f7bdfe2",
    "If Person Claimed":        "f6ad88ff-5ce7-4594-b9c5-59f67c82e46d",
    "Worker - Prepare Item":    "6d1965d0-2ecc-4591-8b3f-c5c1be30e18f",
    "Parse Attempts":           "8505fa90-a754-4017-898d-7be89d4f8e49",
    "SkipGenie Try 1":          "dea8e1ab-4250-4437-9f9f-e62fae4e07e6",
    "SkipGenie Try 2":          "f1c1abb5-1537-4c32-88e7-cb89a8aac1fa",
    "SkipGenie Try 3":          "8948dde9-6e87-4c0c-b0f8-b8e4b0e9c3ab",
    "SkipGenie Try 4":          "1d3ee814-41d1-41ef-8c16-2e19f9438218",
    "SkipGenie Try 5":          "01f1231c-bd43-4399-90e0-3c8d8f8a7b5c",
    "Got Results 1?":           "08f34601-0dc6-4b5f-8bc8-4ab3b8f8c15c",
    "Got Results 2?":           "d1215253-9b7f-4f4c-b7c6-c6d8b6c6d6e6",
    "Got Results 3?":           "24dd4206-d8ba-4852-80e6-b8c7e8b7c9b8",
    "Got Results 4?":           "0cccdaa6-b407-4847-a9c9-c9d9e9f9a9b9",

    # Phase 2 – agents and parse nodes
    "Parse Vital Status":       "8f669b82-6adf-4d8a-a1ac-c8a67550d265",
    "Vital Status Researcher":  "2d5c9cf8-a521-4fa9-a81b-b7f8c1d1e2f3",
    "NC Voter (VSR)":           "b0515dc3-81de-4b01-8e5f-f5e6f6f7f8f9",
    "Ancestry Search (VSR)":    "fd3bc525-1024-4562-8c6e-e6f6f7f8f9fa",
    "Write Voter Record (VSR)": "50951a4b-5e6c-4895-8d7f-f7f8f9fafbfc",
    "VSR Model":                "dc558311-5c40-4d88-a9bf-c1d1e1f1f2f3",
    "Obituary Deep Diver":      "f1667c31-1261-4d93-9e40-f139a9e6289e",
    "Brave Search":             "bf0a7010-c20e-4b1c-80ad-d0e1f1f2f3f4",
    "Fetch Obituary Page":      "f96cf3db-d293-4e5d-91ef-e3f4f5f6f7f8",
    "Ancestry Search (ODD)":    "dd0e2695-e09b-4891-81ef-f1f2f3f4f5f6",
    "Write Ancestry Findings":  "d3f9739f-d6aa-4f81-8aef-c2d2e2f2f3f4",
    "NC Voter Lookup":          "485ebdf3-b30e-41e6-a8bf-c3d3e3f3f4f5",
    "ODD Model":                "18f930cf-771c-4e82-a0b0-d0e0f0f1f2f3",
    "Parse Obit Deep":          "7390ca95-563b-4388-a8ef-e8f8f9fafbfc",
    "Surname Crosser":          "7ca2b4ae-63ba-4801-a9bf-d1e1f1f2f3f4",
    "Ancestry Search (SCR)":    "fbe9d8c2-87a7-45e8-8c6f-f2f3f4f5f6f7",
    "NC Voter (SCR)":           "df64c14b-6d83-42e6-a7bf-e3f3f4f5f6f7",
    "Write Voter Record (SCR)": "db7ea7a2-a17e-4c91-8eef-f4f5f6f7f8f9",
    "SCR Model":                "e315bb00-ddbd-41e9-a9bf-f5f6f7f8f9fa",
    "Parse Surname Crosser":    "438d991c-c82f-4286-81ef-f6f7f8f9fafb",
    "Title Attorney":           "ea3d80e2-779c-4260-af7a-a0262290df8b",
    "Wake Deeds":               "1040ff4b-53b6-4f26-8caf-a1b1c1d1e1f1",
    "Buncombe Deeds":           "44fd4900-cf74-4614-a2b2-b2c2d2e2f2f3",
    "Mecklenburg Deeds":        "c228ab65-d2f9-4a46-83af-c3d3e3f3f4f5",
    "Court Search":             "28acbd6b-59ea-4d5a-8faf-d4e4f4f5f6f7",
    "Register of Actions":      "6bf3c430-48bd-4e52-9baf-e5f5f6f7f8f9",
    "Court Document Pull":      "6266adcc-17d4-4688-a9af-f6f7f8f9fafb",
    "Write Court Findings":     "write-court-findings-001",
    "TA Model":                 "f262c87a-956f-4c7e-a1b1-c1d1e1f1f2f3",

    # Phase 2 – queue management
    "Mark Person Done":         "3b3d58ba-1784-4388-9caf-c2d2e2f2f3f4",
    "Self Trigger Worker":      "82418466-1060-4590-8daf-d3e3f3f4f5f6",
    "Check Queue Status":       "6e21fd8f-657f-4c47-92af-e4f4f5f6f7f8",
    "If Queue Empty":           "0dbd3c27-c5dc-4487-a5af-f5f6f7f8f9fa",
    "Claim FA Trigger":         "a0aa4d90-f4e9-4c5a-83af-f6f7f8f9fafb",
    "If FA Claimed":            "60189cd1-6848-4f59-8caf-f7f8f9fafbfc",
    "Trigger FA Workflow":      "d8a1c11f-4a1d-4d56-95af-f8f9fafbfcfd",

    # Phase 3 – family assembly
    "FA Webhook":               "7175b1ac-8888-4e4a-a2bf-f9fafbfcfdfe",
    "Family Assembler":         "74424069-5093-49ff-8ffc-33ba4412f9cb",
    "Load Family Dataset":      "4167c98d-e14b-4561-a8af-fafbfcfdfeff",
    "Load Obituary Texts":      "ebc83e2d-fef3-4d7b-86af-fbfcfdfeffff",
    "Ancestry Search (FA)":     "c7f633c4-b82c-4c4d-84af-fcfdfeffffff",
    "Load Ancestry Records (FA)": "85d61f32-3749-4951-87af-fdfefeff0001",
    "Load Voter Records (FA)":  "1fadc3e8-7e64-41e8-8caf-feff00010203",
    "FA Model":                 "ba87704d-d33f-4086-8aef-ff0001020304",
    "Parse Family Tree":        "c3140e7d-f87d-4711-89ef-000102030405",
    "Intestate Expert":         "965d5c4e-7b6c-4d19-9e5d-8908185548b0",
    "Filter Cascade Persons":   "5e75c681-c51e-4e55-90af-010203040506",
    "IE Model":                 "f46814cf-a266-49a2-83af-020304050607",
    "Parse Intestate Output":   "d3d1199c-5c0d-4a48-8def-030405060708",
    "More Cascade?":            "4e869f5e-a4d1-4a5e-94af-040506070809",
    "FA Queue Cascade":         "acd8ff1a-bc81-4e52-88af-05060708090a",
    "FA Trigger Worker":        "8b1ab35f-2e03-4d4c-87af-060708090a0b",
    "Genealogist":              "7130a47b-8d1f-4311-8aaf-07080900b0c0",
    "Gen Model":                "678ce6f1-7930-4222-88af-0809000b0c0d",
    "Write Family Tree DB":     "4dee479e-6707-42e3-8baf-09000b0c0d0e",
}

# New v3 node IDs
NID = {k: nid(k) for k in [
    # Phase 1 new nodes
    "Brave Search Root", "Fetch Obit Root", "NC Voter Root", "Write Voter Root",
    "Court Search Root", "Reg Actions Root", "Court Doc Root",
    "Write Court Root", "Write Ancestry Root",
    "Write Root Person",
    "Branch Planner", "Branch Planner Model",
    "Load Ancestry BP", "Load Court BP", "Queue Init Heirs",

    # v3.1 — new tools to fix Lydia Hayes-style misses
    "Ancestry Search Save Root",  # /ancestry/search-and-save — replaces Search+Write pair
    "Ancestry Record Root",        # /ancestry/record-and-save — fetches obit detail page
    "Ancestry Record (ODD)",       # same, for Obituary Deep Diver
    "Ancestry Search (BP)",        # parent-mode lookups for partial-name resolution

    # Phase 2 new nodes
    "SG Analyzer", "SG Analyzer Model",
    "Parse SG Analyzer",
    "Upsert Person SG",
    "Vital Status Gate",
    "Flag Unknown", "Mark Done Unknown", "Self Trigger Unknown",
    "Person Compiler", "Person Compiler Model",
    "Load Ancestry PC", "Load Court PC", "Load Voter PC", "Write Person PC",
    "Parse Person Compiler",
    "Branch Decision", "Branch Decision Model",
    "Load Person BD", "Queue Cascade BD",
]}

# ─── Node definitions ────────────────────────────────────────────────────────

# ── Phase 1: Root Research ──────────────────────────────────────────────────

webhook = v2node("Webhook")

create_session = http_request(
    "Create Heir Session", ID["Create Heir Session"],
    f"{BASE}/heir/session",
    '={{ { "property_id": $json.body.property_id, "county": $json.body.county, "state": $json.body.state } }}',
)

# Enhanced Root Research Agent with full pipeline tools
root_research_agent = agent_node(
    "Root Owner Research", ID["Root Owner Research"],
    system_msg="""You are the Root Research Agent. Research the deceased property owner comprehensively.

MANDATORY STEPS (in order):
1. Use Load Property State to get property details and owner name.
2. Search SkipGenie for the decedent. Pass first_name, last_name, state="NC", and city=<property city or county name> (e.g. "Wake Forest" or "Wake"). Name + state alone returns nothing — city or county is required to narrow results. SkipGenie is helpful but optional — if it returns no match, continue through ALL remaining steps using the property owner name directly. Do not stop.
3. Search NC voter registration (NC Voter Root) using the best name available: SkipGenie matched name if found, otherwise the property owner name as-is.
4. **Ancestry Search Save Root — direct search** (atomic search + DB write): pass session_id, property_id, first_name + last_name + death_location="[County], North Carolina" (e.g. "Wake, North Carolina") + death_year=[infer in priority order: (a) SkipGenie dod if populated, (b) SkipGenie last_address end-date year, (c) deed/property record date if available, (d) omit death_year entirely and search without it] + collection_id="61843". The endpoint pre-ranks results by NC location + death year proximity — review ALL returned records_summary entries (up to 50) before selecting.

**Record selection — mandatory steps:**
  - STEP A — Hard reject: discard any record whose death_location contains a US state name other than "North Carolina" / "NC" (e.g. Texas, Virginia, Georgia). A different state in death_location is disqualifying regardless of year match.
  - STEP B — Soft filters: among remaining candidates, prefer in order: (1) dod year matches inferred death year ±2; (2) children[] names overlap with any known relative (SkipGenie if available, or other Ancestry/obit findings); (3) dob plausible given likely age at death.
  - STEP C — If no NC-location record passes, set best_candidate=none and proceed to step 4c (parent-mode) before falling back to a non-NC record.
  - Reject records with dod before 1960.
4b. **MANDATORY — Ancestry Record Root**: after picking the best obit candidate from step 4, call Ancestry Record Root using the record's **source_url** (preferred) or bare record_id as the record_id parameter, plus session_id+property_id. Always prefer source_url — the bare numeric record_id resolves to the wrong endpoint for Newspapers.com collection records and will 404. The detail page returns the canonical surname-bearing children list ("Mary Justice" not "Mary"). Do not skip — the search-results card is incomplete.
4c. **Parent-mode discovery** — also call Ancestry Search Save Root with mother="<root full name>" (if female/unknown) OR father="<root full name>" (if male) + state="NC" + collection_id="61843" + first_name="" + last_name="<root surname>". This returns records where the root is named as a parent — surfaces children with their married/birth surnames that wouldn't appear in the direct search.
4d. **Census discovery** — also call Ancestry Search Save Root with last_name=<root surname> + state="NC" + collection_id="2442" (1940 census). Look for entries listing the root's household; siblings of obit-named children often appear here (e.g. Johnnie/Moses/Margaret in Lydia Hayes's case).
5. Use Brave Search Root for: "[Full Name] obituary [county] NC [death year or approximate year]"
6. If obituary URL found on a public site (NOT ancestry.com): Fetch Obit Root to get full text.
7. Search NC Courts for estate/probate: Court Search Root with name in "LAST, FIRST" format (e.g. "HAYES, LYDIA") + county. Server now auto-retries name variants — just pass the most complete form you have. This step is ALWAYS mandatory — run it even if SkipGenie returned nothing. A filed probate or estate case is often the single most authoritative source for the heir list.
8. If estate case found: Register Actions Root to see filings. Court Doc Root for the probate PDF. If the probate document names heirs explicitly, those names are definitive — use them as the primary cascade_relatives list.

IMPORTANT — NO SKIPGENIE FALLBACK CHAIN:
If SkipGenie returns no match: do NOT stop or reduce effort. Steps 4–8 (Ancestry, obit, probate) are INDEPENDENT of SkipGenie and often yield richer heir data. Obituaries name survivors. Ancestry parent-mode surfaces married children. Probate documents name heirs legally. Any of these alone can complete the research.

NAME RESOLUTION RULES (CRITICAL):
- NEVER emit a relative with only a first name (e.g. just "Mary"). Single-token names get silently dropped downstream.
- If you find a partial name, resolve it before output by: (a) the Ancestry Record Root detail page (step 4b), (b) parent-mode search (step 4c), or (c) Brave-searching the obit body.
- If a name remains unresolved after exhausting (a-c), DROP it from output. Do not pass it on.
- For married daughters, output the married surname as `name` and set `maiden_name` to the birth surname.

WRITE TO DB (mandatory):
- Write Voter Root: save voter lookup result (even if not found).
- Write Court Root: save probate findings (REQUIRED when any court case is found).
- Ancestry writes happen automatically inside Ancestry Search Save Root / Ancestry Record Root — do NOT call Write Ancestry Root separately for those.
- Use Write Ancestry Root ONLY for legacy/manual record entries not produced by the save-aware tools above.

SESSION CONTEXT: session_id and property_id are in your input — pass them to ALL save-aware tools (without them, no DB write happens).

OUTPUT JSON (no preamble, only this):
{
  "root_decedent_name": "...",
  "matched_identity": { "full_name": "...", "dob": "...", "dod": "...", "address": "..." },
  "vital_status": "deceased",
  "date_of_death": "...",
  "marital_status_at_death": "married|widowed|divorced|single",
  "surviving_spouse_name": "...",
  "estate_filed": true/false/null,
  "had_will": true/false/null,
  "obituary_url": "...",
  "obituary_text": "...(full, do not truncate)...",
  "cascade_relatives": [{"name": "FIRST LAST", "relationship_hint": "child|spouse|sibling", "maiden_name": "...or null"}]
}

CASCADE RELATIVES RULES — CRITICAL:
1. SOURCE PRIORITY: Obituary children (step 4b detail page) and probate named heirs (step 8) are AUTHORITATIVE. When either source explicitly lists children, those are the children — do not add extras.
2. SKIPGENIE RELATIVES ARE NOT HEIRS: SkipGenie "possible_relatives" are useful ONLY for confirming you found the right person (do they share known family names?). Never add a SkipGenie relative to cascade_relatives as a child based solely on shared last name or age gap — those signals are meaningless without a probate or obituary as basis.
3. MERGE RULE: cascade_relatives = obit children + probate heirs + parent-mode Ancestry results. Add SkipGenie relatives ONLY if they are also named as heirs/survivors in an independent source (obit, probate, census). If the obituary lists children, it is a closed list — do not supplement it with SkipGenie names.
4. Deduplicate: if the same person appears in multiple qualifying sources, include them ONCE using the most complete name.
Do NOT output separate "relatives" and "ancestry_family_members" arrays.""",
    text_expr=(
        "=Research the deceased property owner:\n\n"
        "Property ID: {{ $json.property_id }}\n"
        "Session ID: {{ $json.session_id }}\n"
        "Root Decedent: {{ $json.root_decedent_name }}\n"
        "County: {{ $json.county }}\n"
        "State: {{ $json.state }}"
    ),
)

root_research_model = gpt_model("GPT-5-Mini (Root Research)", ID["Root Research Model"])

# Original tools kept for Root Research Agent
sg_root_tool     = v2node("SkipGenie — Root Decedent")
load_prop_tool   = v2node("Load Property State")
anc_root_tool    = v2node("Ancestry Search (Root)")
anc_root_tool["name"] = "Ancestry Search Root"
anc_root_tool["id"]   = ID["Ancestry Search Root"]
# Override tool to support parent-mode search (mother=/father=) and count=100
anc_root_tool["parameters"]["toolDescription"] = (
    "Search Ancestry.com obituary collection (61843) for the root decedent. "
    "Pass first_name + last_name + death_location (e.g. 'Wake, North Carolina') + "
    "death_year (infer from SkipGenie dod or last address end-date) + collection_id='61843'. "
    "Returns up to 100 obituary records with dob, dod, children[], and spouse fields."
)
anc_root_tool["parameters"]["jsonBody"] = (
    '={{ { '
    '"first_name": $fromAI("first_name", "First name. Empty string for parent-mode search."), '
    '"last_name": $fromAI("last_name", "Last name. Empty string for parent-mode search."), '
    '"birth_year": $fromAI("birth_year", "Estimated birth year, empty if unknown"), '
    '"death_year": $fromAI("death_year", "Estimated death year, empty if unknown"), '
    '"death_location": $fromAI("death_location", "Death location e.g. \'North Carolina\'"), '
    '"mother": $fromAI("mother", "Parent-mode: pass decedent\'s full name as mother. Empty string for direct search."), '
    '"father": $fromAI("father", "Parent-mode: pass decedent\'s full name as father. Empty string for direct search."), '
    '"collection_id": $fromAI("collection_id", "Always \'61843\' for U.S. Obituary Collection"), '
    '"count": 100, "state": "NC", "name_x": "1_1" } }}'
)

brave_root = {
    **v2node("Brave Search"),
    "id": NID["Brave Search Root"],
    "name": "Brave Search Root",
}
fetch_obit_root = {
    **v2node("Fetch Obituary Page"),
    "id": NID["Fetch Obit Root"],
    "name": "Fetch Obit Root",
}
nc_voter_root = http_tool(
    "NC Voter Root", NID["NC Voter Root"],
    "Look up NC voter registration for the root decedent. Pass last_name, first_name. Returns voter status (A=Active, R=Removed).",
    f"{BASE}/voter/nc/lookup",
    '={{ { "last_name": $fromAI("last_name", "Last name"), "first_name": $fromAI("first_name", "First name"), "county": $fromAI("county", "County if known", "string", null) } }}',
)
write_voter_root = http_tool(
    "Write Voter Root", NID["Write Voter Root"],
    "Save voter lookup result for the root decedent. Required: session_id, property_id, search_name, search_context='root_research'.",
    f"{BASE}/heir/write-voter",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "search_name": $fromAI("search_name", "Name searched"), "search_context": "root_research", "ncid": $fromAI("ncid", "NCID if found", "string", null), "full_name": $fromAI("full_name", "Full name if found", "string", null), "county": $fromAI("county", "County if found", "string", null), "status": $fromAI("status", "Status A/I/R/D if found", "string", null), "notes": $fromAI("notes", "Notes", "string", "") } }}',
)
court_search_root = http_tool(
    "Court Search Root", NID["Court Search Root"],
    "Search NC courts for the root decedent's estate/probate case. Pass name in 'LAST, FIRST' format (e.g. 'HAYES, LYDIA') and county.",
    f"{BASE}/court/nc/search",
    '={{ { "name": $fromAI("name", "Person name in LAST, FIRST format (e.g. HAYES, LYDIA)"), "county": $fromAI("county", "County", "string", null) } }}',
)
reg_actions_root = http_tool(
    "Register Actions Root", NID["Reg Actions Root"],
    "Get full event timeline for a root decedent's court case. Pass case_url from Court Search Root.",
    f"{BASE}/court/nc/register_of_actions",
    '={{ { "case_url": $fromAI("case_url", "The case URL from Court Search Root") } }}',
)
court_doc_root = http_tool(
    "Court Doc Root", NID["Court Doc Root"],
    "Download and extract a probate court document for the root decedent. Pass case URL.",
    f"{BASE}/court/nc/pull-document",
    '={{ { "url": $fromAI("url", "Case URL from Register Actions Root or Court Search") } }}',
)
write_court_root = http_tool(
    "Write Court Root", NID["Write Court Root"],
    "Save root decedent's probate court findings to DB. Required: session_id, property_id, person_name. Include all court and probate data found.",
    f"{BASE}/heir/write-court-findings",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "person_name": $fromAI("person_name", "Decedent full name"), "case_number": $fromAI("case_number", "Case number", "string", null), "case_url": $fromAI("case_url", "Case URL", "string", null), "case_type": $fromAI("case_type", "Case type E/SP", "string", null), "estate_filed": $fromAI("estate_filed", "Whether estate was filed", "boolean", null), "had_will": $fromAI("had_will", "Whether decedent had a will", "boolean", null), "named_persons": $fromAI("named_persons", "Named persons from probate", "json", []), "probate_family_tree": $fromAI("probate_family_tree", "Family tree from probate PDF", "json", []), "extraction_summary": $fromAI("extraction_summary", "Summary of extracted data", "string", "") } }}',
)
write_anc_root = http_tool(
    "Write Ancestry Root", NID["Write Ancestry Root"],
    "(LEGACY — prefer Ancestry Search Save Root) Save Ancestry records to DB. Required: session_id, property_id, search_name, records[].",
    f"{BASE}/heir/write-ancestry",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "search_name": $fromAI("search_name", "Name searched on Ancestry"), "records": $fromAI("records", "Array of Ancestry records found", "json", []) } }}',
)

# v3.1 — atomic search+save (eliminates LLM-curated records[] data loss)
ancestry_search_save_root = http_tool(
    "Ancestry Search Save Root", NID["Ancestry Search Save Root"],
    (
        "Search Ancestry AND auto-save raw results to DB in one call. "
        "REQUIRED: session_id, property_id. Plus one of: first_name+last_name, OR mother=<full name>, OR father=<full name>. "
        "Use this instead of the legacy Ancestry Search Root → Write Ancestry Root pair. "
        "Returns compact records_summary (with children/parents intact). "
        "Three usage modes for the root decedent: "
        "(1) DIRECT: first_name+last_name+death_year+death_location+collection_id='61843' to find the obit. "
        "(2) PARENT-MODE: mother=<full name> OR father=<full name> + last_name=<surname> + collection_id='61843' to find records where decedent is named as parent. "
        "(3) CENSUS: last_name=<surname>+state='NC'+collection_id='2442' for 1940 census household members."
    ),
    f"{BASE}/ancestry/search-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"first_name": $fromAI("first_name", "First name. Empty string for parent-mode.", "string", ""), '
        '"last_name": $fromAI("last_name", "Last name. Empty string for parent-mode if needed.", "string", ""), '
        '"birth_year": $fromAI("birth_year", "Estimated birth year, empty if unknown", "string", ""), '
        '"death_year": $fromAI("death_year", "Estimated death year, empty if unknown", "string", ""), '
        '"death_location": $fromAI("death_location", "Death location e.g. \'Wake, North Carolina\'", "string", ""), '
        '"mother": $fromAI("mother", "Parent-mode: decedent full name as mother. Empty for direct.", "string", ""), '
        '"father": $fromAI("father", "Parent-mode: decedent full name as father. Empty for direct.", "string", ""), '
        '"collection_id": $fromAI("collection_id", "Ancestry collection_id e.g. 61843 (obits), 2442 (1940 census), or empty for global", "string", ""), '
        '"state": $fromAI("state", "State e.g. \'NC\'", "string", "NC"), '
        '"name_x": $fromAI("name_x", "Exact-match flags, default \'1_1\'", "string", "1_1") '
        '} }}'
    ),
)

# v3.1 — fetch the obit DETAIL page (canonical structured Child field) and save it
ancestry_record_root = http_tool(
    "Ancestry Record Root", NID["Ancestry Record Root"],
    (
        "Fetch a specific Ancestry record's full detail page AND save it. "
        "REQUIRED: session_id, property_id, record_id (numeric ID OR full URL). "
        "The search results card is incomplete — the detail page has the canonical "
        "structured Child field with full surnames (e.g. 'Mary Justice' not 'Mary'). "
        "Always call this after selecting the best obit candidate from Ancestry Search Save Root."
    ),
    f"{BASE}/ancestry/record-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"record_id": $fromAI("record_id", "Ancestry record_id (numeric) or full record URL"), '
        '"state": $fromAI("state", "State e.g. \'NC\'", "string", "NC") '
        '} }}'
    ),
)

write_root_person = http_request(
    "Write Root Person", NID["Write Root Person"],
    f"{BASE}/heir/upsert-person",
    """={{ (function() {
  try {
    const raw = $('Root Owner Research').first().json.output || '';
    const cleaned = raw.replace(/```json\\n?/g, '').replace(/```/g, '').trim();
    const m = cleaned.match(/\\{[\\s\\S]*\\}/);
    const parsed = JSON.parse(m ? m[0] : cleaned);
    const sess = $('Create Heir Session').first().json;
    const name = parsed.root_decedent_name || parsed.matched_identity?.full_name || sess.root_decedent_name || 'Unknown';
    return {
      session_id:        sess.session_id,
      property_id:       sess.property_id,
      input_name:        name,
      relationship_hint: 'root_decedent',
      level:             0,
      research_phase:    'complete',
      vital_status:      parsed.vital_status || 'deceased',
      matched_identity:  parsed.matched_identity || {},
      obituary_url:      parsed.obituary_url || '',
      obituary_text:     parsed.obituary_text || '',
      deceased_facts: {
        date_of_death:           parsed.date_of_death || '',
        marital_status_at_death: parsed.marital_status_at_death || '',
        surviving_spouse_name:   parsed.surviving_spouse_name || '',
        estate_filed:            parsed.estate_filed,
        had_will:                parsed.had_will,
        family_alive_at_death:   parsed.cascade_relatives || [],
      },
      cascade_relatives: parsed.cascade_relatives || [],
    };
  } catch(e) {
    const sess = $('Create Heir Session').first().json;
    return { session_id: sess.session_id, property_id: sess.property_id, input_name: sess.root_decedent_name || 'Unknown', level: 0, research_phase: 'complete', vital_status: 'deceased' };
  }
})() }}""",
)

# Branch Planner Agent
branch_planner = agent_node(
    "Branch Planner", NID["Branch Planner"],
    system_msg="""You are the Branch Planner. Read the root decedent's research from DB and determine which persons to queue for research under NC Chapter 29 intestate succession.

STEP 1 — Load Ancestry Records (BP) (just the session, no person filter) to find obituary and death records. Focus on:
  - Collection 61843 (Obituaries) — children[] / parents[] / spouse fields
  - Collection 2442 (1940 Census) — household members reveal siblings
  - Detail-page records (record_type="record") — these have the canonical surname-bearing children list

STEP 2 — Load Court Findings (BP) for the session to find probate data. A filed estate names heirs explicitly — use that as the definitive heir list.

STEP 3 — Apply NC Chapter 29 (in order):
a. If root decedent had children → children are primary heirs (they take everything, per stirpes)
b. If no children found → surviving spouse gets 1/2 + parents or siblings share the rest
c. Use obituary text, ancestry records, and probate data to build the initial heir list
d. Also include SkipGenie relatives from root person output (provided in your input)

STEP 3b — GRANDCHILDREN FROM OBIT BODY
Scan obituary_text for patterns like:
  - "grandchildren X, Y, Z" / "survived by … grandchildren …"
  - "great-grandchildren …"
  - "grandsons … and granddaughters …"
Queue each named grandchild with relationship_hint="grandchild". If a grandchild's parent
is identifiable from context (e.g. "his daughter Linda and her son Bob"), set
relationship_hint="grandchild" and note the parent in maiden_name as "via <parent>".
These get researched as level-2 heirs; the cascade will reconcile parentage later.

STEP 4 — Reconcile names across all sources BEFORE queuing. The same person may appear under different names:
- Obituary says "daughter Linda" (no last name) AND Ancestry parent-mode returns "Linda Turner (mother: Lydia Hayes)" → these are the same person → use "Linda Turner", maiden_name: "Hayes", do NOT create two entries
- SkipGenie relative "Mary Hayes" AND Ancestry shows "Mary Justice (mother: Lydia Hayes)" → same person → use "Mary Justice", maiden_name: "Hayes"
- Rule: always prefer the married/current name. Set maiden_name to the birth surname when known.

STEP 4b — RESOLVE PARTIAL NAMES (instead of dropping them silently)
For any single-token name in cascade_relatives (e.g. just "Mary"):
  1. First, scan all loaded Ancestry records for a children[] entry with that first name AND parent matching the root decedent. Use that resolved name.
  2. If unresolved, call Ancestry Search (BP) in parent-mode: mother=<root full name> (or father=) + state="NC" + collection_id="61843". Look for records whose children[] contains the first name.
  3. If still unresolved, log it in persons_dropped (do not queue).

STEP 5 — Queue Initial Heirs with the deduplicated, reconciled list.

Rules:
- Do NOT queue: "Heirs of X", "Estate of X", "Unknown", or the root decedent themselves
- Single-token names: resolve via Step 4b first; drop only if unresolvable
- ONLY queue persons with at least first AND last name
- Include relationship_hint: "child", "spouse", "parent", "sibling", "grandchild"
- Include maiden_name when known (married daughter's birth surname)

After calling Queue Initial Heirs, output this JSON:
{
  "heir_rationale": "Brief NC Ch. 29 explanation",
  "persons_queued": [{"name": "NAME1", "maiden_name": null, "relationship_hint": "child"}],
  "persons_dropped": [{"name": "Mary", "reason": "single-token name; not resolvable via ancestry parent-mode"}],
  "total_queued": N
}""",
    text_expr=(
        "=Determine initial heirs for root decedent.\n\n"
        "Session ID: {{ $json.session_id }}\n"
        "Property ID: {{ $json.property_id }}\n"
        "Root Decedent: {{ $json.input_name }}\n"
        "Person ID: {{ $json.person_id }}\n\n"
        "SkipGenie relatives from root research:\n"
        "={{ JSON.stringify($json.cascade_relatives || []) }}\n\n"
        "Obituary text (if available):\n"
        "={{ ($json.obituary_text || '').substring(0, 4000) }}"
    ),
)
branch_planner_model = gpt_model("GPT-5-Mini (Branch Planner)", NID["Branch Planner Model"])

load_anc_bp = http_tool(
    "Load Ancestry Records (BP)", NID["Load Ancestry BP"],
    "Load all Ancestry records for this session to find named relatives. Pass only session_id.",
    f"{BASE}/heir/ancestry-records",
    '={{ { "session_id": $fromAI("session_id", "The session ID") } }}',
)
load_court_bp = http_tool(
    "Load Court Findings (BP)", NID["Load Court BP"],
    "Load court/probate findings for this session. Pass only session_id.",
    f"{BASE}/heir/court-findings",
    '={{ { "session_id": $fromAI("session_id", "The session ID") } }}',
)
queue_init_heirs = http_tool(
    "Queue Initial Heirs", NID["Queue Init Heirs"],
    "Queue the initial list of heir candidates for research. Required: session_id, property_id, persons (array of {name, relationship_hint, maiden_name}). maiden_name is the birth surname for married daughters — pass it so the worker loop knows both names.",
    f"{BASE}/heir/queue-persons",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "persons": $fromAI("persons", "Array of {name, relationship_hint, maiden_name} to queue. maiden_name is optional birth surname.", "json", []) } }}',
)

# v3.1 — give Branch Planner an Ancestry search tool for partial-name resolution
ancestry_search_bp = http_tool(
    "Ancestry Search (BP)", NID["Ancestry Search (BP)"],
    (
        "Atomic Ancestry search + DB write. Use ONLY for resolving partial names "
        "(single-token first names) via parent-mode lookup. "
        "REQUIRED: session_id, property_id. Typical call: "
        "mother=<root full name> + last_name=<root surname> + state='NC' + collection_id='61843' + first_name=''. "
        "Returns records_summary; scan children[] for the partial name to resolve to full name."
    ),
    f"{BASE}/ancestry/search-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"first_name": $fromAI("first_name", "First name (empty for parent-mode)", "string", ""), '
        '"last_name": $fromAI("last_name", "Last name", "string", ""), '
        '"mother": $fromAI("mother", "Parent-mode: full name as mother", "string", ""), '
        '"father": $fromAI("father", "Parent-mode: full name as father", "string", ""), '
        '"collection_id": $fromAI("collection_id", "e.g. \'61843\' for obits, \'2442\' for 1940 census", "string", "61843"), '
        '"state": $fromAI("state", "State e.g. \'NC\'", "string", "NC") '
        '} }}'
    ),
)

# Forward county to the worker so SkipGenie can use it as city.
# county comes from Create Heir Session which auto-looks it up from the property.
trigger_worker_init = v2node("Trigger Worker Init")
trigger_worker_init["parameters"]["jsonBody"] = (
    '={{ { "session_id": $(\'Create Heir Session\').first().json.session_id,'
    ' "property_id": $(\'Create Heir Session\').first().json.property_id,'
    ' "county": $(\'Create Heir Session\').first().json.county || \'\' } }}'
)
respond_to_webhook  = v2node("Respond to Webhook")

# ── Phase 2: Worker Loop ────────────────────────────────────────────────────

worker_webhook  = v2node("Worker Webhook")
claim_next      = v2node("Claim Next Person")
if_claimed      = v2node("If Person Claimed")

# Worker Prepare Item — simplified (no Orch-Prep needed)
worker_prepare = code_node(
    "Worker - Prepare Item", ID["Worker - Prepare Item"],
    """const wb = $('Worker Webhook').first().json.body;
const item = $('Claim Next Person').first().json.item;
return [{ json: {
  name:              item.person_name,
  relationship_hint: item.relationship_hint || '',
  age:               '',
  phone:             '',
  address:           '',
  property_id:       wb.property_id,
  session_id:        wb.session_id,
  queue_id:          item.queue_id,
  maiden_name:       item.maiden_name || '',
  loop_context:      'worker',
  state:             'NC',
  county:            wb.county || '',
} }];""",
)

# Parse Attempts — generates search attempts directly from name (no LLM needed)
parse_attempts = code_node(
    "Parse Attempts", ID["Parse Attempts"],
    """const d = $input.first().json;
const name = (d.name || '').trim();
const parts = name.split(/\\s+/).filter(Boolean);
const last     = parts.length > 0 ? parts[parts.length - 1] : '';
const firstAll = parts.length > 1 ? parts.slice(0, -1).join(' ') : '';
const firstOnly = parts.length > 1 ? parts[0] : '';
const state = d.state || 'NC';
const county = (d.county || '').trim();  // narrower search — SkipGenie needs city or county
const maiden = (d.maiden_name || '').trim();

// Tip: name+state alone usually returns nothing from SkipGenie.
// Lead with county-narrowed attempts, fall back to state-only.
const attempts = [
  { first_name: firstAll,  last_name: last,   state: state, city: county },  // full name + county
  { first_name: firstOnly, last_name: last,   state: state, city: county },  // first + last + county
  { first_name: firstAll,  last_name: last,   state: state, city: '' },      // full name, state only
  { first_name: firstOnly, last_name: last,   state: state, city: '' },      // first + last, state only
  { first_name: '',        last_name: last,   state: state, city: county },  // last + county only
].filter(a => a.last_name.length > 0);

// Add maiden name attempt (with county) after attempt 1 if available
if (maiden && maiden !== last) {
  attempts.splice(1, 0, { first_name: firstAll, last_name: maiden, state: state, city: county });
}

while (attempts.length < 5) attempts.push(attempts[attempts.length - 1]);

return [{ json: { ...d, attempts: attempts.slice(0, 5) } }];""",
)

# Keep SkipGenie Try 1-5 and Got Results 1-4 exactly as in v2
sg_try1 = v2node("SkipGenie Try 1")
sg_try2 = v2node("SkipGenie Try 2")
sg_try3 = v2node("SkipGenie Try 3")
sg_try4 = v2node("SkipGenie Try 4")
sg_try5 = v2node("SkipGenie Try 5")
got1    = v2node("Got Results 1?")
got2    = v2node("Got Results 2?")
got3    = v2node("Got Results 3?")
got4    = v2node("Got Results 4?")

# SkipGenie Analyzer Agent — selects best candidate from SG results
sg_analyzer = agent_node(
    "SG Analyzer", NID["SG Analyzer"],
    system_msg="""You are the SkipGenie Results Analyzer. Select the best matching candidate from raw SkipGenie results.

Scoring rules (higher = better match):
+2: last name matches exactly (case-insensitive)
+2: person is marked deceased (expected for heir research)
+2: known relative name (from prior research context) appears in this candidate's possible_relatives
+1: age estimate is plausible (if estimated death year is 1980-2010, age at death 40-90)
+1: NC address or state matches NC

GEOGRAPHIC SANITY VETO (overrides scoring):
The property's expected county/state is in your input as expected_county / expected_state.
A candidate whose primary/current address is OUTSIDE the expected state — and whose
possible_relatives don't overlap with relatives from prior research — is almost
certainly the wrong person sharing a common name.
  - If a candidate's state doesn't match expected_state AND no relative-name overlap:
    that candidate scores 0 regardless of other signals. Pick a different one.
  - If NO candidate has matching state, prefer one with relative-name overlap.
  - If still nothing plausible, return selected_result_index: null with reason
    "no candidate matches expected geography".

Select the best candidate. If no candidate scores ≥ 2, select index: null.

RELATIVES RULE — CRITICAL:
SkipGenie lists "possible_relatives" but does NOT identify who is a child vs. sibling vs.
spouse vs. cousin. Do NOT infer relationship type from age gap or shared last name alone.
  - Output all possible_relatives as relationship: "relative"
  - Never assign relationship: "child" — SkipGenie has no basis for that
  - These relatives are ONLY useful for confirming you have the right person (cross-reference
    with known family from obituary/probate). They are NOT a source of heir data.

Output ONLY this JSON (no preamble):
{
  "selected_result_index": 0,
  "selection_reason": "...",
  "matched_identity": {
    "full_name": "...",
    "dob": "...",
    "dod": "...",
    "address": "...",
    "confidence": "high|medium|low"
  },
  "cascade_relatives": [
    {"name": "...", "relationship": "relative"}
  ],
  "vital_status_hint": "deceased|living|unknown",
  "geography_check": "matches_expected|wrong_state|wrong_county|unknown"
}""",
    text_expr=(
        "=Analyze these SkipGenie results for: {{ $('Parse Attempts').first().json.name }}\n"
        "Relationship hint: {{ $('Parse Attempts').first().json.relationship_hint }}\n"
        "Expected county: {{ $('Worker Webhook').first().json.body.county || 'unknown' }}\n"
        "Expected state: {{ $('Worker Webhook').first().json.body.state || 'NC' }}\n\n"
        "Result count: {{ $json.result_count || 0 }}\n"
        "Results:\n={{ JSON.stringify(($json.results || []).slice(0, 15)) }}"
    ),
)
sg_analyzer_model = gpt_model("GPT-5-Mini (SG Analyzer)", NID["SG Analyzer Model"])

parse_sg_analyzer = code_node(
    "Parse SG Analyzer", NID["Parse SG Analyzer"],
    """const raw = ($input.first().json.output || '').replace(/```json\\n?/g, '').replace(/```/g, '').trim();
const ctx = $('Parse Attempts').first().json;

let parsed = {};
try {
  const m = raw.match(/\\{[\\s\\S]*\\}/);
  parsed = JSON.parse(m ? m[0] : raw);
} catch(e) {
  parsed = { selected_result_index: null, matched_identity: {}, cascade_relatives: [], vital_status_hint: 'unknown' };
}

return [{ json: {
  name:              ctx.name || '',
  property_id:       ctx.property_id,
  session_id:        ctx.session_id,
  queue_id:          ctx.queue_id,
  loop_context:      ctx.loop_context || 'worker',
  relationship_hint: ctx.relationship_hint || '',
  maiden_name:       ctx.maiden_name || '',
  matched_identity:  parsed.matched_identity || {},
  cascade_relatives: parsed.cascade_relatives || [],
  vital_status_hint: parsed.vital_status_hint || 'unknown',
  sg_selection_reason: parsed.selection_reason || '',
} }];""",
)

upsert_person_sg = http_request(
    "Upsert Person SG", NID["Upsert Person SG"],
    f"{BASE}/heir/upsert-person",
    """={{ {
  session_id:        $json.session_id,
  property_id:       $json.property_id,
  input_name:        $json.name,
  name:              $json.name,
  relationship_hint: $json.relationship_hint,
  queue_id:          $json.queue_id,
  level:             1,
  research_phase:    'skipgenie',
  matched_identity:  $json.matched_identity,
  cascade_relatives: $json.cascade_relatives,
  vital_status_hint: $json.vital_status_hint,
  loop_context:      $json.loop_context,
  maiden_name:       $json.maiden_name || '',
} }}""",
)

# VSR Agent — keep existing tools, update text to not use Orch-Format-Prompt
vsr_agent = v2node("Vital Status Researcher")

# v3.1 — strengthen identity verification (fixes wrong-Troy-Hayes problem)
_vsr_orig_sm = vsr_agent["parameters"]["options"].get("systemMessage", "")
vsr_agent["parameters"]["options"]["systemMessage"] = _vsr_orig_sm + """

IDENTITY VERIFICATION GATE (CRITICAL — v3.1):
Name + state matches alone are NEVER sufficient to accept a candidate as the right person.
Before marking a person 'living' or 'deceased' on the strength of name-only evidence,
you MUST find at least one of these parent-linkage signals:
  - A voter record listing the candidate's address in the expected county/state, AND
    SkipGenie or prior research shows the same address pattern
  - An Ancestry record whose parents[] includes the known parent (root decedent's name)
  - An obituary/SSDI/census entry naming the candidate with the known parent as a relative

If only a name+state match is available (e.g. a random 'Troy Hayes' deed grantor with
no parent linkage), set vital_status='unknown', vital_status_confidence='low',
reason='name-only match — no parent linkage evidence'. The branch will be paused
and surfaced for human review rather than chained off the wrong identity.
"""
vsr_agent["parameters"]["text"] = (
    "={{ `Research vital status for: ${$json.name}\n"
    "Session ID: ${$json.session_id}\nProperty ID: ${$json.property_id}\n"
    "Queue ID: ${$json.queue_id}\nRelationship: ${$json.relationship_hint}\n\n"
    "Expected geography (from property): county=${$('Worker Webhook').first().json.body.county || 'unknown'}, state=${$('Worker Webhook').first().json.body.state || 'NC'}\n"
    "Known parent (for identity verification): ${$('Worker Webhook').first().json.body.deceased_owner || ''}\n\n"
    "SkipGenie candidate:\nName: ${($json.matched_identity || {}).full_name || 'Not found'}\n"
    "DOB: ${($json.matched_identity || {}).dob || 'Unknown'}\n"
    "DOD: ${($json.matched_identity || {}).dod || 'Unknown'}\n"
    "Address: ${($json.matched_identity || {}).address || 'Unknown'}\n"
    "Vital status hint: ${$json.vital_status_hint || 'unknown'}\n\n"
    "Use NC Voter (VSR) and Ancestry Search (VSR) to confirm vital status.\n"
    "Write voter record findings to DB using Write Voter Record (VSR).\n"
    "REQUIRED: apply the Identity Verification Gate. Name+state matches without parent linkage → unknown.\n\n"
    "Output JSON: { vital_status: 'living|deceased|unknown', vital_status_confidence: 'high|medium|low', voter_status: 'Active|Removed|not_found', voter_ncid: '', voter_full_name: '', ssdi_dod: '', identity_evidence: 'parent_linkage_found|name_only|address_match|...', reason: '' }` }}"
)
vsr_model    = v2node("VSR Model") if "VSR Model" in v2_by_name else {**gpt_model("GPT-5-Mini (VSR)", ID["VSR Model"])}
nc_voter_vsr = v2node("NC Voter (VSR)")
anc_vsr      = v2node("Ancestry Search (VSR)")
write_voter_vsr = v2node("Write Voter Record (VSR)")

# Parse Vital Status — updated to use Upsert Person SG context (not Orch-Format-Prompt)
parse_vital_status = code_node(
    "Parse Vital Status", ID["Parse Vital Status"],
    """const vsrRaw = ($input.first().json.output || '').replace(/```json\\n?/g, '').replace(/```/g, '').trim();
const ctx = $('Upsert Person SG').first().json;

let vsr = {};
try {
  const m = vsrRaw.match(/\\{[\\s\\S]*\\}/);
  vsr = JSON.parse(m ? m[0] : vsrRaw);
} catch(e) {
  vsr = { vital_status: 'unknown', reason: 'VSR parse error: ' + vsrRaw.slice(0, 100) };
}

let vital_status = vsr.vital_status || 'unknown';
let vital_confidence = vsr.vital_status_confidence || 'low';

// SkipGenie hint as fallback
const sgHint = ctx.vital_status_hint || '';
if (vital_status === 'unknown' && sgHint === 'deceased') { vital_status = 'deceased'; vital_confidence = 'low'; }
if (vital_status === 'unknown' && sgHint === 'living')   { vital_status = 'living';   vital_confidence = 'low'; }

return [{ json: {
  name:              ctx.name || '',
  property_id:       ctx.property_id,
  session_id:        ctx.session_id,
  queue_id:          ctx.queue_id,
  person_id:         ctx.person_id || null,
  loop_context:      ctx.loop_context || 'worker',
  relationship_hint: ctx.relationship_hint || '',
  maiden_name:       ctx.maiden_name || '',
  matched_identity:  ctx.matched_identity || {},
  vital_status,
  vital_status_confidence: vital_confidence,
  cascade_relatives: ctx.cascade_relatives || [],
  voter_status:    vsr.voter_status || 'not_found',
  voter_ncid:      vsr.voter_ncid || '',
  voter_full_name: vsr.voter_full_name || '',
  vital_status_hint: ctx.vital_status_hint || '',
  notes: '[VSR] ' + (vsr.reason || ''),
} }];""",
)

# Vital Status Gate — unknown → flag and skip
vital_status_gate = if_node(
    "Vital Status Gate", NID["Vital Status Gate"],
    "={{ $json.vital_status }}",
    "notEquals", "unknown",
)

flag_unknown = http_request(
    "Flag Unknown", NID["Flag Unknown"],
    f"{BASE}/heir/upsert-person",
    """={{ {
  session_id:       $json.session_id,
  property_id:      $json.property_id,
  input_name:       $json.name,
  vital_status:     'unknown',
  vital_status_paused: true,
  research_phase:   'paused',
  notes:            'Branch paused: vital status unknown after VSR. Needs human review.',
} }}""",
)

mark_done_unknown = http_request(
    "Mark Done Unknown", NID["Mark Done Unknown"],
    f"{BASE}/heir/complete-person",
    "={{ { \"queue_id\": $('Parse Vital Status').first().json.queue_id } }}",
)

self_trigger_unknown = http_request(
    "Self Trigger Unknown", NID["Self Trigger Unknown"],
    f"{LOCALHOST_N8N}/webhook/heir-worker",
    "={{ { \"session_id\": $('Parse Vital Status').first().json.session_id, \"property_id\": $('Parse Vital Status').first().json.property_id, \"county\": $('Worker Webhook').first().json.body.county || '' } }}",
    timeout=5000,
)

# ODD, SCR, Title Attorney — keep from v2 (they already write to DB via tools)
odd_agent        = v2node("Obituary Deep Diver")

# v3.1 — strengthen identity verification + nudge toward record-detail fetch
_odd_orig_sm = odd_agent["parameters"]["options"].get("systemMessage", "")
odd_agent["parameters"]["options"]["systemMessage"] = _odd_orig_sm + """

v3.1 ADDITIONS:

CANONICAL CHILDREN VIA RECORD DETAIL:
After Ancestry Search (ODD) finds a matching obit, also call Ancestry Record (ODD)
with the record_id (or full source_url) and session_id+property_id. The detail page
carries the canonical structured Child field with full surnames — search results often
truncate to first names only.

IDENTITY VERIFICATION GATE (CRITICAL):
For deceased-confirmation, a name+state-only match is insufficient. You need:
  - parents[] containing the known parent name, OR
  - obit body naming the known parent, OR
  - SSDI/census entry consistent with the known birth/death years AND geography
Otherwise: is_deceased: null, confidence: 'low', notes: 'name-only — no parent linkage'.
This prevents the workflow from accepting a same-name stranger as the heir.
"""

# Prepend session context so the agent can pass session_id/property_id to Write Ancestry Findings
_odd_text = odd_agent["parameters"]["text"]
odd_agent["parameters"]["text"] = (
    "=Session ID: {{ $json.session_id }}\n"
    "Property ID: {{ $json.property_id }}\n"
    "Known parent (for identity verification): {{ $('Worker Webhook').first().json.body.deceased_owner || '' }}\n\n"
    + _odd_text.lstrip("=")
)

brave_search     = v2node("Brave Search")
fetch_obit       = v2node("Fetch Obituary Page")
anc_odd          = v2node("Ancestry Search")
anc_odd["name"] = "Ancestry Search (ODD)"
anc_odd["id"]   = ID["Ancestry Search (ODD)"]
write_anc_odd    = v2node("Write Ancestry Findings")
# Fix records type: without "json" hint n8n coerces the array to the string "[]"
write_anc_odd["parameters"]["jsonBody"] = (
    '={{ { '
    '"session_id": $fromAI("session_id", "The session ID for this heir research run"), '
    '"property_id": $fromAI("property_id", "The property ID"), '
    '"search_name": $fromAI("search_name", "The full name that was searched"), '
    '"search_first": $fromAI("search_first", "First name searched"), '
    '"search_last": $fromAI("search_last", "Last name searched"), '
    '"search_birth_year": $fromAI("search_birth_year", "Birth year used in search, or empty"), '
    '"search_state": $fromAI("search_state", "State searched, default NC"), '
    '"records": $fromAI("records", "Array of relevant Ancestry record objects to save", "json", []) '
    '} }}'
)

# v3.1 — new tool: fetch+save Ancestry record detail (for ODD)
ancestry_record_odd = http_tool(
    "Ancestry Record (ODD)", NID["Ancestry Record (ODD)"],
    (
        "Fetch a specific Ancestry record's full detail page AND save it. "
        "REQUIRED: session_id, property_id, record_id (numeric ID OR full URL). "
        "The detail page returns the canonical structured Child field with full surnames. "
        "Call this after picking the best Ancestry Search (ODD) result."
    ),
    f"{BASE}/ancestry/record-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"record_id": $fromAI("record_id", "Ancestry record_id or full URL"), '
        '"state": $fromAI("state", "State e.g. \'NC\'", "string", "NC") '
        '} }}'
    ),
)
nc_voter_lookup  = v2node("NC Voter Lookup")
odd_model        = v2node("ODD Model") if "ODD Model" in v2_by_name else gpt_model("GPT-5-Mini (ODD)", ID["ODD Model"])
parse_obit_deep  = v2node("Parse Obit Deep")

scr_agent        = v2node("Surname Crosser")
anc_scr          = v2node("Ancestry Search (SCR)")
nc_voter_scr     = v2node("NC Voter (SCR)")
write_voter_scr  = v2node("Write Voter Record (SCR)")
scr_model        = v2node("SCR Model") if "SCR Model" in v2_by_name else gpt_model("GPT-5-Mini (SCR)", ID["SCR Model"])
parse_scr        = v2node("Parse Surname Crosser")

ta_agent         = v2node("Title Attorney")

# Patch TA prompt: fix name variant order + add SE/PR case types + stronger probate pull instructions
_ta_orig_sm = ta_agent["parameters"]["options"].get("systemMessage", "")

# Fix TASK 3c: insert "LAST, FIRST" (no middle) as the FIRST retry variant.
# Without this, the agent skips straight to "HAYES" (noisy) or "ALYCE HAYES",
# missing cases indexed under the stripped form (e.g. 24E002839-910 for Alyce Joye Hayes).
_ta_orig_sm = _ta_orig_sm.replace(
    "## TASK 3c — COURT SEARCH NAME VARIANTS\n"
    "If the initial Court Search by full name returns no estate cases:\n"
    "  1. Retry with last name only (e.g. \"HAYES\" instead of \"HAYES, ALYCE F\")\n"
    "  2. Retry with \"FIRSTNAME LASTNAME\" without comma and without middle initial\n"
    "  3. Try up to 3 variants before concluding no estate exists.\n"
    "  The correct probate may be filed under a slightly different name format.",
    "## TASK 3c — COURT SEARCH NAME VARIANTS\n"
    "If the initial Court Search by full name returns no estate cases:\n"
    "  1. FIRST retry: \"LAST, FIRST\" — drop ALL middle names/initials/suffixes.\n"
    "     e.g. \"HAYES, ALYCE\" instead of \"HAYES, ALYCE JOYE F\"\n"
    "     This is the most important variant: portals index under first+last only.\n"
    "  2. Retry with last name only (e.g. \"HAYES\")\n"
    "  3. Retry with \"FIRSTNAME LASTNAME\" without comma or middle (e.g. \"ALYCE HAYES\")\n"
    "  4. Try up to 4 variants before concluding no estate exists.\n"
    "  The correct probate may be filed under a slightly different spelling or middle name.",
)

ta_agent["parameters"]["options"]["systemMessage"] = _ta_orig_sm + """

## CRITICAL PATCH — PROBATE CASE TYPE COVERAGE
The following case types ALL indicate a filed estate and MUST trigger Court Document Pull:
  - case_type_code "E"  — Decedents' Estate
  - case_type_code "SE" — Decedents' Estate (Small Estate) ← MOST COMMON for recent deaths
  - case_type_code "SP" — Special Proceedings
  - category "PR"       — Probate (any sub-type)
Do NOT skip Court Document Pull just because the case is "Small Estate" (SE). Small Estate filings
contain the same family tree documents as full estate filings. Always pull.

## CRITICAL PATCH — PROBATE DOCUMENT EXTRACTION
When Court Document Pull returns documents, extract and include in Write Court Findings:
  1. named_persons — every person named as heir, beneficiary, or relative in the document
     Format: [{"name": "FIRST LAST", "role": "heir|executor|beneficiary|relative", "has_issue": true/false/null}]
  2. family_tree — structured per-person has_issue array (has_issue=false = confirmed no children)
  3. decedent_name — name of the deceased person whose estate this is
  4. If the document explicitly states a person has no children (no issue): has_issue=false — this CLOSES that branch permanently. Flag it prominently in notes.

## CRITICAL PATCH — WRITE EVERY ESTATE CASE
Call Write Court Findings for EVERY estate/probate case found (E, SE, SP, PR category),
even if Court Document Pull fails or returns empty documents. Record the case number and URL
so the Person Compiler knows a probate exists even when the PDF is inaccessible.
"""

wake_deeds       = v2node("Wake Deeds")
buncombe_deeds   = v2node("Buncombe Deeds")
meck_deeds       = v2node("Mecklenburg Deeds")
court_search     = v2node("Court Search")
reg_actions      = v2node("Register of Actions")
court_doc_pull   = v2node("Court Document Pull")
write_court_ta   = v2node("Write Court Findings")
ta_model         = v2node("TA Model") if "TA Model" in v2_by_name else gpt_model("GPT-5-Mini (TA)", ID["TA Model"])

# Person Compiler Agent — replaces the JS code node
pc_agent = agent_node(
    "Person Compiler", NID["Person Compiler"],
    system_msg="""You are the Person Compiler. Integrate all research findings to build the complete person record and write it to the database.

CONTEXT: Your input has session_id, property_id, person name, vital_status, matched_identity, obit data, cascade_relatives.

STEP 1 — Load Ancestry Records (PC) for this session + person to get all Ancestry findings (obit, SSDI, census).
STEP 2 — Load Court Findings (PC) for this session + person to get estate/probate data.
STEP 3 — Load Voter Records (PC) for this session + person to get voter status confirmation.

STEP 4 — Determine final vital_status (in priority order):
1. If Ancestry SSDI confirms death date: deceased (high confidence)
2. If voter status = Active AND no death evidence: living (high confidence)
3. If obituary confirms death (is_deceased=true in input, confidence=high|medium): deceased
4. If voter status = Removed + SkipGenie deceased flag: deceased (medium confidence)
5. If vital_status from input is already confirmed: use it
6. Otherwise: unknown (DO NOT cascade from unknown)

STEP 5 — Determine cascade_needed:
- cascade_needed = true ONLY when: vital_status='deceased' AND estate_filed=false|null AND no has_issue=false signal
- If estate found with named_persons: cascade_needed=false — probate names heirs directly, use those
- If probate family_tree contains has_issue=false for this person: cascade_needed=false, cascade_relatives=[] — this means the court confirmed they died with NO children. Branch is permanently closed. Do not cascade.

STEP 6 — Compile cascade_relatives (per stirpes cascade targets):
- Priority 0: Probate named_persons — if court findings contain named_persons (heirs/beneficiaries from a probate document), use that list as definitive. These come from a legal filing and are the most authoritative source available.
- Priority 0b: has_issue=false signal — if court findings contain a family_tree entry where has_issue=false for this person, cascade_relatives=[] and cascade_needed=false. Do not add anyone. This overrides all other sources.
- Priority 1: Obituary survivors (named, high/medium confidence obit only)
- Priority 2: Ancestry children records
- Priority 3: Surname Crosser children (SCR)
- Priority 4: SkipGenie possible relatives — ONLY use if relationship_hint is 'child' or 'son' or 'daughter'. NEVER add siblings or parents as cascade targets.
- Merge all sources into ONE deduplicated list. If the same person appears in multiple sources, include them once using the most complete name. Exclude vague entries (HEIRS OF, ESTATE, UNKNOWN, single words).

STEP 7 — Call Write Person (PC) with all compiled data. This is MANDATORY — always write.

After Write Person (PC) returns person_id, output ONLY this JSON:
{
  "person_id": <integer from write response>,
  "session_id": <integer>,
  "property_id": <integer>,
  "queue_id": <integer>,
  "name": "<full name>",
  "vital_status": "living|deceased|unknown",
  "cascade_needed": true/false,
  "cascade_relatives": [{"name": "...", "relationship_hint": "child|spouse|sibling"}]
}""",
    text_expr=(
        "={{ (function() {\n"
        "  const scr = $('Parse Surname Crosser').first().json;\n"
        "  const ta  = $input.first().json.output || '';\n"
        "  return `Compile person record.\\n\\n"
        "Name: ${scr.name}\\nSession: ${scr.session_id}\\nProperty: ${scr.property_id}\\nQueue: ${scr.queue_id}\\n"
        "Person ID (upsert): ${scr.person_id || 'null'}\\n\\n"
        "Vital Status: ${scr.vital_status}\\nConfidence: ${scr.vital_status_confidence || 'low'}\\n"
        "Voter Status: ${scr.voter_status || 'not_found'}\\n"
        "Matched Identity: ${JSON.stringify(scr.matched_identity || {})}\\n\\n"
        "Obit URL: ${scr.obit_url || ''}\\nObit Confidence: ${scr.obit_confidence || 'low'}\\n"
        "Obit Date of Death: ${scr.obit_date_of_death || ''}\\n"
        "Obit Surviving Spouse: ${scr.obit_surviving_spouse || ''}\\n"
        "Cascade Relatives (from research): ${JSON.stringify(scr.cascade_relatives || [])}\\n\\n"
        "Title Attorney output:\\n${ta.substring(0, 1500)}`;\n"
        "})() }}"
    ),
)
pc_model = gpt_model("GPT-5-Mini (Person Compiler)", NID["Person Compiler Model"])

load_anc_pc = http_tool(
    "Load Ancestry Records (PC)", NID["Load Ancestry PC"],
    "Load Ancestry records for this session and person name. Pass session_id and optionally search_name.",
    f"{BASE}/heir/ancestry-records",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "search_name": $fromAI("search_name", "Person name to filter by", "string", null) } }}',
)
load_court_pc = http_tool(
    "Load Court Findings (PC)", NID["Load Court PC"],
    "Load court/probate findings for this session. Pass session_id.",
    f"{BASE}/heir/court-findings",
    '={{ { "session_id": $fromAI("session_id", "Session ID") } }}',
)
load_voter_pc = http_tool(
    "Load Voter Records (PC)", NID["Load Voter PC"],
    "Load NC voter records saved for this session. Pass session_id.",
    f"{BASE}/heir/voter-records",
    '={{ { "session_id": $fromAI("session_id", "Session ID") } }}',
)
write_person_pc = http_tool(
    "Write Person (PC)", NID["Write Person PC"],
    """Write the complete compiled person record to the database. REQUIRED — always call this.
Required: session_id, property_id, input_name, vital_status, cascade_needed.
Include: matched_identity, deceased_facts (date_of_death, marital_status_at_death, surviving_spouse_name, estate_filed, had_will, family_alive_at_death), deed_transfers, obituary_url, obituary_text, claim_sources, cascade_relatives, maiden_name, notes.""",
    f"{BASE}/heir/write-person",
    """={{ {
  "session_id":    $fromAI("session_id", "Session ID"),
  "property_id":   $fromAI("property_id", "Property ID"),
  "input_name":    $fromAI("input_name", "Person name as queued"),
  "vital_status":  $fromAI("vital_status", "living|deceased|unknown"),
  "cascade_needed": $fromAI("cascade_needed", "Whether cascade research is needed", "boolean", false),
  "matched_identity": $fromAI("matched_identity", "SkipGenie matched identity object", "json", {}),
  "deceased_facts":   $fromAI("deceased_facts", "NC Ch. 29 required facts object", "json", {}),
  "deed_transfers":   $fromAI("deed_transfers", "Deed transfer findings", "json", []),
  "obituary_url":     $fromAI("obituary_url", "Obituary URL", "string", ""),
  "obituary_text":    $fromAI("obituary_text", "Full obituary text", "string", ""),
  "claim_sources":    $fromAI("claim_sources", "Evidence attribution object", "json", {}),
  "cascade_relatives": $fromAI("cascade_relatives", "Persons to cascade research to", "json", []),
  "maiden_name":      $fromAI("maiden_name", "Maiden name if applicable", "string", ""),
  "notes":            $fromAI("notes", "Research notes", "string", ""),
  "obituary_named_survivors": $fromAI("obituary_named_survivors", "Named survivors from obit", "json", []),
  "ancestry_named_children":  $fromAI("ancestry_named_children", "Children from Ancestry", "json", [])
} }}""",
)

parse_pc = code_node(
    "Parse Person Compiler", NID["Parse Person Compiler"],
    """const raw = ($input.first().json.output || '').replace(/```json\\n?/g, '').replace(/```/g, '').trim();
const ctx = $('Parse Surname Crosser').first().json;

let parsed = {};
try {
  const m = raw.match(/\\{[\\s\\S]*\\}/);
  parsed = JSON.parse(m ? m[0] : raw);
} catch(e) {
  parsed = {};
}

return [{ json: {
  person_id:        parsed.person_id || null,
  session_id:       parsed.session_id || ctx.session_id,
  property_id:      parsed.property_id || ctx.property_id,
  queue_id:         parsed.queue_id || ctx.queue_id,
  name:             parsed.name || ctx.name || '',
  vital_status:     parsed.vital_status || ctx.vital_status || 'unknown',
  cascade_needed:   !!parsed.cascade_needed,
  cascade_relatives: parsed.cascade_relatives || ctx.cascade_relatives || [],
} }];""",
)

# Branch Decision Agent — applies NC Ch. 29 to decide who to cascade
bd_agent = agent_node(
    "Branch Decision", NID["Branch Decision"],
    system_msg="""You are the Branch Decision Agent. Apply NC Chapter 29 intestate succession rules to decide which persons to queue for cascade research.

INPUT: person_id, session_id, property_id, vital_status, cascade_needed, cascade_relatives.

STEP 1 — Load Person (BD) by person_id to get the authoritative, freshly-written DB record.

STEP 2 — Apply NC Ch. 29 cascade rules:
- IF vital_status = 'deceased' AND cascade_needed = true:
  → The person's share passes to THEIR children (per stirpes)
  → Queue only persons from cascade_relatives who:
    a) Have both first and last name (not "HEIRS OF", "ESTATE", "UNKNOWN")
    b) Are classified as child/heir (relationship_hint = child, heir, son, daughter, grandchild)
    c) Have not already been researched in this session
  → Call Queue Cascade (BD) with the validated list

- IF vital_status = 'living': no cascade needed — output: {"queued": 0, "reason": "person is living"}
- IF vital_status = 'unknown': no cascade (branch is paused) — output: {"queued": 0, "reason": "branch paused - unknown vital status"}
- IF cascade_needed = false (estate found): probate handles succession — output: {"queued": 0, "reason": "estate filed - probate handles succession"}

STEP 3 — Output (include persons_dropped so silent filters surface):
{
  "queued": N,
  "persons_queued": ["NAME1", "NAME2"],
  "persons_dropped": [{"name": "Linda", "reason": "single-token name — not in current research scope"}],
  "reason": "..."
}""",
    text_expr=(
        "={{ `Apply NC Ch. 29 cascade decision for:\\n"
        "Person ID: ${$json.person_id}\\nName: ${$json.name}\\n"
        "Session: ${$json.session_id}\\nProperty: ${$json.property_id}\\nQueue: ${$json.queue_id}\\n"
        "Vital Status: ${$json.vital_status}\\nCascade Needed: ${$json.cascade_needed}\\n\\n"
        "Cascade Relatives:\\n${JSON.stringify($json.cascade_relatives || [])}` }}"
    ),
)
bd_model = gpt_model("GPT-5-Mini (Branch Decision)", NID["Branch Decision Model"])

load_person_bd = http_tool(
    "Load Person (BD)", NID["Load Person BD"],
    "Load person record from DB by person_id. Returns full research record including cascade_needed, vital_status, estate_filed.",
    f"{BASE}/heir/load-person",
    '={{ { "person_id": $fromAI("person_id", "The person_id integer"), "session_id": $fromAI("session_id", "Session ID", "number", null) } }}',
)
queue_cascade_bd = http_tool(
    "Queue Cascade (BD)", NID["Queue Cascade BD"],
    "Queue persons for cascade research. Required: session_id, property_id, persons (array of {name, relationship_hint}). The server deduplicates automatically.",
    f"{BASE}/heir/queue-persons",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "depth": $fromAI("depth", "Depth level for cascade", "number", 1), "persons": $fromAI("persons", "Array of {name, relationship_hint} to queue", "json", []) } }}',
)

mark_person_done = v2node("Mark Person Done")
self_trigger_wkr = v2node("Self Trigger Worker")
self_trigger_wkr["parameters"]["jsonBody"] = (
    '={{ { "session_id": $(\'Worker - Prepare Item\').first().json.session_id,'
    ' "property_id": $(\'Worker - Prepare Item\').first().json.property_id,'
    ' "county": $(\'Worker Webhook\').first().json.body.county || \'\' } }}'
)
check_queue_status = v2node("Check Queue Status")
if_queue_empty   = v2node("If Queue Empty")
claim_fa_trigger = v2node("Claim FA Trigger")
if_fa_claimed    = v2node("If FA Claimed")
trigger_fa       = v2node("Trigger FA Workflow")

# ── Phase 3: Family Assembly — kept from v2 ──────────────────────────────────

fa_webhook     = v2node("FA Webhook")
fa_agent       = v2node("Family Assembler")
load_fam_ds    = v2node("Load Family Dataset")
load_obit_txt  = v2node("Load Obituary Texts")
anc_fa         = v2node("Ancestry Search (FA)")
load_anc_fa    = v2node("Load Ancestry Records")
load_anc_fa["name"] = "Load Ancestry Records (FA)"
load_anc_fa["id"]   = ID["Load Ancestry Records (FA)"]
load_voter_fa  = v2node("Load Voter Records")
load_voter_fa["name"] = "Load Voter Records (FA)"
load_voter_fa["id"]   = ID["Load Voter Records (FA)"]
fa_model       = v2node("FA Model") if "FA Model" in v2_by_name else gpt_model("GPT-5-Mini (FA)", ID["FA Model"])
parse_fa_tree  = v2node("Parse Family Tree")
ie_agent       = v2node("Intestate Expert")
filter_cascade = v2node("Filter Cascade Persons")
ie_model       = v2node("IE Model") if "IE Model" in v2_by_name else gpt_model("GPT-5-Mini (IE)", ID["IE Model"])
parse_ie_out   = v2node("Parse Intestate Output")
more_cascade   = v2node("More Cascade?")
fa_queue_cas   = v2node("FA - Queue Cascade")
fa_queue_cas["name"] = "FA Queue Cascade"
fa_queue_cas["id"]   = ID["FA Queue Cascade"]
fa_trigger_wkr = v2node("FA - Trigger Worker Cascade")
fa_trigger_wkr["name"] = "FA Trigger Worker"
fa_trigger_wkr["id"]   = ID["FA Trigger Worker"]
gen_agent      = v2node("Genealogist")
gen_model      = v2node("Gen Model") if "Gen Model" in v2_by_name else gpt_model("GPT-5-Mini (Gen)", ID["Gen Model"])
write_fam_tree = v2node("Write Family Tree Database")
write_fam_tree["name"] = "Write Family Tree DB"
write_fam_tree["id"]   = ID["Write Family Tree DB"]

# All model nodes already created with gpt-5-mini names above; no post-processing needed.

# ─── Build nodes list ────────────────────────────────────────────────────────

all_nodes = [
    # Phase 1
    webhook, create_session, root_research_agent, root_research_model,
    sg_root_tool, load_prop_tool, anc_root_tool,
    brave_root, fetch_obit_root, nc_voter_root, write_voter_root,
    court_search_root, reg_actions_root, court_doc_root, write_court_root, write_anc_root,
    # v3.1 — new atomic search+save tools
    ancestry_search_save_root, ancestry_record_root,
    write_root_person,
    branch_planner, branch_planner_model, load_anc_bp, load_court_bp, queue_init_heirs,
    # v3.1 — BP partial-name resolution
    ancestry_search_bp,
    trigger_worker_init, respond_to_webhook,

    # Phase 2 – SG waterfall
    worker_webhook, claim_next, if_claimed,
    worker_prepare, parse_attempts,
    sg_try1, got1, sg_try2, got2, sg_try3, got3, sg_try4, got4, sg_try5,
    sg_analyzer, sg_analyzer_model, parse_sg_analyzer, upsert_person_sg,

    # Phase 2 – VSR + gate
    vsr_agent, vsr_model, nc_voter_vsr, anc_vsr, write_voter_vsr,
    parse_vital_status,
    vital_status_gate, flag_unknown, mark_done_unknown, self_trigger_unknown,

    # Phase 2 – ODD
    odd_agent, odd_model, brave_search, fetch_obit, anc_odd, write_anc_odd, nc_voter_lookup,
    ancestry_record_odd,  # v3.1 — record-detail fetch+save for ODD
    parse_obit_deep,

    # Phase 2 – SCR
    scr_agent, scr_model, anc_scr, nc_voter_scr, write_voter_scr, parse_scr,

    # Phase 2 – Title Attorney
    ta_agent, ta_model, wake_deeds, buncombe_deeds, meck_deeds,
    court_search, reg_actions, court_doc_pull, write_court_ta,

    # Phase 2 – Person Compiler + Branch Decision
    pc_agent, pc_model, load_anc_pc, load_court_pc, load_voter_pc, write_person_pc,
    parse_pc,
    bd_agent, bd_model, load_person_bd, queue_cascade_bd,

    # Phase 2 – queue management
    mark_person_done, self_trigger_wkr,
    check_queue_status, if_queue_empty, claim_fa_trigger, if_fa_claimed, trigger_fa,

    # Phase 3
    fa_webhook, fa_agent, fa_model,
    load_fam_ds, load_obit_txt, anc_fa, load_anc_fa, load_voter_fa,
    parse_fa_tree,
    ie_agent, ie_model, filter_cascade,
    parse_ie_out, more_cascade,
    fa_queue_cas, fa_trigger_wkr,
    gen_agent, gen_model, write_fam_tree,
]

# ─── Connections ─────────────────────────────────────────────────────────────

def main(dest: str, idx: int = 0) -> dict:
    return {"node": dest, "type": "main", "index": idx}

def ai_lang(dest: str) -> dict:
    return {"node": dest, "type": "ai_languageModel", "index": 0}

def ai_tool(dest: str) -> dict:
    return {"node": dest, "type": "ai_tool", "index": 0}

connections = {
    # ── Phase 1 ──────────────────────────────────────────────────────────────
    "Webhook": {"main": [[main("Create Heir Session")]]},
    "Create Heir Session": {"main": [[main("Root Owner Research")]]},
    # Root Research tools → agent
    "GPT-5-Mini (Root Research)":  {"ai_languageModel": [[ai_lang("Root Owner Research")]]},
    "SkipGenie — Root Decedent":   {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Load Property State":         {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Ancestry Search Root":        {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Brave Search Root":           {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Fetch Obit Root":             {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "NC Voter Root":               {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Write Voter Root":            {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Court Search Root":           {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Register Actions Root":       {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Court Doc Root":              {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Write Court Root":            {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Write Ancestry Root":         {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    # v3.1 — atomic search+save and record-detail tools
    "Ancestry Search Save Root":   {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Ancestry Record Root":        {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    # Root Research → Write Root Person → Branch Planner
    "Root Owner Research":  {"main": [[main("Write Root Person")]]},
    "Write Root Person":    {"main": [[main("Branch Planner")]]},
    # Branch Planner tools → agent
    "GPT-5-Mini (Branch Planner)":   {"ai_languageModel": [[ai_lang("Branch Planner")]]},
    "Load Ancestry Records (BP)":    {"ai_tool":          [[ai_tool("Branch Planner")]]},
    "Load Court Findings (BP)":      {"ai_tool":          [[ai_tool("Branch Planner")]]},
    "Queue Initial Heirs":           {"ai_tool":          [[ai_tool("Branch Planner")]]},
    # v3.1 — partial-name resolution via parent-mode lookup
    "Ancestry Search (BP)":          {"ai_tool":          [[ai_tool("Branch Planner")]]},
    # Branch Planner → Trigger Worker → Respond
    "Branch Planner":    {"main": [[main("Trigger Worker Init")]]},
    "Trigger Worker Init":  {"main": [[main("Respond to Webhook")]]},

    # ── Phase 2: Claim + SG waterfall ────────────────────────────────────────
    "Worker Webhook":    {"main": [[main("Claim Next Person")]]},
    "Claim Next Person": {"main": [[main("If Person Claimed")]]},
    "If Person Claimed": {
        "main": [
            [main("Worker - Prepare Item")],  # 0 = claimed
            [main("Check Queue Status")],     # 1 = not claimed
        ]
    },
    "Worker - Prepare Item": {"main": [[main("Parse Attempts")]]},
    "Parse Attempts":         {"main": [[main("SkipGenie Try 1")]]},
    "SkipGenie Try 1":  {"main": [[main("Got Results 1?")]]},
    "Got Results 1?": {
        "main": [
            [main("SG Analyzer")],   # 0 = got results
            [main("SkipGenie Try 2")],  # 1 = no results
        ]
    },
    "SkipGenie Try 2":  {"main": [[main("Got Results 2?")]]},
    "Got Results 2?": {
        "main": [
            [main("SG Analyzer")],
            [main("SkipGenie Try 3")],
        ]
    },
    "SkipGenie Try 3":  {"main": [[main("Got Results 3?")]]},
    "Got Results 3?": {
        "main": [
            [main("SG Analyzer")],
            [main("SkipGenie Try 4")],
        ]
    },
    "SkipGenie Try 4":  {"main": [[main("Got Results 4?")]]},
    "Got Results 4?": {
        "main": [
            [main("SG Analyzer")],
            [main("SkipGenie Try 5")],
        ]
    },
    "SkipGenie Try 5": {"main": [[main("SG Analyzer")]]},
    # SG Analyzer tools → agent
    "GPT-5-Mini (SG Analyzer)": {"ai_languageModel": [[ai_lang("SG Analyzer")]]},
    # SG Analyzer → Parse → Upsert → VSR
    "SG Analyzer":       {"main": [[main("Parse SG Analyzer")]]},
    "Parse SG Analyzer": {"main": [[main("Upsert Person SG")]]},
    "Upsert Person SG":  {"main": [[main("Vital Status Researcher")]]},
    # VSR tools → agent
    "GPT-5-Mini (VSR)":          {"ai_languageModel": [[ai_lang("Vital Status Researcher")]]},
    "NC Voter (VSR)":            {"ai_tool":          [[ai_tool("Vital Status Researcher")]]},
    "Ancestry Search (VSR)":     {"ai_tool":          [[ai_tool("Vital Status Researcher")]]},
    "Write Voter Record (VSR)":  {"ai_tool":          [[ai_tool("Vital Status Researcher")]]},
    # VSR → Parse Vital Status → Vital Status Gate
    "Vital Status Researcher": {"main": [[main("Parse Vital Status")]]},
    "Parse Vital Status":      {"main": [[main("Vital Status Gate")]]},
    # Gate branches
    "Vital Status Gate": {
        "main": [
            [main("Obituary Deep Diver")],  # 0 = known (not unknown)
            [main("Flag Unknown")],         # 1 = unknown
        ]
    },
    # Unknown branch: flag → mark done → self trigger
    "Flag Unknown":        {"main": [[main("Mark Done Unknown")]]},
    "Mark Done Unknown":   {"main": [[main("Self Trigger Unknown")]]},

    # ── Phase 2: ODD ─────────────────────────────────────────────────────────
    # ODD tools → agent
    "GPT-5-Mini (ODD)":         {"ai_languageModel": [[ai_lang("Obituary Deep Diver")]]},
    "Brave Search":             {"ai_tool":          [[ai_tool("Obituary Deep Diver")]]},
    "Fetch Obituary Page":      {"ai_tool":          [[ai_tool("Obituary Deep Diver")]]},
    "Ancestry Search (ODD)":    {"ai_tool":          [[ai_tool("Obituary Deep Diver")]]},
    "Write Ancestry Findings":  {"ai_tool":          [[ai_tool("Obituary Deep Diver")]]},
    "NC Voter Lookup":          {"ai_tool":          [[ai_tool("Obituary Deep Diver")]]},
    # v3.1 — record-detail fetch for canonical Child field
    "Ancestry Record (ODD)":    {"ai_tool":          [[ai_tool("Obituary Deep Diver")]]},
    "Obituary Deep Diver": {"main": [[main("Parse Obit Deep")]]},
    "Parse Obit Deep":     {"main": [[main("Surname Crosser")]]},

    # ── Phase 2: SCR ─────────────────────────────────────────────────────────
    "GPT-5-Mini (SCR)":           {"ai_languageModel": [[ai_lang("Surname Crosser")]]},
    "Ancestry Search (SCR)":      {"ai_tool":          [[ai_tool("Surname Crosser")]]},
    "NC Voter (SCR)":             {"ai_tool":          [[ai_tool("Surname Crosser")]]},
    "Write Voter Record (SCR)":   {"ai_tool":          [[ai_tool("Surname Crosser")]]},
    "Surname Crosser": {"main": [[main("Parse Surname Crosser")]]},
    "Parse Surname Crosser": {"main": [[main("Title Attorney")]]},

    # ── Phase 2: Title Attorney ───────────────────────────────────────────────
    "GPT-5-Mini (TA)":     {"ai_languageModel": [[ai_lang("Title Attorney")]]},
    "Wake Deeds":          {"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Buncombe Deeds":      {"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Mecklenburg Deeds":   {"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Court Search":        {"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Register of Actions": {"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Court Document Pull": {"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Write Court Findings":{"ai_tool":          [[ai_tool("Title Attorney")]]},
    "Title Attorney": {"main": [[main("Person Compiler")]]},

    # ── Phase 2: Person Compiler ──────────────────────────────────────────────
    "GPT-5-Mini (Person Compiler)": {"ai_languageModel": [[ai_lang("Person Compiler")]]},
    "Load Ancestry Records (PC)":   {"ai_tool":          [[ai_tool("Person Compiler")]]},
    "Load Court Findings (PC)":     {"ai_tool":          [[ai_tool("Person Compiler")]]},
    "Load Voter Records (PC)":      {"ai_tool":          [[ai_tool("Person Compiler")]]},
    "Write Person (PC)":            {"ai_tool":          [[ai_tool("Person Compiler")]]},
    "Person Compiler": {"main": [[main("Parse Person Compiler")]]},
    "Parse Person Compiler": {"main": [[main("Branch Decision")]]},

    # ── Phase 2: Branch Decision ──────────────────────────────────────────────
    "GPT-5-Mini (Branch Decision)": {"ai_languageModel": [[ai_lang("Branch Decision")]]},
    "Load Person (BD)":             {"ai_tool":          [[ai_tool("Branch Decision")]]},
    "Queue Cascade (BD)":           {"ai_tool":          [[ai_tool("Branch Decision")]]},
    "Branch Decision": {"main": [[main("Mark Person Done")]]},
    "Mark Person Done": {"main": [[main("Self Trigger Worker")]]},

    # ── Phase 2: Queue management ─────────────────────────────────────────────
    "Check Queue Status": {"main": [[main("If Queue Empty")]]},
    "If Queue Empty": {
        "main": [
            [main("Claim FA Trigger")],  # 0 = empty
            [main("Self Trigger Worker")],  # 1 = not empty (still processing)
        ]
    },
    "Claim FA Trigger": {"main": [[main("If FA Claimed")]]},
    "If FA Claimed": {
        "main": [
            [main("Trigger FA Workflow")],  # 0 = claimed
            [],  # 1 = not claimed (another worker already triggered FA)
        ]
    },

    # ── Phase 3: Family Assembly ──────────────────────────────────────────────
    "FA Webhook": {"main": [[main("Family Assembler")]]},
    "GPT-5-Mini (FA)":            {"ai_languageModel": [[ai_lang("Family Assembler")]]},
    "Load Family Dataset":        {"ai_tool":          [[ai_tool("Family Assembler")]]},
    "Load Obituary Texts":        {"ai_tool":          [[ai_tool("Family Assembler")]]},
    "Ancestry Search (FA)":       {"ai_tool":          [[ai_tool("Family Assembler")]]},
    "Load Ancestry Records (FA)": {"ai_tool":          [[ai_tool("Family Assembler")]]},
    "Load Voter Records (FA)":    {"ai_tool":          [[ai_tool("Family Assembler")]]},
    "Family Assembler": {"main": [[main("Parse Family Tree")]]},
    "Parse Family Tree": {"main": [[main("Intestate Expert")]]},
    "GPT-5-Mini (IE)":           {"ai_languageModel": [[ai_lang("Intestate Expert")]]},
    "Filter Cascade Persons":    {"ai_tool":          [[ai_tool("Intestate Expert")]]},
    "Intestate Expert": {"main": [[main("Parse Intestate Output")]]},
    "Parse Intestate Output": {"main": [[main("More Cascade?")]]},
    "More Cascade?": {
        "main": [
            [main("FA Queue Cascade")],  # 0 = more cascade
            [main("Genealogist")],       # 1 = done
        ]
    },
    "FA Queue Cascade": {"main": [[main("FA Trigger Worker")]]},
    "GPT-5-Mini (Gen)":        {"ai_languageModel": [[ai_lang("Genealogist")]]},
    "Write Family Tree DB":    {"ai_tool":          [[ai_tool("Genealogist")]]},
}

# ─── Node positions ──────────────────────────────────────────────────────────
# Layout:
#   Phase 1 main flow  → y=0,    x increases left-to-right
#   Phase 1 tools      → y=200+  below their agent
#   Phase 2 main flow  → y=1600, x increases left-to-right
#   Phase 2 tools      → y=1800+ below their agent
#   Phase 3 main flow  → y=3600, x increases left-to-right
#   Phase 3 tools      → y=3800+ below their agent
#
# Main-flow horizontal step: 260px
# Tool vertical step: 180px   (tools stack downward)
# Tool horizontal column 1: agent_x - 220
# Tool horizontal column 2: agent_x
# Tool horizontal column 3: agent_x + 220
# Model node: agent_x + 220, agent_y + 200

POS: dict[str, list[int]] = {
    # ── Phase 1 main flow (y=0) ───────────────────────────────────────────────
    "Webhook":                   [0,    0],
    "Create Heir Session":       [260,  0],
    "Root Owner Research":       [520,  0],
    "Write Root Person":         [820,  0],
    "Branch Planner":            [1100, 0],
    "Trigger Worker Init":       [1380, 0],
    "Respond to Webhook":        [1640, 0],

    # Root Research model + tools (below agent at x=520)
    "GPT-5-Mini (Root Research)": [760,  200],
    "Load Property State":        [300,  200],
    "SkipGenie — Root Decedent":  [300,  380],
    "Ancestry Search Root":       [300,  560],
    "Brave Search Root":          [300,  740],
    "Fetch Obit Root":            [300,  920],
    "NC Voter Root":              [300,  1100],
    "Write Voter Root":           [300,  1280],
    "Court Search Root":          [520,  380],
    "Register Actions Root":      [520,  560],
    "Court Doc Root":             [520,  740],
    "Write Court Root":           [520,  920],
    "Write Ancestry Root":        [520,  1100],

    # Branch Planner model + tools (below agent at x=1100)
    "GPT-5-Mini (Branch Planner)": [1340, 200],
    "Load Ancestry Records (BP)":  [1100, 200],
    "Load Court Findings (BP)":    [1100, 380],
    "Queue Initial Heirs":         [1100, 560],

    # ── Phase 2: SG waterfall (y=1600) ───────────────────────────────────────
    "Worker Webhook":          [0,    1600],
    "Claim Next Person":       [220,  1600],
    "If Person Claimed":       [440,  1600],
    "Worker - Prepare Item":   [680,  1600],
    "Parse Attempts":          [900,  1600],
    "SkipGenie Try 1":         [1120, 1600],
    "Got Results 1?":          [1320, 1600],
    "SkipGenie Try 2":         [1320, 1780],
    "Got Results 2?":          [1500, 1780],
    "SkipGenie Try 3":         [1500, 1960],
    "Got Results 3?":          [1660, 1960],
    "SkipGenie Try 4":         [1660, 2140],
    "Got Results 4?":          [1820, 2140],
    "SkipGenie Try 5":         [1820, 2320],

    # Queue management branch (from If Person Claimed output[1] → not claimed)
    "Check Queue Status":      [440,  1800],
    "If Queue Empty":          [660,  1800],
    "Claim FA Trigger":        [880,  1800],
    "If FA Claimed":           [1100, 1800],
    "Trigger FA Workflow":     [1320, 1800],

    # ── Phase 2: SG Analyzer + Upsert (converge point from waterfall) ─────────
    "SG Analyzer":             [2080, 1960],
    "GPT-5-Mini (SG Analyzer)":[2300, 2140],
    "Parse SG Analyzer":       [2340, 1960],
    "Upsert Person SG":        [2600, 1960],

    # ── Phase 2: VSR (y=1960 continuing right) ───────────────────────────────
    "Vital Status Researcher":    [2860, 1960],
    "GPT-5-Mini (VSR)":           [3100, 2140],
    "NC Voter (VSR)":             [2640, 2140],
    "Ancestry Search (VSR)":      [2640, 2320],
    "Write Voter Record (VSR)":   [2640, 2500],

    "Parse Vital Status":         [3120, 1960],
    "Vital Status Gate":          [3380, 1960],

    # Unknown branch (drops down from gate)
    "Flag Unknown":               [3380, 2160],
    "Mark Done Unknown":          [3600, 2160],
    "Self Trigger Unknown":       [3820, 2160],

    # ── Phase 2: ODD (y=1960 continuing right from gate) ─────────────────────
    "Obituary Deep Diver":        [3640, 1960],
    "GPT-5-Mini (ODD)":           [3880, 2140],
    "Brave Search":               [3420, 2140],
    "Fetch Obituary Page":        [3420, 2320],
    "Ancestry Search (ODD)":      [3420, 2500],
    "Write Ancestry Findings":    [3420, 2680],
    "NC Voter Lookup":            [3420, 2860],

    "Parse Obit Deep":            [3900, 1960],

    # ── Phase 2: SCR ──────────────────────────────────────────────────────────
    "Surname Crosser":            [4160, 1960],
    "GPT-5-Mini (SCR)":           [4400, 2140],
    "Ancestry Search (SCR)":      [3940, 2140],
    "NC Voter (SCR)":             [3940, 2320],
    "Write Voter Record (SCR)":   [3940, 2500],

    "Parse Surname Crosser":      [4420, 1960],

    # ── Phase 2: Title Attorney ───────────────────────────────────────────────
    "Title Attorney":             [4680, 1960],
    "GPT-5-Mini (TA)":            [4920, 2140],
    "Wake Deeds":                 [4460, 2140],
    "Buncombe Deeds":             [4460, 2320],
    "Mecklenburg Deeds":          [4460, 2500],
    "Court Search":               [4460, 2680],
    "Register of Actions":        [4460, 2860],
    "Court Document Pull":        [4460, 3040],
    "Write Court Findings":       [4460, 3220],

    # ── Phase 2: Person Compiler ──────────────────────────────────────────────
    "Person Compiler":            [4940, 1960],
    "GPT-5-Mini (Person Compiler)":[5180, 2140],
    "Load Ancestry Records (PC)": [4720, 2140],
    "Load Court Findings (PC)":   [4720, 2320],
    "Load Voter Records (PC)":    [4720, 2500],
    "Write Person (PC)":          [4720, 2680],

    "Parse Person Compiler":      [5200, 1960],

    # ── Phase 2: Branch Decision ──────────────────────────────────────────────
    "Branch Decision":            [5460, 1960],
    "GPT-5-Mini (Branch Decision)":[5700, 2140],
    "Load Person (BD)":           [5240, 2140],
    "Queue Cascade (BD)":         [5240, 2320],

    "Mark Person Done":           [5720, 1960],
    "Self Trigger Worker":        [5980, 1960],

    # ── Phase 3: Family Assembly (y=3600) ─────────────────────────────────────
    "FA Webhook":                 [0,    3600],
    "Family Assembler":           [260,  3600],
    "GPT-5-Mini (FA)":            [500,  3800],
    "Load Family Dataset":        [40,   3800],
    "Load Obituary Texts":        [40,   3980],
    "Ancestry Search (FA)":       [40,   4160],
    "Load Ancestry Records (FA)": [40,   4340],
    "Load Voter Records (FA)":    [40,   4520],

    "Parse Family Tree":          [560,  3600],
    "Intestate Expert":           [820,  3600],
    "GPT-5-Mini (IE)":            [1060, 3800],
    "Filter Cascade Persons":     [600,  3800],

    "Parse Intestate Output":     [1080, 3600],
    "More Cascade?":              [1340, 3600],
    "FA Queue Cascade":           [1600, 3600],
    "FA Trigger Worker":          [1860, 3600],

    "Genealogist":                [1600, 3800],
    "GPT-5-Mini (Gen)":           [1840, 3980],
    "Write Family Tree DB":       [1380, 3980],
}

# Apply positions — any node not in POS keeps [0,0]
def _apply_positions(nodes: list[dict]) -> None:
    for node in nodes:
        if node["name"] in POS:
            node["position"] = POS[node["name"]]

# ─── Assemble workflow ───────────────────────────────────────────────────────

# Deduplicate nodes by ID (last definition wins)
seen_ids: dict[str, dict] = {}
for node in all_nodes:
    seen_ids[node["id"]] = node

_apply_positions(list(seen_ids.values()))

workflow_v3 = {
    "name": "Heir Tracer v3",
    "nodes": list(seen_ids.values()),
    "connections": connections,
    "active": False,
    "settings": v2.get("settings", {}),
    "versionId": str(uuid.uuid4()),
    "meta": {"instanceId": v2.get("meta", {}).get("instanceId", "")},
    "tags": [],
}

out_path = r"C:\Users\Summer Ishi\Github\TitleMatrix\ScraperSystems\others\heirtracer\workflow_v3_local.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(workflow_v3, f, indent=2, ensure_ascii=False)

print(f"Written {len(workflow_v3['nodes'])} nodes to workflow_v3_local.json")
print(f"Connections: {len(connections)} source nodes")
