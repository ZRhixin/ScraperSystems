"""
Build workflow_v4_local.json — the v4 heir tracer workflow.

Key changes from v3:
1. Write Root Person now triggers Orchestrator Webhook (not Branch Planner)
2. Worker Loop (Branch Planner → Genealogist) REMOVED entirely
3. NEW: Orchestrator Webhook + Heir Research Orchestrator agent (researches ONE person per invocation)
4. NEW: Court Researcher sub-workflow (called as tool by Orchestrator)
5. NEW: Simplified Family Assembly (no research agents — just Load + NC Ch.29 + Write)
6. n8n manages the loop externally: Mark Done → Check Queue → If Empty → Self Trigger or Trigger FA
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
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"heirtracer-v4-{tag}"))

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

def agent_tool_node(name: str, node_id: str, tool_description: str, system_msg: str, text_expr: str, max_iter: int = 20) -> dict:
    """Agent node wired as a tool to a parent agent (agentTool type)."""
    return {
        "id": node_id,
        "name": name,
        "type": "@n8n/n8n-nodes-langchain.agentTool",
        "typeVersion": 3,
        "position": [0, 0],
        "rewireOutputLogTo": "ai_tool",
        "parameters": {
            "toolDescription": tool_description,
            "text": text_expr,
            "options": {
                "systemMessage": system_msg,
                "maxIterations": max_iter,
            },
        },
    }

def agent_node(name: str, node_id: str, system_msg: str, text_expr: str, max_iter: int = 30) -> dict:
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
                "maxIterations": max_iter,
            },
        },
    }

def http_tool(name: str, node_id: str, description: str, url: str, body_expr: str, method: str = "POST") -> dict:
    node = {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.2,
        "position": [0, 0],
        "parameters": {
            "toolDescription": description,
            "method": method,
            "url": url,
        },
    }
    if method == "GET":
        node["parameters"]["sendQuery"] = True
        node["parameters"]["queryParameters"] = {
            "parameters": []
        }
        # For GET tools we embed query logic differently; use sendBody=False
        # Store body_expr in a custom key for reference — actual GET tools use queryParameters
        node["parameters"]["_body_expr_ref"] = body_expr
    else:
        node["parameters"]["sendBody"] = True
        node["parameters"]["specifyBody"] = "json"
        node["parameters"]["jsonBody"] = body_expr
    return node

def http_tool_get(name: str, node_id: str, description: str, url: str) -> dict:
    """GET-based tool node — URL is a template expression."""
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.2,
        "position": [0, 0],
        "parameters": {
            "toolDescription": description,
            "method": "GET",
            "url": url,
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
        "notExists": {"type": "string", "operation": "notExists"},
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

# ─── load v3 JSON to reuse existing node structures ──────────────────────────

with open(
    r"C:\Users\Summer Ishi\Github\TitleMatrix\ScraperSystems\others\heirtracer\workflow_v3_local.json",
    encoding="utf-8",
) as f:
    v3 = json.load(f)

v3_by_name = {n["name"]: n for n in v3["nodes"]}

def v3node(name: str) -> dict:
    """Return a deep copy of a v3 node."""
    return json.loads(json.dumps(v3_by_name[name]))


# ─── Stable IDs ──────────────────────────────────────────────────────────────

# Phase 1 IDs: reuse from v3 (same nodes, same IDs)
ID = {
    "Webhook":                  "9959105c-ab2e-41d0-bb48-55fd0b1e0e2c",
    "Create Heir Session":      "bab81353-0323-4b24-8cb1-48f40cef7a48",
    "Root Owner Research":      "251f3f2d-778d-4c40-81af-2d4131847cf5",
    "Root Research Model":      "bb3e5e39-0209-4d0a-98c8-4cf7f447a15f",
    "SkipGenie Root Decedent":  "7856bcf4-f058-4d5c-87ad-fbed5a1cbeba",
    "Load Property State":      "31d0b388-2083-4f6c-a499-2e83ab68f12f",
    "Ancestry Search Root":     "ancestry-search-root-001",
    "Respond to Webhook":       "d1c12ac6-7309-4623-8958-1c0c23a88b27",

    # FA — kept IDs
    "FA Webhook":               "7175b1ac-8888-4e4a-a2bf-f9fafbfcfdfe",
    "FA Model":                 "ba87704d-d33f-4086-8aef-ff0001020304",
    "Load Family Dataset":      "4167c98d-e14b-4561-a8af-fafbfcfdfeff",
    "Write Family Tree DB":     "4dee479e-6707-42e3-8baf-09000b0c0d0e",
}

# New v4 node IDs — all stable via nid()
NID = {k: nid(k) for k in [
    # Phase 1 — tools reused from v3 but with new IDs referencing v4 namespace
    "Brave Search Root", "Fetch Obit Root", "NC Voter Root", "Write Voter Root",
    "Court Search Root", "Reg Actions Root", "Court Doc Root",
    "Write Court Root", "Write Ancestry Root",
    "Ancestry Search Save Root", "Ancestry Record Root",
    "Ancestry Household Root",
    "Write Root Person",

    # Phase 1 → Orchestrator trigger
    "Queue Initial Relatives",
    "Trigger Orchestrator Init",

    # Orchestrator Workflow
    "Orchestrator Webhook",
    "Heir Research Orchestrator",
    "Orch Model",

    # Orchestrator tools — research
    "SkipGenie (Orch)",
    "NC Voter (Orch)",
    "Ancestry Search Save (Orch)",
    "Ancestry Record (Orch)",
    "Brave Search (Orch)",
    "Fetch Obituary Page (Orch)",
    "Wake Deeds (Orch)",
    "Buncombe Deeds (Orch)",
    "Mecklenburg Deeds (Orch)",

    # Orchestrator tools — census
    "Ancestry Household (Orch)",

    # Orchestrator tools — DB reads
    "Load Property State (Orch)",
    "Load Person (Orch)",
    "Load Ancestry Records (Orch)",
    "Load Court Findings (Orch)",
    "Load Voter Records (Orch)",

    # Orchestrator tools — DB writes
    "Write Person (Orch)",
    "Write Voter Record (Orch)",
    "Queue Persons (Orch)",

    # Orchestrator tools — sub-agents (HTTP webhook)
    "Court Researcher Tool",

    # Ancestry Selector Agent (AI tool wired to Orchestrator)
    "Ancestry Selector Agent",
    "Ancestry Selector Model",
    "Ancestry Search Save (AS)",
    "Ancestry Record (AS)",

    # SkipGenie Resolver Agent (AI tool wired to Orchestrator)
    "SkipGenie Resolver Agent",
    "SkipGenie Resolver Model",
    "SkipGenie (SR)",
    "Write Person (SR)",

    # Orchestrator queue management nodes
    "Mark Person Done (Orch)",
    "Check Queue Status (Orch)",
    "If Queue Empty (Orch)",
    "Self Trigger Orchestrator",
    "Trigger Family Assembly",

    # Court Researcher sub-workflow
    "Court Researcher Webhook",
    "Court Researcher Agent",
    "Court Researcher Model",
    "Court Search (CR)",
    "Register of Actions (CR)",
    "Court Document Pull (CR)",
    "Write Court Findings (CR)",
    "Return Court Result",

    # Family Assembly (simplified)
    "Family Assembler",
    "FA Model v4",
    "Load Family Dataset (FA)",
    "Write Family Tree (FA)",
]}


# ─── Phase 1: Root Research — reused from v3 ─────────────────────────────────

webhook        = v3node("Webhook")
webhook["parameters"]["responseMode"] = "onReceived"
create_session = v3node("Create Heir Session")
root_research_agent = v3node("Root Owner Research")
# Patch: inject SkipGenie address strategy (street_address + zip_code from Load Property State)
import re as _re
_root_sys = root_research_agent["parameters"]["options"]["systemMessage"]
_root_sys = _re.sub(
    r"2\. Search SkipGenie for the decedent\. Pass first_name.*?Do not stop\.",
    (
        "2. Search SkipGenie for the decedent. "
        "Load Property State runs first (step 1) — use its output to pass: "
        "first_name, last_name, state=\"NC\", "
        "city=<property city> (e.g. \"Wake Forest\"), "
        "zip_code=<property zip>, "
        "AND street_address=<property street address> (e.g. \"631 E Nelson Ave\"). "
        "The street address is the single most effective filter — it surfaces people who lived at or near the property. "
        "Name + state alone returns nothing; city/zip/street together are far more precise. "
        "SkipGenie is helpful but optional — if it returns no match, continue through ALL remaining steps using the property owner name directly. Do not stop."
    ),
    _root_sys,
    flags=_re.DOTALL,
)
# Fix step 4c: warn that parent-mode into collection 61843 (obituaries) returns noise
_root_sys = _re.sub(
    r"4c\. \*\*Parent-mode discovery\*\*.*?wouldn't appear in the direct search\.",
    (
        "4c. **Parent-mode discovery — WARNING: DO NOT USE collection_id='61843' with mother= or father=.** "
        "The obituary index does not store parent names as structured fields — passing mother= or father= into collection_id='61843' returns 39,000+ noise results and will not find children. "
        "Skip this step entirely. Use step 4d (census household) instead to find siblings/children."
    ),
    _root_sys,
    flags=_re.DOTALL,
)
# Fix step 4d: add household followup after finding census anchor record
_root_sys = _re.sub(
    r"4d\. \*\*Census discovery\*\*.*?in Lydia Hayes's case\)\.",
    (
        "4d. **Census discovery** — call Ancestry Search Save Root with last_name=<root surname> + first_name=<root first name> + state=\"NC\" + collection_id=\"2442\" (1940 census). "
        "Find a census record for the root or a known family member. "
        "**Record selection for census:** Hard-reject any record whose birth_location or residence is outside North Carolina (e.g. New Jersey, Virginia, Georgia). "
        "Among NC records, prefer dob closest to the root's known birth year (inferred from SkipGenie dob or dod minus age). "
        "4d-b. **MANDATORY followup** — take the source_url from the best NC census hit in step 4d and call Ancestry Household Root. "
        "This returns all household members with relationship_to_head (Son/Daughter/Wife/etc.). "
        "Children listed here are siblings who may not appear in any obituary — add them to cascade_relatives. "
        "NOTE: source_url may be empty in search results; if so, construct it as: "
        "https://www.ancestry.com/search/collections/<collection_id>/records/<record_id>"
    ),
    _root_sys,
    flags=_re.DOTALL,
)
root_research_agent["parameters"]["options"]["systemMessage"] = _root_sys
root_research_model = v3node("GPT-5-Mini (Root Research)")
sg_root_tool   = v3node("SkipGenie — Root Decedent")
load_prop_tool = v3node("Load Property State")
anc_root_tool  = v3node("Ancestry Search Root")
brave_root     = v3node("Brave Search Root")
fetch_obit_root = v3node("Fetch Obit Root")
nc_voter_root  = v3node("NC Voter Root")
write_voter_root = v3node("Write Voter Root")
court_search_root = v3node("Court Search Root")
reg_actions_root = v3node("Register Actions Root")
court_doc_root = v3node("Court Doc Root")
write_court_root = v3node("Write Court Root")
write_anc_root = v3node("Write Ancestry Root")
ancestry_search_save_root = v3node("Ancestry Search Save Root")
ancestry_record_root = v3node("Ancestry Record Root")

anc_household_root = http_tool(
    "Ancestry Household Root", NID["Ancestry Household Root"],
    (
        "Fetch all members of the same census household given any Ancestry census record URL. "
        "Use after step 4d when you have a census source_url — returns all household members with relationship_to_head. "
        "Children appear as 'Son' or 'Daughter'. More reliable than obituary parent searches for finding all siblings."
    ),
    f"{BASE}/ancestry/household",
    '={{ { "record_url": $fromAI("record_url", "Ancestry census record URL from step 4d search result source_url field") } }}',
)

# Write Root Person — same logic as v3 but triggers Orchestrator instead of Branch Planner
write_root_person = v3node("Write Root Person")
# ID stays same as v3
write_root_person["id"] = NID["Write Root Person"]

# Queue Initial Relatives — queues ALL cascade_relatives from Root Owner Research upfront.
# This ensures all children/heirs are in the queue before the orchestrator loop starts.
queue_initial_relatives = http_request(
    "Queue Initial Relatives", NID["Queue Initial Relatives"],
    f"{BASE}/heir/queue-persons",
    """={{ (function() {
  try {
    const raw = $('Root Owner Research').first().json.output || '';
    const cleaned = raw.replace(/```json\\n?/g, '').replace(/```/g, '').trim();
    const m = cleaned.match(/\\{[\\s\\S]*\\}/);
    const parsed = JSON.parse(m ? m[0] : cleaned);
    const sess = $('Create Heir Session').first().json;
    const relatives = parsed.cascade_relatives || [];
    return {
      session_id: sess.session_id,
      property_id: sess.property_id,
      depth: 1,
      persons: relatives.map(r => ({
        name: r.name,
        relationship_hint: r.relationship_hint || 'child',
        maiden_name: r.maiden_name || null,
        depth: 1,
      })),
    };
  } catch(e) {
    const sess = $('Create Heir Session').first().json;
    return { session_id: sess.session_id, property_id: sess.property_id, persons: [], _error: e.message };
  }
})() }}""",
)

# Trigger Orchestrator Init — fires after Queue Initial Relatives with the first queued person.
trigger_orch_init = http_request(
    "Trigger Orchestrator Init", NID["Trigger Orchestrator Init"],
    f"{LOCALHOST_N8N}/webhook/heir-orchestrator",
    """={{ (function() {
  try {
    const q = $('Queue Initial Relatives').first().json;
    const sess = $('Create Heir Session').first().json;
    const firstQueued = (q.queued || [])[0] || null;
    if (!firstQueued) {
      return {
        session_id: sess.session_id,
        property_id: sess.property_id,
        county: sess.county || '',
        person_name: '',
        relationship_hint: '',
        queue_id: null,
        _no_persons: true,
      };
    }
    return {
      session_id: sess.session_id,
      property_id: sess.property_id,
      county: sess.county || '',
      person_name: firstQueued.person_name,
      relationship_hint: firstQueued.person_name || 'child',
      maiden_name: firstQueued.maiden_name || '',
      queue_id: firstQueued.queue_id,
    };
  } catch(e) {
    const sess = $('Create Heir Session').first().json;
    return {
      session_id: sess.session_id,
      property_id: sess.property_id,
      county: sess.county || '',
      person_name: '',
      relationship_hint: '',
      queue_id: null,
      _error: e.message,
    };
  }
})() }}""",
    timeout=5000,
)


# ─── Workflow 2: Heir Research Orchestrator ───────────────────────────────────

orchestrator_webhook = {
    "id": NID["Orchestrator Webhook"],
    "name": "Orchestrator Webhook",
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 2.1,
    "position": [0, 0],
    "parameters": {
        "httpMethod": "POST",
        "path": "heir-orchestrator",
        "responseMode": "onReceived",
        "options": {},
    },
    "webhookId": str(uuid.uuid5(uuid.NAMESPACE_URL, "heir-orchestrator-webhook-v4")),
}

ORCH_SYSTEM_PROMPT = """You are the Heir Research Orchestrator. Your job is to determine the complete legal heir list for one person in an NC estate research session and write that result to the database.

## Your Goal (per invocation)

You receive ONE person to research. For that person, determine:
1. **vital_status** — are they living or deceased?
2. **estate_filed** — did they file a probate in NC courts?
3. **cascade_needed** — do we need to find their heirs (deceased + no filed estate)?
4. **cascade_relatives** — who are their heirs if cascade is needed?

One invocation = one person. New persons discovered (children from an obit, beneficiaries from probate) are QUEUED via Queue Persons (Orch) and picked up by the next invocation. Do NOT research discovered persons now.

## Reasoning Loop (not a fixed sequence — adapt based on what you learn)

**Start every new person with:**
1. Load Person (Orch) — check what's already saved. If research_phase="complete", skip all tool calls.
2. If matched_identity is empty → call SkipGenie Resolver Agent (AI tool). It handles the search + best-match selection + DB write internally and returns a slim identity JSON. NEVER call SkipGenie (Orch) directly for identity lookup — it dumps large raw results into context. NEVER call SkipGenie twice for same person.

**SkipGenie address strategy — more fields = better match:**
- Always pass city=property city (e.g. "Wake Forest") AND zip_code=property zip (e.g. "27587"). County alone is too broad.
- For the first person you research: call Load Property State first to get the property street address (e.g. "631 E Nelson Ave"). Pass that as street_address — SkipGenie will surface people who lived near that address.
- For subsequent persons (children, heirs): pass the property street_address as well — family members very often lived on the same street or nearby. This is the single most effective way to distinguish the right "Mary Justice" from other people with the same name.
- If a prior SkipGenie result returned a known address for a relative, pass that address for the relative's own search.
- Pass middle_name if known from obituary or deed records.

**Vital status:**
3. NC Voter (Orch) — Active = living (high confidence). Write voter record immediately. If Active → close: vital_status=living, cascade_needed=false, done.
4. If voter Removed or not found → check SSDI via Ancestry Search Save (Orch) with collection_id="2442".
5. If SSDI confirms death → deceased. If not → try obituary search next.

**Court research (for every deceased person — always):**
6. Court Researcher Tool (sub-agent) — pass person_name, county, session_id, property_id. It handles Court Search variants, ROA, and Document Pull internally. Returns {estate_filed, had_will, case_number, case_url, named_persons[], notes}.
   - If estate_filed=true with named_persons → cascade_needed=false, queue those named persons, write person, done.
   - If named_persons[x].has_issue=false → cascade_needed=false, cascade_relatives=[], done permanently.

**Obituary research (only if no probate found with named persons):**
7. Call Ancestry Selector Agent (AI tool) — pass first_name, last_name, death_year, death_location="[County], North Carolina", session_id, property_id. It handles full search + NC candidate selection + Ancestry Record detail internally. Returns {found, children[], obit_text, confidence}. Use this INSTEAD of calling Ancestry Search Save + Ancestry Record directly — avoids 100+ raw records flooding context.
8. Only fall back to Ancestry Search Save (Orch) directly if Ancestry Selector returns found=false AND you need a census/SSDI search (collection_id=2442 — NOT 61843).
9. Brave Search (Orch) — only if Ancestry returned nothing or wrong state results. Pattern: "[FULL NAME] obituary [county] NC [year]".
10. Fetch Obituary Page (Orch) — only after Brave Search found a promising non-Ancestry URL.

**Census household (when obit didn't name all children):**
11. Ancestry Search Save (Orch) with collection_id="2442" + first_name + last_name + birth_year + state="NC" — find a census record for this person or a known family member.
11b. Ancestry Household (Orch) — pass the source_url from step 11. Returns all household members with relationship_to_head. Children = 'Son' or 'Daughter'. More reliable than obituary parent searches.
NOTE: Do NOT pass father= or mother= into collection_id="61843" — the obituary index does not store parent names as structured fields and returns tens of thousands of noise results.

**Deeds (for property owners / high-value heirs):**
13. Wake Deeds (Orch) / Buncombe Deeds (Orch) / Mecklenburg Deeds (Orch) — use based on property county. Surfaces deed transfers to named heirs.

**Synthesis (after researching):**
14. Determine final cascade_relatives from (in priority): probate named_persons > obit children (from detail page) > parent-mode Ancestry > Census. NEVER use SkipGenie possible_relatives as heirs.
15. Queue Persons (Orch) — queue all newly discovered heirs. Include relationship_hint and maiden_name if known.
16. Write Person (Orch) — final write with vital_status, estate_filed, had_will, cascade_needed, cascade_relatives, research_phase="complete".

## Critical Rules

**SkipGenie:** Paid per-call. Check DB first (Load Person). Pass city=property city AND zip_code=property zip AND street_address=property address. The property address anchors the search geographically — family members almost always lived nearby (same street, same zip). Save immediately. possible_relatives are NOT heirs — identity cross-check only. Never call twice.

**Obituary > SkipGenie for heir discovery.** When obit names children, that list is closed. Do not supplement with SkipGenie relatives.

**Probate > Obituary for legal heir list.** If probate names beneficiaries, use those. cascade_needed=false.

**Write as you go.** Voter records → write immediately. Ancestry finds → auto-saved by the tool. Court findings → written by Court Researcher. Person record → write after SkipGenie (early), update after vital status, final write when complete.

**NC Chapter 29 intestate succession:**
- Deceased + no estate → children are primary heirs (per stirpes).
- Deceased + no children + no estate → surviving spouse gets half, then parents/siblings.
- Deceased + estate with named heirs → those are the heirs, cascade_needed=false.
- Apply this inline at synthesis time.

**Name completeness:** Never queue a single-token name. Resolve partial names via Ancestry parent-mode or Brave Search before queuing. Drop unresolvable partials and note in output.

**Termination conditions (close the branch):**
- Active voter → living, no cascade.
- Probate with named persons → cascade to those persons only.
- Probate with has_issue=false → no children, branch permanently closed.
- Obituary with explicit children list → that list is the closed heir set.
- All 4 Court Search variants returned nothing → estate_filed=false.
- All search strategies exhausted → write best known data, done.

## SkipGenie Name Hints

Collections:
- 61843 = U.S. Obituary Collection (primary for heir discovery)
- 2442 = SSDI / Social Security Death Index (vital status confirmation)
- 63277 = Ancestry Family Trees (soft signal, user-contributed)

## Output (return when done researching this person)

Return ONLY this JSON (no preamble):
{
  "person_name": "FIRST LAST",
  "vital_status": "living|deceased|unknown",
  "estate_filed": true/false/null,
  "had_will": true/false/null,
  "cascade_needed": true/false,
  "cascade_relatives": [{"name": "FIRST LAST", "relationship_hint": "child|spouse|sibling|beneficiary", "maiden_name": "...or null"}],
  "persons_queued": ["NAME1", "NAME2"],
  "notes": "Brief summary of key findings and sources used."
}"""

heir_research_orch = agent_node(
    "Heir Research Orchestrator", NID["Heir Research Orchestrator"],
    system_msg=ORCH_SYSTEM_PROMPT,
    text_expr=(
        "={{ `Research this person completely.\\n\\n"
        "Person Name: ${$json.body.person_name}\\n"
        "Session ID: ${$json.body.session_id}\\n"
        "Property ID: ${$json.body.property_id}\\n"
        "County: ${$json.body.county}\\n"
        "Relationship Hint: ${$json.body.relationship_hint || ''}\\n"
        "Queue ID: ${$json.body.queue_id || ''}\\n"
        "Maiden Name: ${$json.body.maiden_name || ''}` }}"
    ),
    max_iter=60,
)

orch_model = gpt_model("GPT-5-Mini (Orch)", NID["Orch Model"])

# ── Orchestrator research tools ──────────────────────────────────────────────

# SkipGenie — reuse v3 worker try1 structure (single call tool)
sg_orch = v3node("SkipGenie Try 1")
sg_orch["id"]   = NID["SkipGenie (Orch)"]
sg_orch["name"] = "SkipGenie (Orch)"
# Override to be a proper tool (not httpRequest) — use httpRequestTool
sg_orch["type"] = "n8n-nodes-base.httpRequestTool"
sg_orch["typeVersion"] = 4.2
sg_orch["parameters"] = {
    "toolDescription": (
        "Search SkipGenie for a person. PAID — check DB first (Load Person). "
        "Required: first_name, last_name, state='NC'. "
        "CRITICAL for good results: always pass city=property city (e.g. 'Wake Forest' not just 'Wake'), "
        "zip_code=property zip (e.g. '27587'), AND street_address=property street address (e.g. '631 E Nelson Ave'). "
        "The property address anchors the search — family members typically lived nearby (same street, same zip). "
        "Without street+zip, common names like 'Mary Justice' return wrong people or no results. "
        "Also pass middle_name if known. "
        "NEVER call twice for the same person. Save result immediately via Write Person (Orch). "
        "possible_relatives and possible_associates are identity cross-check signals ONLY — not heirs. "
        "Pick the result where: deceased=true matches expectation, address is closest to property, "
        "and known family names appear in possible_relatives or possible_associates."
    ),
    "method": "POST",
    "url": f"{BASE}/skipgenie",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": (
        '={{ { '
        '"first_name": $fromAI("first_name", "First name"), '
        '"last_name": $fromAI("last_name", "Last name"), '
        '"middle_name": $fromAI("middle_name", "Middle name if known, else empty string", "string", ""), '
        '"street_address": $fromAI("street_address", "Street address if known from SkipGenie or deed records, else empty string", "string", ""), '
        '"state": $fromAI("state", "State, default NC", "string", "NC"), '
        '"city": $fromAI("city", "City or county name — REQUIRED. Name+state alone returns nothing. Pass property county e.g. Wake or city e.g. Raleigh"), '
        '"zip_code": $fromAI("zip_code", "ZIP code if known, else empty string", "string", "") '
        '} }}'
    ),
}

nc_voter_orch = http_tool(
    "NC Voter (Orch)", NID["NC Voter (Orch)"],
    (
        "Look up NC voter registration. Pass last_name, first_name, and county. "
        "Active = living (high confidence). Removed = investigate further. Not found = unknown. "
        "ALWAYS write result via Write Voter Record (Orch) immediately, even if not found."
    ),
    f"{BASE}/voter/nc/lookup",
    '={{ { "last_name": $fromAI("last_name", "Last name"), "first_name": $fromAI("first_name", "First name"), "county": $fromAI("county", "County if known", "string", null) } }}',
)

ancestry_search_save_orch = http_tool(
    "Ancestry Search Save (Orch)", NID["Ancestry Search Save (Orch)"],
    (
        "Search Ancestry AND auto-save results to DB. "
        "REQUIRED: session_id, property_id. "
        "Three usage modes: "
        "(1) OBITUARY: first_name+last_name+death_year+death_location+collection_id='61843' — finds person's own obit. "
        "After picking best hit, call Ancestry Record (Orch) for the detail page — it has the full children/survivors list. "
        "(2) CENSUS: first_name+last_name+birth_year+state='NC'+collection_id='2442' — find a census record for this person. "
        "Pass the returned source_url to Ancestry Household (Orch) to get all household members (children listed as Son/Daughter). "
        "(3) SSDI: first_name+last_name+death_year+collection_id='2442' — confirm death date and last residence. "
        "WARNING: passing father= or mother= into collection_id='61843' does NOT reliably find children. "
        "The obituary index does not store parent names as structured fields — use Ancestry Household instead. "
        "Collections: 61843=obituaries, 2442=census/SSDI, 63277=family trees."
    ),
    f"{BASE}/ancestry/search-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"first_name": $fromAI("first_name", "First name. Empty for parent-mode.", "string", ""), '
        '"last_name": $fromAI("last_name", "Last name.", "string", ""), '
        '"birth_year": $fromAI("birth_year", "Estimated birth year", "string", ""), '
        '"death_year": $fromAI("death_year", "Estimated death year", "string", ""), '
        '"death_location": $fromAI("death_location", "Death location e.g. \'Wake, North Carolina\'", "string", ""), '
        '"mother": $fromAI("mother", "Parent-mode: full name as mother. Empty for direct.", "string", ""), '
        '"father": $fromAI("father", "Parent-mode: full name as father. Empty for direct.", "string", ""), '
        '"collection_id": $fromAI("collection_id", "e.g. 61843 (obits), 2442 (SSDI/census), 63277 (trees)", "string", ""), '
        '"state": $fromAI("state", "State e.g. NC", "string", "NC"), '
        '"name_x": $fromAI("name_x", "Exact-match flags, default 1_1", "string", "1_1") '
        '} }}'
    ),
)

ancestry_record_orch = http_tool(
    "Ancestry Record (Orch)", NID["Ancestry Record (Orch)"],
    (
        "Fetch a specific Ancestry record's full detail page AND save it. "
        "ALWAYS call after selecting best obit candidate from Ancestry Search Save. "
        "REQUIRED: session_id, property_id, record_id (source_url preferred — bare numeric ID 404s for Newspapers.com). "
        "Detail page has canonical full-name children list (e.g. 'Mary Justice' not 'Mary')."
    ),
    f"{BASE}/ancestry/record-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"record_id": $fromAI("record_id", "Ancestry record_id (source_url preferred) or numeric ID"), '
        '"state": $fromAI("state", "State e.g. NC", "string", "NC") '
        '} }}'
    ),
)

brave_search_orch = v3node("Brave Search")
brave_search_orch["id"]   = NID["Brave Search (Orch)"]
brave_search_orch["name"] = "Brave Search (Orch)"

fetch_obit_orch = v3node("Fetch Obituary Page")
fetch_obit_orch["id"]   = NID["Fetch Obituary Page (Orch)"]
fetch_obit_orch["name"] = "Fetch Obituary Page (Orch)"

wake_deeds_orch = v3node("Wake Deeds")
wake_deeds_orch["id"]   = NID["Wake Deeds (Orch)"]
wake_deeds_orch["name"] = "Wake Deeds (Orch)"

buncombe_deeds_orch = v3node("Buncombe Deeds")
buncombe_deeds_orch["id"]   = NID["Buncombe Deeds (Orch)"]
buncombe_deeds_orch["name"] = "Buncombe Deeds (Orch)"

meck_deeds_orch = v3node("Mecklenburg Deeds")
meck_deeds_orch["id"]   = NID["Mecklenburg Deeds (Orch)"]
meck_deeds_orch["name"] = "Mecklenburg Deeds (Orch)"

# ── Ancestry census household tool ───────────────────────────────────────────

anc_household_orch = http_tool(
    "Ancestry Household (Orch)", NID["Ancestry Household (Orch)"],
    (
        "Fetch all members of the same census household given any Ancestry census record URL. "
        "Use when a person's children are not found in their obituary or probate documents. "
        "How to use: first call Ancestry Search Save (Orch) with collection_id='2442' to find a census record "
        "for this person or a confirmed family member — then pass the returned source_url here. "
        "Returns all household members with relationship_to_head (Son, Daughter, Wife, Head, etc.). "
        "Children appear as 'Son' or 'Daughter'. This is the most reliable way to find children "
        "not mentioned in an obituary — census records capture everyone living in the household."
    ),
    f"{BASE}/ancestry/household",
    '={{ { "record_url": $fromAI("record_url", "Ancestry census record URL from a prior search result (source_url field)") } }}',
)

# ── Orchestrator DB read tools ────────────────────────────────────────────────

load_prop_state_orch = http_tool(
    "Load Property State (Orch)", NID["Load Property State (Orch)"],
    (
        "Load full property record including street address, city, zip, and county. "
        "Call ONCE at the start of a session before your first SkipGenie call. "
        "Use property.address.street, property.address.city, property.address.zip as SkipGenie inputs. "
        "Family members of the deceased almost always lived nearby — the property address is the best "
        "geographic anchor for finding ANY person in this family, not just the root decedent. "
        "Pass property_id to retrieve."
    ),
    f"{BASE}/investigate/property-state",
    '={{ { "property_id": $fromAI("property_id", "Property ID") } }}',
)

load_person_orch = http_tool(
    "Load Person (Orch)", NID["Load Person (Orch)"],
    (
        "Load person's existing research record from DB. "
        "Call FIRST before any external API to avoid duplicate paid calls. "
        "If research_phase='complete' → skip all tool calls, person is done. "
        "If matched_identity is populated → skip SkipGenie. "
        "Pass session_id and name."
    ),
    f"{BASE}/heir/load-person",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "name": $fromAI("name", "Person full name") } }}',
)
# Override as GET-style: the endpoint is GET /heir/person?session_id=&name=
# Use POST to keep consistent with http_tool helper — backend accepts both
load_person_orch["parameters"]["method"] = "GET"
load_person_orch["parameters"].pop("sendBody", None)
load_person_orch["parameters"].pop("specifyBody", None)
load_person_orch["parameters"].pop("jsonBody", None)
load_person_orch["type"] = "n8n-nodes-base.httpRequestTool"
load_person_orch["parameters"]["sendQuery"] = True
load_person_orch["parameters"]["queryParameters"] = {
    "parameters": [
        {"name": "session_id", "value": '={{ $fromAI("session_id", "Session ID") }}'},
        {"name": "name",       "value": '={{ $fromAI("name", "Person full name") }}'},
    ]
}

load_anc_orch = http_tool(
    "Load Ancestry Records (Orch)", NID["Load Ancestry Records (Orch)"],
    "Load Ancestry records saved for this session and person. Pass session_id and optionally search_name to filter. Check before running Ancestry Search Save.",
    f"{BASE}/heir/ancestry-records",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "search_name": $fromAI("search_name", "Person name to filter", "string", null) } }}',
)

load_court_orch = http_tool(
    "Load Court Findings (Orch)", NID["Load Court Findings (Orch)"],
    "Load court/probate findings for this session and person. Check before running Court Search. Pass session_id.",
    f"{BASE}/heir/court-findings",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "person_name": $fromAI("person_name", "Person name to filter", "string", null) } }}',
)

load_voter_orch = http_tool(
    "Load Voter Records (Orch)", NID["Load Voter Records (Orch)"],
    "Load voter records saved for this session. Check before running NC Voter Lookup. Pass session_id.",
    f"{BASE}/heir/voter-records",
    '={{ { "session_id": $fromAI("session_id", "Session ID") } }}',
)

# ── Orchestrator DB write tools ───────────────────────────────────────────────

write_person_orch = http_tool(
    "Write Person (Orch)", NID["Write Person (Orch)"],
    (
        "Create or update a person record in DB (upsert). Safe to call multiple times. "
        "Call immediately after SkipGenie with matched_identity. "
        "Call after vital status determined. "
        "Call at end with cascade_needed, cascade_relatives, research_phase='complete'. "
        "REQUIRED: session_id, property_id, input_name, vital_status."
    ),
    f"{BASE}/heir/upsert-person",
    """={{ {
  "session_id":        $fromAI("session_id", "Session ID"),
  "property_id":       $fromAI("property_id", "Property ID"),
  "input_name":        $fromAI("input_name", "Person name as queued"),
  "vital_status":      $fromAI("vital_status", "living|deceased|unknown"),
  "research_phase":    $fromAI("research_phase", "skipgenie|vital_status|complete", "string", ""),
  "cascade_needed":    $fromAI("cascade_needed", "Whether cascade research needed", "boolean", false),
  "matched_identity":  $fromAI("matched_identity", "SkipGenie matched identity", "json", {}),
  "deceased_facts":    $fromAI("deceased_facts", "NC Ch.29 required facts", "json", {}),
  "obituary_url":      $fromAI("obituary_url", "Obituary URL", "string", ""),
  "obituary_text":     $fromAI("obituary_text", "Full obituary text", "string", ""),
  "estate_filed":      $fromAI("estate_filed", "Whether estate was filed", "boolean", null),
  "had_will":          $fromAI("had_will", "Whether had a will", "boolean", null),
  "cascade_relatives": $fromAI("cascade_relatives", "Heir list", "json", []),
  "maiden_name":       $fromAI("maiden_name", "Maiden name if applicable", "string", ""),
  "notes":             $fromAI("notes", "Research notes", "string", ""),
  "relationship_hint": $fromAI("relationship_hint", "Relationship to root decedent", "string", ""),
  "queue_id":          $fromAI("queue_id", "Queue item ID", "number", null)
} }}""",
)

write_voter_orch = http_tool(
    "Write Voter Record (Orch)", NID["Write Voter Record (Orch)"],
    "Save voter lookup result to DB. Call after EVERY NC Voter Lookup, including not-found. Required: session_id, property_id, search_name. Saves full_name (may be married name), county, status.",
    f"{BASE}/heir/write-voter",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "search_name": $fromAI("search_name", "Name searched"), "search_context": $fromAI("search_context", "Context e.g. orchestrator", "string", "orchestrator"), "ncid": $fromAI("ncid", "NCID if found", "string", null), "full_name": $fromAI("full_name", "Full legal name if found — may differ (married name)", "string", null), "county": $fromAI("county", "County if found", "string", null), "status": $fromAI("status", "Status A/I/R/D if found", "string", null), "notes": $fromAI("notes", "Notes", "string", "") } }}',
)

queue_persons_orch = http_tool(
    "Queue Persons (Orch)", NID["Queue Persons (Orch)"],
    (
        "Add new persons to the research queue. "
        "Use when new heirs/children are discovered during research. "
        "Required: session_id, property_id, persons=[{name, relationship_hint, maiden_name}]. "
        "Server deduplicates. Do NOT queue: the current person, single-token names, 'Estate of', 'Heirs of'."
    ),
    f"{BASE}/heir/queue-persons",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "depth": $fromAI("depth", "Depth level for cascade", "number", 1), "persons": $fromAI("persons", "Array of {name, relationship_hint, maiden_name} to queue", "json", []) } }}',
)

# ── Court Researcher Tool (sub-agent call) ────────────────────────────────────

court_researcher_tool = http_tool(
    "Court Researcher Tool", NID["Court Researcher Tool"],
    (
        "Call the Court Researcher sub-agent to handle ALL probate research for one person. "
        "Call for EVERY deceased person without exception — even if an obit was found. "
        "Probate supersedes obituary for the legal heir list. "
        "Pass person_name, county, session_id, property_id. "
        "Returns: {estate_filed, had_will, case_number, case_url, named_persons[], notes}. "
        "If estate_filed=true with named_persons → cascade_needed=false, use those as heirs."
    ),
    f"{LOCALHOST_N8N}/webhook/heir-court-researcher",
    '={{ { "person_name": $fromAI("person_name", "Full name of person to research"), "county": $fromAI("county", "NC county for court search"), "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID") } }}',
)

# ── Ancestry Selector Agent (AI tool connected to Orchestrator) ───────────────

ANCESTRY_SELECTOR_PROMPT = """You are the Ancestry Selector. Search Ancestry for ONE person's obituary, select the best NC match, fetch the full record detail, and return a structured result.

## Input (from parent agent)
first_name, last_name, death_year, death_location (e.g. "Wake, North Carolina"), session_id, property_id

## Steps

1. Call Ancestry Search Save (AS) with first_name, last_name, death_year, death_location, collection_id="61843", session_id, property_id. Results auto-save to DB.

2. Review ALL returned records_summary entries:
   - STEP A — Hard reject: any record whose death_location contains a US state other than "North Carolina" or "NC" is disqualifying.
   - STEP B — Among NC records, prefer: (1) dod year matches death_year ±2; (2) children[] overlap with known relatives; (3) dob plausible for expected age. Reject records with dod before 1960.
   - STEP C — If no NC record passes, return found=false immediately.

3. If best candidate found: call Ancestry Record (AS) using source_url (preferred over bare record_id). Gets canonical full-name children list. ALWAYS do this step.

4. Return ONLY this JSON:
{
  "found": true/false,
  "record_id": "...",
  "source_url": "...",
  "person_name": "...",
  "dob": "...",
  "dod": "...",
  "death_location": "...",
  "children": ["FIRST LAST"],
  "obit_text": "...full text if available...",
  "confidence": "high|medium|low",
  "notes": "Brief selection rationale."
}"""

ancestry_selector_agent = agent_tool_node(
    "Ancestry Selector Agent", NID["Ancestry Selector Agent"],
    tool_description=(
        "Search Ancestry for a person's obituary and return the single best NC match. "
        "Handles full search + NC candidate selection + Ancestry Record detail internally. "
        "Returns {found, person_name, dob, dod, death_location, children[], obit_text, confidence}. "
        "Use INSTEAD of calling Ancestry Search Save + Ancestry Record directly — avoids 100+ raw records flooding context. "
        "Pass: first_name, last_name, death_year, death_location (e.g. 'Wake, North Carolina'), session_id, property_id."
    ),
    system_msg=ANCESTRY_SELECTOR_PROMPT,
    text_expr=(
        '={{ `Select best Ancestry obituary match.\n\n'
        'First Name: ${$fromAI("first_name", "First name")}\n'
        'Last Name: ${$fromAI("last_name", "Last name")}\n'
        'Death Year: ${$fromAI("death_year", "Estimated death year", "string", "")}\n'
        'Death Location: ${$fromAI("death_location", "e.g. Wake, North Carolina", "string", "")}\n'
        'Session ID: ${$fromAI("session_id", "Session ID")}\n'
        'Property ID: ${$fromAI("property_id", "Property ID")}` }}'
    ),
    max_iter=10,
)
ancestry_selector_model = gpt_model("GPT-5-Mini (Ancestry Selector)", NID["Ancestry Selector Model"])

ancestry_search_save_as = http_tool(
    "Ancestry Search Save (AS)", NID["Ancestry Search Save (AS)"],
    (
        "Search Ancestry AND auto-save results to DB. "
        "Pass session_id, property_id, first_name, last_name, death_year, death_location, collection_id."
    ),
    f"{BASE}/ancestry/search-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"first_name": $fromAI("first_name", "First name", "string", ""), '
        '"last_name": $fromAI("last_name", "Last name", "string", ""), '
        '"birth_year": $fromAI("birth_year", "Birth year", "string", ""), '
        '"death_year": $fromAI("death_year", "Death year", "string", ""), '
        '"death_location": $fromAI("death_location", "Death location", "string", ""), '
        '"collection_id": $fromAI("collection_id", "Collection ID", "string", "61843"), '
        '"state": $fromAI("state", "State", "string", "NC") '
        '} }}'
    ),
)

ancestry_record_as = http_tool(
    "Ancestry Record (AS)", NID["Ancestry Record (AS)"],
    (
        "Fetch a specific Ancestry record's full detail page AND save it. "
        "Use source_url (preferred) or record_id. Returns canonical full-name children list."
    ),
    f"{BASE}/ancestry/record-and-save",
    (
        '={{ { '
        '"session_id": $fromAI("session_id", "Session ID"), '
        '"property_id": $fromAI("property_id", "Property ID"), '
        '"record_id": $fromAI("record_id", "source_url preferred, or numeric record_id"), '
        '"state": $fromAI("state", "State", "string", "NC") '
        '} }}'
    ),
)

# ── SkipGenie Resolver Agent (AI tool connected to Orchestrator) ───────────────

SKIPGENIE_RESOLVER_PROMPT = """You are the SkipGenie Identity Resolver. Find and confirm the identity of ONE person using SkipGenie and write the result to the database.

## Input (from parent agent)
first_name, last_name, street_address, city, zip_code, state, session_id, property_id, person_name (as queued)

## Steps

1. Call SkipGenie (SR) with ALL provided address fields: first_name, last_name, street_address, city, zip_code, state. The property address is the best geographic anchor — family members typically lived nearby.

2. Select the best match:
   - Prefer: deceased=true if expected deceased
   - Prefer: address closest to the property address
   - Prefer: possible_relatives contains known family names
   - If no convincing match: matched=false

3. Call Write Person (SR) IMMEDIATELY — even if matched=false (write empty identity to mark as checked). Required: session_id, property_id, input_name=person_name, vital_status="unknown", research_phase="skipgenie", matched_identity.

4. Return ONLY this JSON:
{
  "matched": true/false,
  "subject_name": "...",
  "age": "...",
  "dob": "...",
  "dod": "...",
  "deceased": true/false,
  "last_address": "...",
  "city": "...",
  "state": "...",
  "possible_relatives": [{"name": "...", "age": "...", "pid": "..."}],
  "pid": "...",
  "notes": "Brief match rationale."
}"""

skipgenie_resolver_agent = agent_tool_node(
    "SkipGenie Resolver Agent", NID["SkipGenie Resolver Agent"],
    tool_description=(
        "Resolve a person's identity via SkipGenie and write the result to DB. "
        "Handles search + best-match selection + DB write internally. "
        "Returns slim identity {matched, subject_name, dob, dod, deceased, last_address, possible_relatives}. "
        "Use INSTEAD of calling SkipGenie (Orch) directly — avoids large raw results in context. "
        "PAID — call only once per person. "
        "Pass: first_name, last_name, street_address, city, zip_code, state, session_id, property_id, person_name."
    ),
    system_msg=SKIPGENIE_RESOLVER_PROMPT,
    text_expr=(
        '={{ `Resolve identity for person.\n\n'
        'First Name: ${$fromAI("first_name", "First name")}\n'
        'Last Name: ${$fromAI("last_name", "Last name")}\n'
        'Street Address: ${$fromAI("street_address", "Property street address", "string", "")}\n'
        'City: ${$fromAI("city", "City", "string", "")}\n'
        'Zip: ${$fromAI("zip_code", "ZIP code", "string", "")}\n'
        'State: ${$fromAI("state", "State", "string", "NC")}\n'
        'Session ID: ${$fromAI("session_id", "Session ID")}\n'
        'Property ID: ${$fromAI("property_id", "Property ID")}\n'
        'Person Name: ${$fromAI("person_name", "Full name as queued")}` }}'
    ),
    max_iter=8,
)
skipgenie_resolver_model = gpt_model("GPT-5-Mini (SkipGenie Resolver)", NID["SkipGenie Resolver Model"])

sg_sr = http_tool(
    "SkipGenie (SR)", NID["SkipGenie (SR)"],
    (
        "Search SkipGenie for a person. PAID — only call once. "
        "Pass first_name, last_name, street_address, city, zip_code, state."
    ),
    f"{BASE}/skipgenie",
    (
        '={{ { '
        '"first_name": $fromAI("first_name", "First name"), '
        '"last_name": $fromAI("last_name", "Last name"), '
        '"middle_name": $fromAI("middle_name", "Middle name if known", "string", ""), '
        '"street_address": $fromAI("street_address", "Street address", "string", ""), '
        '"state": $fromAI("state", "State", "string", "NC"), '
        '"city": $fromAI("city", "City", "string", ""), '
        '"zip_code": $fromAI("zip_code", "ZIP code", "string", "") '
        '} }}'
    ),
)

write_person_sr = http_tool(
    "Write Person (SR)", NID["Write Person (SR)"],
    (
        "Create or update a person record in DB. Call immediately after SkipGenie with matched_identity. "
        "Required: session_id, property_id, input_name, vital_status."
    ),
    f"{BASE}/heir/upsert-person",
    """={{ {
  "session_id":        $fromAI("session_id", "Session ID"),
  "property_id":       $fromAI("property_id", "Property ID"),
  "input_name":        $fromAI("input_name", "Person name as queued"),
  "vital_status":      $fromAI("vital_status", "living|deceased|unknown"),
  "research_phase":    $fromAI("research_phase", "skipgenie|vital_status|complete", "string", "skipgenie"),
  "matched_identity":  $fromAI("matched_identity", "SkipGenie matched identity", "json", {}),
  "notes":             $fromAI("notes", "Notes", "string", "")
} }}""",
)

# ── Orchestrator queue management ─────────────────────────────────────────────

mark_person_done_orch = http_request(
    "Mark Person Done (Orch)", NID["Mark Person Done (Orch)"],
    f"{BASE}/heir/complete-person",
    "={{ { \"queue_id\": $('Orchestrator Webhook').first().json.body.queue_id } }}",
)

check_queue_status_orch = http_request(
    "Check Queue Status (Orch)", NID["Check Queue Status (Orch)"],
    f"{BASE}/heir/next-person",
    "={{ { \"session_id\": $('Orchestrator Webhook').first().json.body.session_id } }}",
)

# If item exists (queue not empty) → Self Trigger; else → Trigger Family Assembly
if_queue_empty_orch = if_node(
    "If Queue Empty (Orch)", NID["If Queue Empty (Orch)"],
    "={{ $json.item?.person_name }}",
    "notExists", "",
)

# Self Trigger — fire Orchestrator Webhook again with next person
self_trigger_orch = http_request(
    "Self Trigger Orchestrator", NID["Self Trigger Orchestrator"],
    f"{LOCALHOST_N8N}/webhook/heir-orchestrator",
    """={{ {
  "session_id":        $('Orchestrator Webhook').first().json.body.session_id,
  "property_id":       $('Orchestrator Webhook').first().json.body.property_id,
  "county":            $('Orchestrator Webhook').first().json.body.county || '',
  "person_name":       $('Check Queue Status (Orch)').first().json.item.person_name,
  "relationship_hint": $('Check Queue Status (Orch)').first().json.item.relationship_hint || '',
  "maiden_name":       $('Check Queue Status (Orch)').first().json.item.maiden_name || '',
  "queue_id":          $('Check Queue Status (Orch)').first().json.item.queue_id
} }}""",
    timeout=5000,
)

# Trigger Family Assembly when queue empty
trigger_family_assembly = http_request(
    "Trigger Family Assembly", NID["Trigger Family Assembly"],
    f"{LOCALHOST_N8N}/webhook/heir-family-assembly",
    """={{ {
  "session_id":  $('Orchestrator Webhook').first().json.body.session_id,
  "property_id": $('Orchestrator Webhook').first().json.body.property_id
} }}""",
    timeout=5000,
)


# ─── Workflow 3: Court Researcher Sub-Agent ───────────────────────────────────

court_researcher_webhook = {
    "id": NID["Court Researcher Webhook"],
    "name": "Court Researcher Webhook",
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 2.1,
    "position": [0, 0],
    "parameters": {
        "httpMethod": "POST",
        "path": "heir-court-researcher",
        "responseMode": "responseNode",
        "options": {},
    },
    "webhookId": str(uuid.uuid5(uuid.NAMESPACE_URL, "heir-court-researcher-webhook-v4")),
}

CR_SYSTEM_PROMPT = """You are the Court Researcher. Your job is to research NC probate court records for ONE person and return a structured result.

## Input
- person_name, county, session_id, property_id (from your input JSON)

## Steps (always all 4, in order)

**Step 1 — Court Search (name variants, never skip)**
Search NC Courts Portal. Try these name variants in order until you find an estate case:
  1. "LAST, FIRST" — no middle names, no suffixes. MOST IMPORTANT — the portal indexes by first+last only.
     Example: "HAYES, ALYCE" not "HAYES, ALYCE JOYE F"
  2. "LAST, FIRST MIDDLE" — full name as provided (if it has a middle name)
  3. "LAST" only — noisy but catches edge cases
  4. "FIRST LAST" — no comma, no middle

Case types that indicate a filed estate (DO NOT skip any):
- "E"  = Decedents' Estate
- "SE" = Small Estate (most common for recent deaths)
- "SP" = Special Proceedings
- "PR" = Probate (any sub-type)

If you find an estate case → IMMEDIATELY call Write Court Findings (CR) with case_number and case_url BEFORE proceeding to ROA or document pull. Even if document pull fails, the case reference is recorded.

If all 4 variants return zero estate cases → estate_filed=false, record this result, proceed to Return Court Result.

**Step 2 — Register of Actions (if estate case found)**
Call Register of Actions (CR) with the case_url. Key events to note:
- "Letters Testamentary" → had_will=true
- "Letters of Administration" → had_will=false (intestate)
- "Deed of Distribution" → real property transferred — grantees may be named heirs

If roa_unavailable=true (WAF block): skip, use case data from Court Search.

**Step 3 — Court Document Pull (if estate case found)**
Call Court Document Pull (CR) with case_url. Extract:
- named_persons[] — every person named as heir, executor, beneficiary, or relative
  Format: [{"name": "FIRST LAST", "role": "heir|executor|beneficiary|relative", "has_issue": true/false/null}]
- has_issue=false in named_persons is the HIGHEST VALUE signal in the system — permanently closes that branch (confirmed no children).
- decedent_name — full name from the document (confirms you have the right case)
- family_tree — structured per-person has_issue array

If documents=[] or pull fails: note "document pull failed" and continue to step 4.

**Step 4 — Write Court Findings (CR) (update with extracted data)**
Update the court findings record with named_persons and family_tree. Required: session_id, property_id, person_name.

## Output (return exactly this JSON, no preamble)

{
  "estate_filed": true/false,
  "had_will": true/false/null,
  "case_number": "...",
  "case_url": "...",
  "named_persons": [{"name": "FIRST LAST", "role": "beneficiary|heir|executor", "has_issue": true/false/null}],
  "notes": "Brief summary: case type, date filed, key document findings."
}"""

court_researcher_agent = agent_node(
    "Court Researcher Agent", NID["Court Researcher Agent"],
    system_msg=CR_SYSTEM_PROMPT,
    text_expr=(
        "={{ `Research probate court records for:\\n\\n"
        "Person Name: ${$json.body.person_name}\\n"
        "County: ${$json.body.county}\\n"
        "Session ID: ${$json.body.session_id}\\n"
        "Property ID: ${$json.body.property_id}` }}"
    ),
    max_iter=15,
)

court_researcher_model = gpt_model("GPT-5-Mini (Court Researcher)", NID["Court Researcher Model"])

# Court Researcher tools — reuse v3 TA tools with new IDs/names
court_search_cr = v3node("Court Search")
court_search_cr["id"]   = NID["Court Search (CR)"]
court_search_cr["name"] = "Court Search (CR)"

reg_actions_cr = v3node("Register of Actions")
reg_actions_cr["id"]   = NID["Register of Actions (CR)"]
reg_actions_cr["name"] = "Register of Actions (CR)"

court_doc_cr = v3node("Court Document Pull")
court_doc_cr["id"]   = NID["Court Document Pull (CR)"]
court_doc_cr["name"] = "Court Document Pull (CR)"

write_court_cr = v3node("Write Court Findings")
write_court_cr["id"]   = NID["Write Court Findings (CR)"]
write_court_cr["name"] = "Write Court Findings (CR)"

# Return Court Result — respond to webhook with structured output
return_court_result = {
    "id": NID["Return Court Result"],
    "name": "Return Court Result",
    "type": "n8n-nodes-base.respondToWebhook",
    "typeVersion": 1.1,
    "position": [0, 0],
    "parameters": {
        "respondWith": "lastNode",
        "options": {},
    },
}


# ─── Workflow 4: Family Assembly (simplified) ─────────────────────────────────

fa_webhook = v3node("FA Webhook")
fa_webhook["id"] = ID["FA Webhook"]
fa_webhook["parameters"]["path"] = "heir-family-assembly"
fa_webhook["parameters"]["responseMode"] = "onReceived"

FA_SYSTEM_PROMPT = """You are the Family Assembler. Your job is to synthesize all research results and write the final family tree.

## Steps

1. **Load Family Dataset (FA)** — load all person records for this session (vital_status, cascade_needed, cascade_relatives, estate_filed, obituary data, court data for every person).

2. **Apply NC Chapter 29 intestate succession** across all persons:
   - Deceased + estate with named persons → those persons are the heirs (legal heirs)
   - Deceased + no estate + cascade_relatives → children are primary heirs per stirpes
   - Deceased + no children + no estate → surviving spouse gets 1/2, remainder to parents or siblings
   - Living persons → they receive their own share directly
   - Unknown vital status → include in heir list with uncertainty noted
   - Persons with has_issue=false → confirmed no children, branch closed

3. **Compute share fractions** for each heir based on the above rules. For per-stirpes: if a deceased heir has N living children, each child takes (parent's share / N).

4. **Write Family Tree (FA)** — write the complete family tree. Required fields: session_id, property_id, root_decedent_name (full name of root decedent), heir_tree (array). Do NOT use "family_tree" — the field is named "heir_tree".

## Output from Write Family Tree (FA)

The tree should include all persons in scope:
- Resolved heirs with share fractions
- Closed branches (with reason: has_will, has_issue_false, living, etc.)
- Unknowns with notes
- Chain-of-title annotations where relevant

Return a brief summary JSON after writing:
{
  "session_id": <int>,
  "property_id": <int>,
  "total_heirs": N,
  "total_branches": N,
  "open_unknowns": N,
  "notes": "..."
}"""

family_assembler = agent_node(
    "Family Assembler", NID["Family Assembler"],
    system_msg=FA_SYSTEM_PROMPT,
    text_expr=(
        "={{ `Synthesize family tree for session.\\n\\n"
        "Session ID: ${$json.body.session_id}\\n"
        "Property ID: ${$json.body.property_id}` }}"
    ),
    max_iter=20,
)

fa_model_v4 = gpt_model("GPT-5-Mini (FA v4)", NID["FA Model v4"])

load_family_dataset_fa = http_tool(
    "Load Family Dataset (FA)", NID["Load Family Dataset (FA)"],
    "Load all person records for this session — vital_status, cascade_needed, cascade_relatives, estate_filed, obituary data for every person researched. Required: session_id.",
    f"{BASE}/heir/persons",
    '={{ { "session_id": $fromAI("session_id", "Session ID") } }}',
)

write_family_tree_fa = http_tool(
    "Write Family Tree (FA)", NID["Write Family Tree (FA)"],
    "Write the final resolved family tree to DB. Call once at the end after applying NC Ch. 29 to all branches. Required: session_id, property_id, root_decedent_name, heir_tree (array of heir nodes with share_fraction and basis).",
    f"{BASE}/heir/write",
    '={{ { "session_id": $fromAI("session_id", "Session ID"), "property_id": $fromAI("property_id", "Property ID"), "root_decedent_name": $fromAI("root_decedent_name", "Full name of the root decedent (e.g. Lydia L Hayes)"), "heir_tree": $fromAI("heir_tree", "Complete heir tree array", "json", []), "notes": $fromAI("notes", "Summary notes", "string", "") } }}',
)


# ─── Build nodes list ─────────────────────────────────────────────────────────

all_nodes = [
    # ── Workflow 1: Root Research (unchanged from v3) ──────────────────────────
    webhook, create_session, root_research_agent, root_research_model,
    sg_root_tool, load_prop_tool, anc_root_tool,
    brave_root, fetch_obit_root, nc_voter_root, write_voter_root,
    court_search_root, reg_actions_root, court_doc_root, write_court_root, write_anc_root,
    ancestry_search_save_root, ancestry_record_root, anc_household_root,
    write_root_person,
    queue_initial_relatives, trigger_orch_init,

    # ── Workflow 2: Orchestrator ───────────────────────────────────────────────
    orchestrator_webhook, heir_research_orch, orch_model,
    # Research tools
    sg_orch, nc_voter_orch, ancestry_search_save_orch, ancestry_record_orch,
    brave_search_orch, fetch_obit_orch,
    wake_deeds_orch, buncombe_deeds_orch, meck_deeds_orch,
    # Census household tool
    anc_household_orch,
    # DB read tools
    load_prop_state_orch, load_person_orch, load_anc_orch, load_court_orch, load_voter_orch,
    # DB write tools
    write_person_orch, write_voter_orch, queue_persons_orch,
    # Sub-agent tools
    court_researcher_tool,
    # Ancestry Selector Agent (AI tool)
    ancestry_selector_agent, ancestry_selector_model,
    ancestry_search_save_as, ancestry_record_as,
    # SkipGenie Resolver Agent (AI tool)
    skipgenie_resolver_agent, skipgenie_resolver_model,
    sg_sr, write_person_sr,
    # Queue management
    mark_person_done_orch, check_queue_status_orch,
    if_queue_empty_orch, self_trigger_orch, trigger_family_assembly,

    # ── Workflow 3: Court Researcher ───────────────────────────────────────────
    court_researcher_webhook, court_researcher_agent, court_researcher_model,
    court_search_cr, reg_actions_cr, court_doc_cr, write_court_cr,
    return_court_result,

    # ── Workflow 4: Family Assembly (simplified) ───────────────────────────────
    fa_webhook, family_assembler, fa_model_v4,
    load_family_dataset_fa, write_family_tree_fa,
]


# ─── Connections ──────────────────────────────────────────────────────────────

def main(dest: str, idx: int = 0) -> dict:
    return {"node": dest, "type": "main", "index": idx}

def ai_lang(dest: str) -> dict:
    return {"node": dest, "type": "ai_languageModel", "index": 0}

def ai_tool(dest: str) -> dict:
    return {"node": dest, "type": "ai_tool", "index": 0}

connections = {
    # ── Workflow 1: Root Research ─────────────────────────────────────────────
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
    "Ancestry Search Save Root":   {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Ancestry Record Root":        {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    "Ancestry Household Root":     {"ai_tool":          [[ai_tool("Root Owner Research")]]},
    # Root Research → Write Root Person → Queue Initial Relatives → Trigger Orchestrator Init → Respond
    "Root Owner Research":        {"main": [[main("Write Root Person")]]},
    "Write Root Person":          {"main": [[main("Queue Initial Relatives")]]},
    "Queue Initial Relatives":    {"main": [[main("Trigger Orchestrator Init")]]},
    # Trigger Orchestrator Init is fire-and-forget — no downstream node needed

    # ── Workflow 2: Orchestrator ──────────────────────────────────────────────
    "Orchestrator Webhook": {"main": [[main("Heir Research Orchestrator")]]},
    # Model
    "GPT-5-Mini (Orch)": {"ai_languageModel": [[ai_lang("Heir Research Orchestrator")]]},
    # Research tools → agent
    "SkipGenie (Orch)":              {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "NC Voter (Orch)":               {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Ancestry Search Save (Orch)":   {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Ancestry Record (Orch)":        {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Brave Search (Orch)":           {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Fetch Obituary Page (Orch)":    {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Wake Deeds (Orch)":             {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Buncombe Deeds (Orch)":         {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Mecklenburg Deeds (Orch)":      {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Ancestry Household (Orch)":     {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    # DB read tools → agent
    "Load Property State (Orch)":    {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Load Person (Orch)":            {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Load Ancestry Records (Orch)":  {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Load Court Findings (Orch)":    {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Load Voter Records (Orch)":     {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    # DB write tools → agent
    "Write Person (Orch)":           {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Write Voter Record (Orch)":     {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Queue Persons (Orch)":          {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    # Sub-agent tools → orchestrator
    "Court Researcher Tool":         {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "Ancestry Selector Agent":       {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    "SkipGenie Resolver Agent":      {"ai_tool": [[ai_tool("Heir Research Orchestrator")]]},
    # Ancestry Selector internal
    "GPT-5-Mini (Ancestry Selector)": {"ai_languageModel": [[ai_lang("Ancestry Selector Agent")]]},
    "Ancestry Search Save (AS)":     {"ai_tool": [[ai_tool("Ancestry Selector Agent")]]},
    "Ancestry Record (AS)":          {"ai_tool": [[ai_tool("Ancestry Selector Agent")]]},
    # SkipGenie Resolver internal
    "GPT-5-Mini (SkipGenie Resolver)": {"ai_languageModel": [[ai_lang("SkipGenie Resolver Agent")]]},
    "SkipGenie (SR)":                {"ai_tool": [[ai_tool("SkipGenie Resolver Agent")]]},
    "Write Person (SR)":             {"ai_tool": [[ai_tool("SkipGenie Resolver Agent")]]},
    # Orchestrator → Mark Done → Check Queue → If Empty
    "Heir Research Orchestrator":   {"main": [[main("Mark Person Done (Orch)")]]},
    "Mark Person Done (Orch)":      {"main": [[main("Check Queue Status (Orch)")]]},
    "Check Queue Status (Orch)":    {"main": [[main("If Queue Empty (Orch)")]]},
    "If Queue Empty (Orch)": {
        "main": [
            [main("Trigger Family Assembly")],  # 0 = queue empty → trigger FA
            [main("Self Trigger Orchestrator")], # 1 = queue not empty → loop back
        ]
    },

    # ── Workflow 3: Court Researcher ──────────────────────────────────────────
    "Court Researcher Webhook": {"main": [[main("Court Researcher Agent")]]},
    "GPT-5-Mini (Court Researcher)": {"ai_languageModel": [[ai_lang("Court Researcher Agent")]]},
    "Court Search (CR)":         {"ai_tool": [[ai_tool("Court Researcher Agent")]]},
    "Register of Actions (CR)":  {"ai_tool": [[ai_tool("Court Researcher Agent")]]},
    "Court Document Pull (CR)":  {"ai_tool": [[ai_tool("Court Researcher Agent")]]},
    "Write Court Findings (CR)": {"ai_tool": [[ai_tool("Court Researcher Agent")]]},
    "Court Researcher Agent": {"main": [[main("Return Court Result")]]},

    # ── Workflow 4: Family Assembly ───────────────────────────────────────────
    "FA Webhook": {"main": [[main("Family Assembler")]]},
    "GPT-5-Mini (FA v4)":       {"ai_languageModel": [[ai_lang("Family Assembler")]]},
    "Load Family Dataset (FA)": {"ai_tool":          [[ai_tool("Family Assembler")]]},
    "Write Family Tree (FA)":   {"ai_tool":          [[ai_tool("Family Assembler")]]},
}


# ─── Node positions ───────────────────────────────────────────────────────────
# Layout:
#   Workflow 1 main flow  → y=0,    x increases left-to-right
#   Workflow 1 tools      → y=200+  below their agent
#   Workflow 2 main flow  → y=1600, x increases left-to-right
#   Workflow 2 tools      → y=1800+ below their agent
#   Workflow 3 main flow  → y=3200, x increases left-to-right
#   Workflow 4 main flow  → y=4400, x increases left-to-right

POS: dict[str, list[int]] = {
    # ── Workflow 1 main flow (y=0) ────────────────────────────────────────────
    "Webhook":                      [0,    0],
    "Create Heir Session":          [260,  0],
    "Root Owner Research":          [520,  0],
    "Write Root Person":            [820,  0],
    "Queue Initial Relatives":      [1080, 0],
    "Trigger Orchestrator Init":    [1340, 0],

    # Root Research model + tools (below agent at x=520)
    "GPT-5-Mini (Root Research)":   [760,  200],
    "Load Property State":          [300,  200],
    "SkipGenie — Root Decedent":    [300,  380],
    "Ancestry Search Root":         [300,  560],
    "Brave Search Root":            [300,  740],
    "Fetch Obit Root":              [300,  920],
    "NC Voter Root":                [300,  1100],
    "Write Voter Root":             [300,  1280],
    "Court Search Root":            [520,  380],
    "Register Actions Root":        [520,  560],
    "Court Doc Root":               [520,  740],
    "Write Court Root":             [520,  920],
    "Write Ancestry Root":          [520,  1100],
    "Ancestry Search Save Root":    [760,  380],
    "Ancestry Record Root":         [760,  560],
    "Ancestry Household Root":      [760,  740],

    # ── Workflow 2: Orchestrator main flow (y=1600) ──────────────────────────
    "Orchestrator Webhook":         [0,    1600],
    "Heir Research Orchestrator":   [300,  1600],
    "Mark Person Done (Orch)":      [600,  1600],
    "Check Queue Status (Orch)":    [860,  1600],
    "If Queue Empty (Orch)":        [1120, 1600],
    "Trigger Family Assembly":      [1380, 1600],
    "Self Trigger Orchestrator":    [1120, 1820],

    # Orchestrator model + tools
    "GPT-5-Mini (Orch)":            [560,  1820],

    # Research tools (col 1: x=80, col 2: x=300)
    "SkipGenie (Orch)":             [80,   1820],
    "NC Voter (Orch)":              [80,   2000],
    "Ancestry Search Save (Orch)":  [80,   2180],
    "Ancestry Record (Orch)":       [80,   2360],
    "Brave Search (Orch)":          [80,   2540],
    "Fetch Obituary Page (Orch)":   [80,   2720],
    "Wake Deeds (Orch)":            [80,   2900],
    "Buncombe Deeds (Orch)":        [80,   3080],
    "Mecklenburg Deeds (Orch)":     [80,   3260],
    "Ancestry Household (Orch)":    [80,   3440],

    # DB read tools (col 2: x=300)
    "Load Person (Orch)":           [300,  1820],
    "Load Ancestry Records (Orch)": [300,  2000],
    "Load Court Findings (Orch)":   [300,  2180],
    "Load Voter Records (Orch)":    [300,  2360],
    "Load Property State (Orch)":  [300,  2540],

    # DB write + sub-agent tools (col 3: x=520)
    "Write Person (Orch)":          [520,  1820],
    "Write Voter Record (Orch)":    [520,  2000],
    "Queue Persons (Orch)":         [520,  2180],
    "Court Researcher Tool":        [520,  2360],
    # AI sub-agent tools (col 4: x=740)
    "Ancestry Selector Agent":      [740,  1820],
    "SkipGenie Resolver Agent":     [740,  2000],
    # Ancestry Selector internals
    "GPT-5-Mini (Ancestry Selector)": [1000, 1820],
    "Ancestry Search Save (AS)":    [960,  2000],
    "Ancestry Record (AS)":         [960,  2180],
    # SkipGenie Resolver internals
    "GPT-5-Mini (SkipGenie Resolver)": [1000, 2360],
    "SkipGenie (SR)":               [960,  2540],
    "Write Person (SR)":            [960,  2720],

    # ── Workflow 3: Court Researcher main flow (y=3600) ──────────────────────
    "Court Researcher Webhook":     [0,    3600],
    "Court Researcher Agent":       [300,  3600],
    "Return Court Result":          [600,  3600],

    # Court Researcher model + tools
    "GPT-5-Mini (Court Researcher)":[560,  3800],
    "Court Search (CR)":            [80,   3800],
    "Register of Actions (CR)":     [80,   3980],
    "Court Document Pull (CR)":     [80,   4160],
    "Write Court Findings (CR)":    [80,   4340],

    # ── Workflow 4: Family Assembly (simplified, y=4800) ─────────────────────
    "FA Webhook":                   [0,    4800],
    "Family Assembler":             [300,  4800],

    # FA model + tools
    "GPT-5-Mini (FA v4)":           [560,  5000],
    "Load Family Dataset (FA)":     [80,   5000],
    "Write Family Tree (FA)":       [80,   5180],
}

# Apply positions — any node not in POS keeps [0,0]
def _apply_positions(nodes: list[dict]) -> None:
    for node in nodes:
        if node["name"] in POS:
            node["position"] = POS[node["name"]]


# ─── Assemble workflow ────────────────────────────────────────────────────────

# Deduplicate nodes by ID (last definition wins)
seen_ids: dict[str, dict] = {}
for node in all_nodes:
    seen_ids[node["id"]] = node

_apply_positions(list(seen_ids.values()))

workflow_v4 = {
    "name": "Heir Tracer v4",
    "nodes": list(seen_ids.values()),
    "connections": connections,
    "active": False,
    "settings": v3.get("settings", {}),
    "versionId": str(uuid.uuid4()),
    "meta": {"instanceId": v3.get("meta", {}).get("instanceId", "")},
    "tags": [],
}

out_path = r"C:\Users\Summer Ishi\Github\TitleMatrix\ScraperSystems\others\heirtracer\workflow_v4_local.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(workflow_v4, f, indent=2, ensure_ascii=False)

print(f"Written {len(workflow_v4['nodes'])} nodes to workflow_v4_local.json")
print(f"Connections: {len(connections)} source nodes")
