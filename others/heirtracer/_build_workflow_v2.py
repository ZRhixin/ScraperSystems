"""
Build workflow_v2_local.json and workflow_v2.json from the v1 skeleton.

v2 changes vs v1:
  REPLACED:
    Candidate Selector (chainLlm) + Claude Haiku (Selector) + Parse Selection
      → Vital Status Researcher (agent) + Claude Haiku (VSR) + Parse Vital Status
    Obituary Researcher (agent) + OpenAI Chat Model (Obituary)
      → Obituary Deep Diver (agent) — self-gates for living+high_confidence persons

  ADDED:
    Surname Crosser (agent, Haiku) + Claude Haiku (SCR) + Parse Surname Crosser
    Court Document Pull tool → Title Attorney
    Load Voter Records tool → Family Assembler

  MODIFIED:
    Person Compiler — reads from Parse Vital Status / Parse Obit Deep / Parse Surname Crosser
    Title Attorney system prompt — add probate court document pull instructions
    Family Assembler system prompt — add voter records load instructions

Usage:
  cd ScraperSystems
  python others/heirtracer/_build_workflow_v2.py
"""
import copy
import json
import uuid
from pathlib import Path

HERE = Path(__file__).parent
V1_FILE = HERE / "workflow_local.json"
V2_LOCAL_FILE = HERE / "workflow_v2_local.json"
V2_PROD_FILE = HERE / "workflow_v2.json"

BASE_LOCAL = "http://127.0.0.1:8000"
BASE_PROD = "https://scraper.trustedheirsolutions.com"
N8N_LOCAL = "http://localhost:5678"
N8N_PROD = "https://n8n.trustedheirsolutions.com"

ANTHROPIC_CREDS = {"id": "slx6A4HcMXcKN5Y1", "name": "Anthropic account"}
OPENAI_CREDS = {"id": "BRiOORCgq1BegRm2", "name": "OpenAI account"}
BRAVE_CREDS = {"id": "3fPT950eJwKvubjw", "name": "Brave Search account"}

_REMOVE_NODES = {
    "Candidate Selector",
    "Claude Haiku (Selector)",
    "Parse Selection",
    "Obituary Researcher",
    "OpenAI Chat Model",
}


def uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# New node definitions
# ---------------------------------------------------------------------------

def _vsr_agent() -> dict:
    system = (
        "You are the Vital Status Researcher. Your dual job: (1) select the best SkipGenie candidate "
        "for the person being researched, and (2) determine whether that person is currently living or "
        "deceased using NC voter registration and Ancestry SSDI records.\n\n"
        "STEP 1 — CANDIDATE SELECTION\n"
        "The prompt you receive contains the full candidate-scoring context (SKIPGENIE CANDIDATES, "
        "PROPERTY IDENTITY SIGNALS, PERSONS ALREADY RESEARCHED). Apply the scoring rules exactly as "
        "described and identify the best matching candidate. If the top score is 0 or below, "
        "set selected_index: null.\n\n"
        "STEP 2 — NC VOTER LOOKUP (1-3 lookups)\n"
        "Use NC Voter Lookup to check voter registration status for the selected candidate's name "
        "(or input name if no candidate selected).\n"
        "  - Search by last_name + first_name. If gender is female and a maiden surname is likely "
        "    different, also search by maiden surname.\n"
        "  - status=A (Active) → strong living signal.\n"
        "  - status=R (Removed) → possible deceased or moved.\n"
        "  - Not found → unknown.\n"
        "After each voter lookup, call Write Voter Record to save the result with "
        "search_context='vital_status_researcher'. Pass session_id and property_id from your input.\n\n"
        "STEP 3 — ANCESTRY SSDI CHECK (run when vital status is uncertain or person expected deceased)\n"
        "Call Ancestry Search with: first_name, last_name, death_location='North Carolina'.\n"
        "Look for SSDI (Social Security Death Index) or NC Death Certificate records.\n"
        "A confirmed SSDI hit with matching name and NC location = strong deceased signal.\n\n"
        "STEP 4 — VITAL STATUS DETERMINATION\n"
        "  - Active voter + no SSDI → vital_status: 'living', confidence: 'high'\n"
        "  - SSDI confirmed + inactive/removed voter → vital_status: 'deceased', confidence: 'high'\n"
        "  - SSDI confirmed + no voter → vital_status: 'deceased', confidence: 'high'\n"
        "  - Removed voter only → vital_status: 'deceased', confidence: 'medium'\n"
        "  - No voter + no SSDI → vital_status: 'unknown', confidence: 'low'\n"
        "  - Active voter + SSDI (contradictory) → vital_status: 'unknown', confidence: 'low'\n\n"
        "STEP 5 — OUTPUT\n"
        "Return ONLY this raw JSON object. No markdown. No prose. No code fences.\n"
        "{\n"
        "  \"selected_index\": null,\n"
        "  \"subject_name\": \"\",\n"
        "  \"reason\": \"\",\n"
        "  \"vital_status\": \"living|deceased|unknown\",\n"
        "  \"vital_status_confidence\": \"high|medium|low\",\n"
        "  \"voter_status\": \"active|inactive|removed|not_found\",\n"
        "  \"voter_ncid\": \"\",\n"
        "  \"voter_full_name\": \"\",\n"
        "  \"voter_county\": \"\",\n"
        "  \"ssdi_found\": false,\n"
        "  \"ssdi_dod\": \"\"\n"
        "}\n\n"
        "MAX TOOL CALLS: 5 total (voter lookups + ancestry + write voter combined).\n"
        "NEVER exceed 5 tool calls. NEVER return non-JSON."
    )
    return {
        "parameters": {
            "promptType": "define",
            "text": "={{ $json.llm_prompt }}",
            "options": {
                "systemMessage": system,
                "maxIterations": 5,
            },
        },
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 3.1,
        "position": [-20016, 19744],
        "id": uid(),
        "name": "Vital Status Researcher",
        "continueOnFail": True,
    }


def _claude_haiku_vsr() -> dict:
    return {
        "parameters": {
            "model": {
                "__rl": True,
                "value": "claude-haiku-4-5-20251001",
                "mode": "list",
                "cachedResultName": "Claude Haiku 4.5",
            },
            "options": {},
        },
        "type": "@n8n/n8n-nodes-langchain.lmChatAnthropic",
        "typeVersion": 1.3,
        "position": [-20016, 19904],
        "id": uid(),
        "name": "Claude Haiku (VSR)",
        "credentials": {"anthropicApi": ANTHROPIC_CREDS},
    }


def _nc_voter_vsr() -> dict:
    return {
        "id": uid(),
        "name": "NC Voter (VSR)",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-20160, 19904],
        "parameters": {
            "toolDescription": (
                "NC voter registration lookup for vital status research. "
                "Returns: name (current legal/married name), county, city_state_zip, "
                "status (A=Active=living, R=Removed=possibly deceased), ncid, voter_reg_num. "
                "Search by last_name + first_name. Also search maiden surname for female heirs."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/voter/nc/lookup",
            "sendBody": True,
            "contentType": "json",
            "jsonBody": (
                "={{\n"
                "  {\n"
                "    \"last_name\": $fromAI(\"last_name\", \"Last name to search\"),\n"
                "    \"first_name\": $fromAI(\"first_name\", \"First name\"),\n"
                "    \"birth_year\": $fromAI(\"birth_year\", \"Birth year for identity confirmation, year only e.g. 1942\"),\n"
                "    \"county\": $fromAI(\"county\", \"NC county name e.g. Wake — leave blank for statewide\"),\n"
                "    \"include_removed\": $fromAI(\"include_removed\", \"true to include removed/denied registrations\", \"boolean\")\n"
                "  }\n"
                "}}"
            ),
            "options": {},
        },
    }


def _ancestry_search_vsr() -> dict:
    return {
        "id": uid(),
        "name": "Ancestry Search (VSR)",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-19872, 19904],
        "parameters": {
            "toolDescription": (
                "Search Ancestry.com for SSDI and death records. "
                "Pass first_name, last_name, death_location='North Carolina'. "
                "Returns records with record_type, person_name, dob, dod, source_url."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/ancestry/search",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                "={{ {\n"
                "  \"first_name\": $fromAI(\"first_name\", \"First name\"),\n"
                "  \"last_name\": $fromAI(\"last_name\", \"Last name\"),\n"
                "  \"birth_year\": $fromAI(\"birth_year\", \"Birth year e.g. 1942\"),\n"
                "  \"death_year\": $fromAI(\"death_year\", \"Death year if known\"),\n"
                "  \"death_location\": $fromAI(\"death_location\", \"Death location e.g. North Carolina\"),\n"
                "  \"state\": $fromAI(\"state\", \"State abbreviation, default NC\"),\n"
                "  \"name_x\": $fromAI(\"name_x\", \"Name matching: 1_1=exact (default), 0_1=last only\")\n"
                "} }}"
            ),
            "options": {},
        },
    }


def _write_voter_vsr() -> dict:
    return {
        "id": uid(),
        "name": "Write Voter Record (VSR)",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-19728, 19904],
        "parameters": {
            "toolDescription": (
                "Save NC voter record findings to the database for audit trail. "
                "Call after each voter lookup. Required: session_id, property_id, search_name, "
                "search_context='vital_status_researcher'. Optional: ncid, full_name, county, "
                "city_state_zip, status, status_desc, notes."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/heir/write-voter",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                "={{ {\n"
                "  \"session_id\": $fromAI(\"session_id\", \"Session ID from input context\"),\n"
                "  \"property_id\": $fromAI(\"property_id\", \"Property ID from input context\"),\n"
                "  \"search_name\": $fromAI(\"search_name\", \"Full name searched\"),\n"
                "  \"search_first\": $fromAI(\"search_first\", \"First name searched\"),\n"
                "  \"search_last\": $fromAI(\"search_last\", \"Last name searched\"),\n"
                "  \"search_county\": $fromAI(\"search_county\", \"County searched\"),\n"
                "  \"ncid\": $fromAI(\"ncid\", \"NC voter ID if found\"),\n"
                "  \"voter_reg_num\": $fromAI(\"voter_reg_num\", \"Voter registration number if found\"),\n"
                "  \"full_name\": $fromAI(\"full_name\", \"Current legal name on voter rolls\"),\n"
                "  \"county\": $fromAI(\"county\", \"County from voter record\"),\n"
                "  \"city_state_zip\": $fromAI(\"city_state_zip\", \"City, state, zip from voter record\"),\n"
                "  \"status\": $fromAI(\"status\", \"A=Active, I=Inactive, R=Removed\"),\n"
                "  \"status_desc\": $fromAI(\"status_desc\", \"Status description\"),\n"
                "  \"search_context\": \"vital_status_researcher\",\n"
                "  \"notes\": $fromAI(\"notes\", \"Any relevant notes\")\n"
                "} }}"
            ),
            "options": {},
        },
    }


def _parse_vital_status() -> dict:
    code = r"""
// Input: VSR agent output (main input)
// Context: Orch - Format Prompt has SkipGenie candidates and person data
const vsrRaw = ($input.first().json.output || '').replace(/```json\n?/g, '').replace(/```/g, '').trim();
const ctx = $('Orch - Format Prompt').first().json;

let vsr = {};
try {
  const m = vsrRaw.match(/\{[\s\S]*\}/);
  vsr = JSON.parse(m ? m[0] : vsrRaw);
} catch(e) {
  vsr = { selected_index: null, reason: 'VSR parse error: ' + vsrRaw.slice(0, 80) };
}

const allResults = ctx._all_results || [];
const best = allResults.find(r => r.result_index === vsr.selected_index) || {};

function fmtAddr(a) {
  if (!a) return '';
  if (typeof a === 'string') return a;
  return [a.address, a.city, a.state, a.zip].filter(Boolean).join(', ');
}

const ncAddrs = (best.addresses || []).filter(a => {
  const s = JSON.stringify(a).toUpperCase();
  return s.includes('"NC"') || s.includes(' NC');
});
const primaryAddr = ncAddrs.length > 0 ? ncAddrs[0] : (best.addresses || [])[0];

// Vital status: VSR determination is authoritative; fallback to SkipGenie deceased flag
let vital_status = vsr.vital_status || 'unknown';
let vital_confidence = vsr.vital_status_confidence || 'low';

// SkipGenie deceased flag as fallback when VSR is uncertain
const sgDeceased = best.deceased;
const skipgenieDeceased =
  sgDeceased === true  || sgDeceased === 'true'  ? true  :
  sgDeceased === false || sgDeceased === 'false' ? false : null;

if (vital_status === 'unknown' && skipgenieDeceased === true)  { vital_status = 'deceased'; vital_confidence = 'low'; }
if (vital_status === 'unknown' && skipgenieDeceased === false) { vital_status = 'living';   vital_confidence = 'low'; }

const selectionConfidence = (vsr.selected_index != null && best.subject_name) ? 'medium' : 'low';

const cascadeRelatives = (best.possible_relatives || []).map(rel => {
  if (typeof rel === 'string') return { name: rel, relationship: 'unknown', age: '' };
  return { name: rel.name || rel.subject_name || '', relationship: rel.relationship || 'unknown', age: rel.age || '' };
}).filter(r => r.name);

const prop = ctx.property_context || {};

return [{ json: {
  name:              ctx.name,
  property_id:       ctx.property_id,
  session_id:        ctx.session_id,
  loop_context:      ctx.loop_context,
  relationship_hint: ctx.relationship_hint,
  age:               best.age || ctx.age || '',
  phone:             ctx.phone,
  address:           ctx.address,
  queue_id:          ctx.queue_id,
  county:            prop.county || (prop.property && prop.property.county) || '',
  parcel_id:         prop.parcel_id || (prop.property && prop.property.parcel_id) || '',
  matched_identity: {
    full_name:  vsr.voter_full_name || best.subject_name || '',
    dob:        best.dob || '',
    dod:        vsr.ssdi_dod || best.dod || '',
    address:    vsr.voter_county ? (vsr.voter_county + ' County NC') : fmtAddr(primaryAddr),
    confidence: selectionConfidence,
  },
  vital_status,
  vital_status_confidence: vital_confidence,
  cascade_relatives: cascadeRelatives,
  skipgenie_deceased: skipgenieDeceased,
  voter_status:    vsr.voter_status || 'not_found',
  voter_ncid:      vsr.voter_ncid || '',
  voter_full_name: vsr.voter_full_name || '',
  _skip_genie_addresses: (best.addresses || []).slice(0, 5),
  property_context:  ctx.property_context,
  session_persons:   ctx.session_persons,
  notes: '[VSR] ' + (vsr.reason || '') + ' | Selected: ' + (best.subject_name || 'none'),
} }];
"""
    return {
        "parameters": {"jsCode": code},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-19744, 19744],
        "id": uid(),
        "name": "Parse Vital Status",
        "continueOnFail": True,
    }


def _obituary_deep_diver() -> dict:
    system = (
        "You are the Obituary Deep Diver. You find obituaries and Ancestry genealogy records for "
        "deceased persons and extract family structure data.\n\n"
        "SELF-GATE CHECK — read vital_status and vital_status_confidence from your input JSON.\n"
        "IF vital_status = 'living' AND vital_status_confidence = 'high':\n"
        "  → This person is confirmed living. Skip all obit and Ancestry searches.\n"
        "  → Return immediately:\n"
        "  { \"is_deceased\": false, \"date_of_death\": \"\", \"death_location\": \"\", "
        "\"marital_status_at_death\": \"\", \"surviving_spouse\": \"\", \"survivors\": [], "
        "\"ancestry_children\": [], \"maiden_name\": \"\", \"obituary_url\": \"\", "
        "\"obituary_text\": \"\", \"confidence\": \"high\", \"source\": \"voter_registration\", "
        "\"notes\": \"Confirmed living via voter registration — obit search skipped\" }\n\n"
        "FOR ALL OTHER CASES — follow the full research protocol:\n\n"
        "STEP 1 — BRAVE SEARCH (stop at first usable result, max 2 searches)\n"
        "1. \"[Full Name] obituary [county] NC site:tributearchive.com OR site:dignitymemorial.com OR "
        "site:forevermissed.com\"\n"
        "2. \"[Full Name] obituary [city] NC [approximate death year if known]\"\n"
        "IMPORTANT — legacy.com is BLOCKED by Cloudflare. Extract from snippet only.\n\n"
        "STEP 2 — EXTRACT FROM SNIPPETS FIRST\n"
        "Read snippets before fetching. If snippet has DOD and survivor names, you may skip fetch.\n\n"
        "STEP 3 — FETCH (skip legacy.com)\n"
        "If non-legacy.com URL found, call Fetch Obituary Page immediately.\n\n"
        "STEP 4 — ANCESTRY SEARCH (always run)\n"
        "Call Ancestry Search with: first_name, last_name, birth_year, death_location='North Carolina'.\n"
        "Look for SSDI, NC Death Certificates, census records. Collect children[] from matched records.\n"
        "Then call Write Ancestry Findings with all relevant records.\n\n"
        "STEP 4b — MAIDEN NAME / MARRIAGE RECORDS\n"
        "For female heirs: scan obituary for 'née', 'born [Surname]'. Search Ancestry with birth surname "
        "if married name differs from family surname. Extract maiden_name if found.\n\n"
        "STEP 4d — NC VOTER LOOKUP (for uncertain vital status)\n"
        "If vital_status = 'unknown': call NC Voter Lookup. Active = likely living. Removed = possible "
        "deceased. Search maiden surname too for female heirs.\n\n"
        "STEP 5 — IDENTITY VERIFICATION GATE\n"
        "A name match alone is NEVER sufficient. Use the strongest identity signal available:\n"
        "  NAME SIMILARITY: no unrecognized middle name/suffix vs. search name.\n"
        "  RELATIVE OVERLAP: known_relatives list (from SkipGenie if available, or from Ancestry/obit findings).\n"
        "  If known_relatives is empty (SkipGenie returned no match): use geography + birth/death year plausibility "
        "as the overlap signal instead. An obituary naming the correct county and a plausible death year is "
        "sufficient for medium confidence when no relatives are available to cross-check.\n"
        "Confidence rules:\n"
        "  No discrepancy + ≥1 relative overlap → high\n"
        "  No discrepancy + 0 overlap + uncommon name → medium\n"
        "  No discrepancy + 0 overlap + correct county/year + common name → low (include but flag)\n"
        "  No discrepancy + geography match only (no relatives to check) → medium\n"
        "  Discrepancy + ≥2 overlaps → medium\n"
        "  Discrepancy + ≤1 overlap → REJECT (return empty)\n\n"
        "STEP 6 — RETURN\n"
        "Return ONLY raw JSON (no markdown):\n"
        "{ \"is_deceased\": null, \"date_of_death\": \"\", \"death_location\": \"\", "
        "\"marital_status_at_death\": \"\", \"surviving_spouse\": \"\", \"survivors\": [], "
        "\"ancestry_children\": [], \"maiden_name\": \"\", \"obituary_url\": \"\", "
        "\"obituary_text\": \"\", \"confidence\": \"high|medium|low\", \"source\": \"\", "
        "\"notes\": \"\" }\n\n"
        "If no obituary found after 2 searches: return the structure above with confidence: 'low', "
        "notes: 'No obituary found'. If Ancestry SSDI confirms death, set is_deceased: true.\n"
        "MAX TOOL CALLS: 9. NEVER exceed 9. NEVER throw errors."
    )
    return {
        "parameters": {
            "promptType": "define",
            "text": (
                "=Search for an obituary for this person:\n\n"
                "Full Name: {{ $json.matched_identity && $json.matched_identity.full_name ? "
                "$json.matched_identity.full_name : $json.name }}\n"
                "Birth year: {{ $json.matched_identity && $json.matched_identity.dob || 'unknown' }}\n"
                "SkipGenie death year: {{ $json.matched_identity && $json.matched_identity.dod || 'unknown' }}\n"
                "County: {{ $json.county || 'NC' }}\n"
                "Vital status (from VSR): {{ $json.vital_status }} "
                "(confidence: {{ $json.vital_status_confidence }})\n"
                "Voter status: {{ $json.voter_status || 'not_found' }}\n\n"
                "KNOWN RELATIVES (from SkipGenie — use to verify obituary identity):\n"
                "{{ JSON.stringify(($json.cascade_relatives || []).slice(0, 12).map(r => r.name || r)) }}\n\n"
                "PERSONS ALREADY RESEARCHED THIS SESSION:\n"
                "{{ JSON.stringify(($json.session_persons || []).slice(0, 20).map(p => ({"
                "name: p.matched_full_name || p.input_name, "
                "relationship: p.relationship_hint || '', "
                "status: p.vital_status || ''"
                "})).filter(p => p.name)) }}\n\n"
                "PROPERTY & OWNERSHIP CONTEXT:\n"
                "{{ JSON.stringify($json.property_context) }}"
            ),
            "options": {
                "systemMessage": system,
                "maxIterations": 9,
            },
        },
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 3.1,
        "position": [-19520, 19744],
        "id": uid(),
        "name": "Obituary Deep Diver",
        "continueOnFail": True,
    }


def _openai_deep_diver() -> dict:
    return {
        "parameters": {
            "model": {"__rl": True, "value": "gpt-5-mini"},
            "builtInTools": {},
            "options": {},
        },
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
        "typeVersion": 1.3,
        "position": [-19664, 19936],
        "id": uid(),
        "name": "OpenAI Chat Model (Deep Diver)",
        "credentials": {"openAiApi": OPENAI_CREDS},
    }


def _parse_obit_deep() -> dict:
    # Same logic as Parse Obituary Output — just renamed for clarity
    code = r"""
const raw = $input.first().json.output || '';
let cleaned = raw.replace(/```json\n?/g, '').replace(/```/g, '').trim();

try { return [{ json: JSON.parse(cleaned) }]; } catch(_) {}

const start = cleaned.indexOf('{');
const lastEnd = cleaned.lastIndexOf('}');
if (start !== -1 && lastEnd > start) {
  try { return [{ json: JSON.parse(cleaned.slice(start, lastEnd + 1)) }]; } catch(_) {}
}

return [{ json: {
  _parse_error: raw.substring(0, 300),
  is_deceased: null,
  date_of_death: '',
  death_location: '',
  marital_status_at_death: '',
  surviving_spouse: '',
  survivors: [],
  ancestry_children: [],
  obituary_url: '',
  obituary_text: '',
  confidence: 'low',
  source: '',
  notes: 'No obituary found or agent parse failed'
} }];
"""
    return {
        "parameters": {"jsCode": code},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-19280, 19744],
        "id": uid(),
        "name": "Parse Obit Deep",
        "continueOnFail": True,
    }


def _surname_crosser() -> dict:
    system = (
        "You are the Surname Crosser. Your job is to find children and descendants of a deceased person "
        "who may have DIFFERENT surnames (due to marriage, adoption, or paternal lineage).\n\n"
        "SELF-GATE: If the person's vital_status is 'living', return immediately:\n"
        "{ \"scr_children\": [], \"notes\": \"Person is living — surname cross not needed\" }\n\n"
        "STEP 1 — ANCESTRY PARENT-MODE SEARCH\n"
        "Search for records that list this person as a parent.\n"
        "Call Ancestry Search (SCR) with:\n"
        "  - first_name: '' (empty — searching for records that name this person as parent)\n"
        "  - last_name: this person's last name\n"
        "  - mother: this person's full name (if female/unknown gender)\n"
        "  OR father: this person's full name (if male)\n"
        "  - state: 'NC'\n"
        "This returns records where the person appears as mother/father — revealing children's names "
        "and their surnames at birth.\n\n"
        "STEP 2 — EVALUATE RESULTS\n"
        "From Ancestry results, collect every unique child name found across all matching records.\n"
        "Focus on: children[] arrays in matched records, and person_name records where this person "
        "appears in parents[].\n\n"
        "STEP 3 — NC VOTER CROSS-REFERENCE (for up to 3 high-priority new names)\n"
        "For children with surnames different from the deceased person:\n"
        "  Call NC Voter (SCR) with the child's name to get their current address and confirm identity.\n"
        "  Call Write Voter Record (SCR) with search_context='surname_crosser' to save the finding.\n\n"
        "STEP 4 — OUTPUT\n"
        "Return ONLY raw JSON (no markdown):\n"
        "{\n"
        "  \"scr_children\": [\n"
        "    { \"name\": \"\", \"relationship\": \"child\", \"surname_source\": \"ancestry_parent_mode\", "
        "\"voter_confirmed\": false }\n"
        "  ],\n"
        "  \"notes\": \"\"\n"
        "}\n\n"
        "MAX TOOL CALLS: 6. NEVER exceed 6. NEVER return non-JSON."
    )
    return {
        "parameters": {
            "promptType": "define",
            "text": (
                "=Find children with different surnames for this person.\n\n"
                "Person Name: {{ $('Parse Vital Status').first().json.matched_identity && "
                "$('Parse Vital Status').first().json.matched_identity.full_name || "
                "$('Parse Vital Status').first().json.name }}\n"
                "Vital Status: {{ $('Parse Vital Status').first().json.vital_status }}\n"
                "Relationship to decedent: {{ $('Parse Vital Status').first().json.relationship_hint }}\n"
                "County: {{ $('Parse Vital Status').first().json.county || 'Wake' }}\n"
                "Session ID: {{ $('Parse Vital Status').first().json.session_id }}\n"
                "Property ID: {{ $('Parse Vital Status').first().json.property_id }}\n\n"
                "Known children from obituary:\n"
                "{{ JSON.stringify(($json.survivors || []).filter(s => "
                "s.relationship === 'child' || s.relationship === 'daughter' || "
                "s.relationship === 'son')) }}\n"
                "Ancestry children already found:\n"
                "{{ JSON.stringify($json.ancestry_children || []) }}"
            ),
            "options": {
                "systemMessage": system,
                "maxIterations": 6,
            },
        },
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 3.1,
        "position": [-19040, 19744],
        "id": uid(),
        "name": "Surname Crosser",
        "continueOnFail": True,
    }


def _claude_haiku_scr() -> dict:
    return {
        "parameters": {
            "model": {
                "__rl": True,
                "value": "claude-haiku-4-5-20251001",
                "mode": "list",
                "cachedResultName": "Claude Haiku 4.5",
            },
            "options": {},
        },
        "type": "@n8n/n8n-nodes-langchain.lmChatAnthropic",
        "typeVersion": 1.3,
        "position": [-19040, 19936],
        "id": uid(),
        "name": "Claude Haiku (SCR)",
        "credentials": {"anthropicApi": ANTHROPIC_CREDS},
    }


def _ancestry_search_scr() -> dict:
    return {
        "id": uid(),
        "name": "Ancestry Search (SCR)",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-19184, 19936],
        "parameters": {
            "toolDescription": (
                "Search Ancestry.com in parent-mode — finds records that list this person as a parent. "
                "Pass mother='FULL NAME' (or father='FULL NAME') to find their children's records, "
                "even when children have different surnames. Returns children[] arrays from matched records."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/ancestry/search",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                "={{ {\n"
                "  \"first_name\": $fromAI(\"first_name\", \"First name — use empty string for parent-mode search\"),\n"
                "  \"last_name\": $fromAI(\"last_name\", \"Last name of the child you're looking for, or parent's surname for parent-mode\"),\n"
                "  \"mother\": $fromAI(\"mother\", \"Full name of mother for parent-mode search (finds children listed under this mother)\"),\n"
                "  \"father\": $fromAI(\"father\", \"Full name of father for parent-mode search\"),\n"
                "  \"birth_year\": $fromAI(\"birth_year\", \"Birth year if known\"),\n"
                "  \"state\": $fromAI(\"state\", \"State, default NC\"),\n"
                "  \"name_x\": $fromAI(\"name_x\", \"Name matching mode: 1_1=exact, 0_1=last only\")\n"
                "} }}"
            ),
            "options": {},
        },
    }


def _nc_voter_scr() -> dict:
    return {
        "id": uid(),
        "name": "NC Voter (SCR)",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-18896, 19936],
        "parameters": {
            "toolDescription": (
                "NC voter lookup for confirming child identities found via Ancestry parent-mode search. "
                "Use to get current address and confirm the child's current legal (married) name. "
                "Returns: full_name (current name on voter rolls), county, city_state_zip, status."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/voter/nc/lookup",
            "sendBody": True,
            "contentType": "json",
            "jsonBody": (
                "={{\n"
                "  {\n"
                "    \"last_name\": $fromAI(\"last_name\", \"Last name to search\"),\n"
                "    \"first_name\": $fromAI(\"first_name\", \"First name\"),\n"
                "    \"county\": $fromAI(\"county\", \"NC county name — leave blank for statewide\"),\n"
                "    \"include_removed\": $fromAI(\"include_removed\", \"true to include removed registrations\", \"boolean\")\n"
                "  }\n"
                "}}"
            ),
            "options": {},
        },
    }


def _write_voter_scr() -> dict:
    return {
        "id": uid(),
        "name": "Write Voter Record (SCR)",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-18752, 19936],
        "parameters": {
            "toolDescription": (
                "Save voter record findings from Surname Crosser to the database. "
                "Required: session_id, property_id, search_name. "
                "search_context is always 'surname_crosser'."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/heir/write-voter",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                "={{ {\n"
                "  \"session_id\": $fromAI(\"session_id\", \"Session ID\"),\n"
                "  \"property_id\": $fromAI(\"property_id\", \"Property ID\"),\n"
                "  \"search_name\": $fromAI(\"search_name\", \"Name searched\"),\n"
                "  \"search_first\": $fromAI(\"search_first\", \"First name\"),\n"
                "  \"search_last\": $fromAI(\"search_last\", \"Last name\"),\n"
                "  \"search_county\": $fromAI(\"search_county\", \"County searched\"),\n"
                "  \"ncid\": $fromAI(\"ncid\", \"NC voter ID if found\"),\n"
                "  \"full_name\": $fromAI(\"full_name\", \"Current legal name from voter rolls\"),\n"
                "  \"county\": $fromAI(\"county\", \"County from voter record\"),\n"
                "  \"city_state_zip\": $fromAI(\"city_state_zip\", \"Address from voter record\"),\n"
                "  \"status\": $fromAI(\"status\", \"Voter status code\"),\n"
                "  \"search_context\": \"surname_crosser\",\n"
                "  \"notes\": $fromAI(\"notes\", \"Notes about this finding\")\n"
                "} }}"
            ),
            "options": {},
        },
    }


def _parse_surname_crosser() -> dict:
    code = r"""
// Input: Surname Crosser agent output (main)
// Context: Parse Vital Status, Parse Obit Deep
const scrRaw = ($input.first().json.output || '').replace(/```json\n?/g, '').replace(/```/g, '').trim();
const vst = $('Parse Vital Status').first().json;
const obit = $('Parse Obit Deep').first().json;

let scr = {};
try {
  const m = scrRaw.match(/\{[\s\S]*\}/);
  scr = JSON.parse(m ? m[0] : scrRaw);
} catch(e) {
  scr = { scr_children: [], notes: 'SCR parse error: ' + scrRaw.slice(0, 80) };
}

function normName(n) {
  return (n || '').toUpperCase().replace(/[^A-Z ]/g, '').trim().replace(/\s+/g, ' ');
}
const JUNK = [/^HEIRS OF/i, /^HEIR OF/i, /^ESTATE OF/i, /^ESTATE$/i,
              /^UNKNOWN$/i, /^N\/A$/i, /^NA$/i, /^NONE$/i, /^NULL$/i];
function isJunk(name) {
  if (!name || name.trim().length < 3) return true;
  if (/^\d+$/.test(name.trim())) return true;
  return JUNK.some(p => p.test(name.trim()));
}

const seen = new Set();
const cascade_relatives = [];

function addRelative(name, relationship, source, extras) {
  if (isJunk(name)) return;
  const key = normName(name);
  if (!key || seen.has(key)) return;
  seen.add(key);
  cascade_relatives.push({ name: name.trim(), relationship: relationship || 'unknown', source, ...(extras || {}) });
}

// Priority 1: Surname Crosser children (highest — specifically targets surname boundary crossings)
for (const c of (scr.scr_children || [])) {
  if (typeof c === 'string') {
    addRelative(c, 'child', 'surname_crosser');
  } else if (c && c.name) {
    addRelative(c.name, c.relationship || 'child', 'surname_crosser',
      c.voter_confirmed ? { voter_confirmed: true } : undefined);
  }
}

// Priority 2: Obituary survivors (confirmed obit only)
const obitConf = obit.confidence || '';
if (obitConf === 'high' || obitConf === 'medium') {
  for (const s of (obit.survivors || [])) {
    if (typeof s === 'string') {
      addRelative(s, 'survivor', 'obituary');
    } else if (s && s.name) {
      const extras = {};
      if (s.maiden_name) extras.maiden_name = s.maiden_name;
      addRelative(s.name, s.relationship || 'survivor', 'obituary', extras);
    }
  }
}

// Priority 3: Ancestry children from obituary researcher
for (const c of (obit.ancestry_children || [])) {
  if (typeof c === 'string') {
    addRelative(c, 'child', 'ancestry');
  } else if (c && c.name) {
    addRelative(c.name, c.relationship || 'child', 'ancestry');
  }
}

// Priority 4: SkipGenie relatives (fill remaining gaps)
for (const r of (vst.cascade_relatives || [])) {
  if (typeof r === 'string') {
    addRelative(r, 'unknown', 'skipgenie');
  } else if (r && r.name) {
    addRelative(r.name, r.relationship || 'unknown', 'skipgenie');
  }
}

// Pass through the merged context for Person Compiler
return [{ json: {
  // Forward vst data
  name:              vst.name || '',
  property_id:       vst.property_id,
  session_id:        vst.session_id,
  queue_id:          vst.queue_id,
  loop_context:      vst.loop_context || 'worker',
  relationship_hint: vst.relationship_hint || '',
  age:               vst.age || '',
  phone:             vst.phone || '',
  address:           vst.address || '',
  county:            vst.county || '',
  parcel_id:         vst.parcel_id || '',
  matched_identity:  vst.matched_identity,
  vital_status:      vst.vital_status || 'unknown',
  skipgenie_deceased: vst.skipgenie_deceased,
  _skip_genie_addresses: vst._skip_genie_addresses || [],
  property_context:  vst.property_context,
  session_persons:   vst.session_persons,
  // Merged cascade relatives
  cascade_relatives,
  // Obit data
  obit_is_deceased:   obit.is_deceased,
  obit_date_of_death: obit.date_of_death || '',
  obit_marital_status: obit.marital_status_at_death || '',
  obit_surviving_spouse: obit.surviving_spouse || '',
  obit_survivors:     obit.survivors || [],
  obit_url:           obit.obituary_url || '',
  obit_text:          obit.obituary_text || '',
  obit_confidence:    obit.confidence || 'low',
  maiden_name:        obit.maiden_name || '',
  // SCR data
  scr_children:       scr.scr_children || [],
  notes: [vst.notes ? 'VSR: ' + vst.notes : '', scr.notes ? 'SCR: ' + scr.notes : ''].filter(Boolean).join(' | '),
} }];
"""
    return {
        "parameters": {"jsCode": code},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-18800, 19744],
        "id": uid(),
        "name": "Parse Surname Crosser",
        "continueOnFail": True,
    }


def _court_document_pull_tool() -> dict:
    return {
        "id": uid(),
        "name": "Court Document Pull",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-18800, 20336],
        "parameters": {
            "toolDescription": (
                "### Court Document Pull\n"
                "```\n"
                "Download and Claude-extract a probate court document from the NC courts portal.\n"
                "Use when Court Search returns a probate/estate case — pass the case URL to get\n"
                "the full family tree PDF extracted as structured JSON with named_persons and\n"
                "family_tree (including has_issue=false for confirmed no-children branches).\n"
                "Input: { url: \"https://portal-nc.tylertech.cloud/app/RegisterOfActions/...\" }\n"
                "Output: { case_id, documents: [{ url, extraction: { named_persons, family_tree, "
                "decedent_name, flags, ... } }] }\n"
                "The extraction.family_tree[].has_issue field is critical:\n"
                "  false = confirmed no children (branch extinct)\n"
                "  true  = confirmed has children\n"
                "  null  = not stated\n"
                "```"
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/court/nc/pull-document",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                "={{ { \"url\": $fromAI(\"url\", "
                "\"Full NC courts portal URL for the probate case, e.g. "
                "https://portal-nc.tylertech.cloud/app/RegisterOfActions/#/ENCRYPTED_ID/anon/portalembed\") } }}"
            ),
            "options": {},
        },
    }


def _load_voter_records_tool() -> dict:
    return {
        "id": uid(),
        "name": "Load Voter Records",
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.4,
        "position": [-19648, 19216],
        "parameters": {
            "toolDescription": (
                "Load NC voter registration records saved by Vital Status Researcher and Surname Crosser "
                "for this session. Reveals: current legal/married names of female heirs, living status "
                "confirmation, current addresses. "
                "Input: { session_id }. Optional: person_id, status ('A' for active only)."
            ),
            "method": "POST",
            "url": f"{BASE_LOCAL}/heir/voter-records",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": (
                "={{ { "
                "\"session_id\": $fromAI(\"session_id\", \"The session ID to load voter records for\"), "
                "\"person_id\": $fromAI(\"person_id\", \"Optional: specific person_id filter\"), "
                "\"status\": $fromAI(\"status\", \"Optional: filter by voter status e.g. A for active only\") "
                "} }}"
            ),
            "options": {},
        },
    }


def _updated_person_compiler_code() -> str:
    return r"""
// Source nodes (v2)
const orch = $('Parse Vital Status').first().json;
const obit = $('Parse Obit Deep').first().json;
const scr  = $('Parse Surname Crosser').first().json;

// Parse Title Attorney raw agent output
const taRaw = ($input.first().json.output || '').replace(/```json\n?/g, '').replace(/```/g, '').trim();
let ta = {};
try {
  ta = JSON.parse(taRaw);
} catch(_) {
  const s = taRaw.indexOf('{');
  const e = taRaw.lastIndexOf('}');
  if (s !== -1 && e > s) {
    try { ta = JSON.parse(taRaw.slice(s, e + 1)); } catch(_) {}
  }
}

// Resolve vital status — VSR is now authoritative; obituary can upgrade deceased confidence
let vital_status = orch.vital_status || 'unknown';
if (obit.is_deceased === true  && vital_status === 'unknown') vital_status = 'deceased';
if (obit.is_deceased === false && vital_status === 'unknown') vital_status = 'living';

const deedCheck  = ta.deed_check  || {};
const courtCheck = ta.court_check || {};
const estFiled   = courtCheck.estate_filed !== undefined ? courtCheck.estate_filed : null;
const hadWill    = courtCheck.had_will     !== undefined ? courtCheck.had_will     : null;

const cascade_needed = vital_status === 'deceased' && estFiled !== true;

// cascade_relatives come directly from Parse Surname Crosser (already merged + deduplicated)
const cascade_relatives = scr.cascade_relatives || [];

const identity = orch.matched_identity || {};
const obitConf = obit.confidence || scr.obit_confidence || '';

return [{ json: {
  name:              orch.name || '',
  property_id:       orch.property_id,
  session_id:        orch.session_id,
  queue_id:          orch.queue_id,
  loop_context:      orch.loop_context || 'worker',
  relationship_hint: orch.relationship_hint || '',
  age:               orch.age || '',
  phone:             orch.phone || '',
  address:           orch.address || '',
  county:            orch.county || '',
  parcel_id:         orch.parcel_id || '',
  matched_identity:  identity,
  cascade_relatives,
  vital_status,
  deceased_facts: {
    date_of_death:           scr.obit_date_of_death || obit.date_of_death || '',
    marital_status_at_death: scr.obit_marital_status || obit.marital_status_at_death || '',
    surviving_spouse_name:   scr.obit_surviving_spouse || obit.surviving_spouse || '',
    estate_filed:            estFiled,
    had_will:                hadWill,
    family_alive_at_death:   scr.obit_survivors || obit.survivors || [],
  },
  deed_transfers:  deedCheck.transfers || [],
  cascade_needed,
  obituary_url:    scr.obit_url  || obit.obituary_url  || '',
  obituary_text:   scr.obit_text || obit.obituary_text || '',
  claim_sources: {
    date_of_death: {
      value:      scr.obit_date_of_death || obit.date_of_death || '',
      source:     (scr.obit_url || obit.obituary_url) ? 'obituary' : (identity.dod ? 'skipgenie' : 'unknown'),
      url:        scr.obit_url || obit.obituary_url || '',
      confidence: (scr.obit_date_of_death || obit.date_of_death) ? (obitConf || 'medium') : 'none',
    },
    marital_status_at_death: {
      value:      scr.obit_marital_status || obit.marital_status_at_death || '',
      source:     (scr.obit_marital_status || obit.marital_status_at_death) ? 'obituary' : 'unknown',
      confidence: (scr.obit_marital_status || obit.marital_status_at_death) ? 'medium' : 'none',
    },
    estate_filed: {
      value:        estFiled,
      source:       estFiled !== null ? 'nc_courts' : 'unknown',
      case_numbers: (courtCheck.cases || []).map(c => c.case_number).filter(Boolean),
      confidence:   estFiled !== null ? 'high' : 'low',
    },
    had_will: {
      value:      hadWill,
      source:     hadWill !== null ? 'register_of_actions' : 'unknown',
      confidence: hadWill !== null ? 'medium' : 'none',
    },
    family_alive_at_death: {
      sources:    (scr.obit_survivors || obit.survivors || []).length ? ['obituary'] : [],
      confidence: (scr.obit_survivors || obit.survivors || []).length ? (obitConf || 'medium') : 'none',
    },
  },
  maiden_name:        scr.maiden_name || obit.maiden_name || '',
  skipgenie_deceased: orch.skipgenie_deceased,
  voter_status:       orch.voter_status || 'not_found',
  voter_full_name:    orch.voter_full_name || '',
  notes: [orch.notes ? 'Orch: ' + orch.notes : '', ta.notes ? 'TA: ' + ta.notes : ''].filter(Boolean).join(' | '),
} }];
"""


def _updated_ta_system_prompt(original: str) -> str:
    """Add Court Document Pull instructions to Title Attorney system prompt."""
    addition = (
        "\n\n## TASK 3 — PROBATE COURT DOCUMENT PULL\n"
        "If Court Search returns a case with case_type 'E' (Estate) or 'SP' (Special Proceedings):\n"
        "  1. Call Court Document Pull with the register_of_actions_url from that case result.\n"
        "     The URL looks like: https://portal-nc.tylertech.cloud/app/RegisterOfActions/?id=...\n"
        "     Pass it as the 'url' parameter to Court Document Pull.\n"
        "  2. The extraction returns a family_tree array with has_issue per person:\n"
        "     - has_issue=false → confirmed no children (branch extinct — extremely valuable)\n"
        "     - has_issue=true  → confirmed has children\n"
        "     - has_issue=null  → not stated in document\n"
        "  3. Add a note to your output: 'probate_document_pulled: true' and include key\n"
        "     has_issue=false findings in your notes field.\n"
        "  4. If the endpoint returns an error or documents: [], skip silently.\n\n"
        "Include probate findings in your OUTPUT:\n"
        "  court_check.probate_family_tree: the family_tree array from the extraction (or [] if none)\n"
        "  court_check.probate_no_issue: array of names confirmed has_issue=false"
    )
    return original + addition


def _updated_fa_system_prompt(original: str) -> str:
    """Add Load Voter Records instructions to Family Assembler system prompt."""
    addition = (
        "\n\nSTEP 3b — Load Voter Records\n"
        "Call Load Voter Records with the session_id. This returns NC voter registration records "
        "saved by the Vital Status Researcher and Surname Crosser agents. Each record includes:\n"
        "  - full_name: current legal/married name on voter rolls (KEY for married female heirs)\n"
        "  - status: A=Active (confirmed living), R=Removed (possibly deceased/moved)\n"
        "  - search_context: 'vital_status_researcher' or 'surname_crosser'\n"
        "Use voter records to:\n"
        "  - Confirm living status for heirs the VSR found active registrations for\n"
        "  - Discover married names for female heirs (voter_full_name vs. search_name)\n"
        "  - Cross-reference Surname Crosser children against current voter rolls\n"
        "Apply voter data BEFORE mapping relationships so married-name discoveries inform\n"
        "the family structure."
    )
    return original + addition


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build():
    with open(V1_FILE, encoding="utf-8") as f:
        wf = json.load(f)

    nodes: list = wf["nodes"]
    conns: dict = wf["connections"]

    # -----------------------------------------------------------------------
    # 1. Remove replaced nodes
    # -----------------------------------------------------------------------
    nodes[:] = [n for n in nodes if n.get("name") not in _REMOVE_NODES]
    for name in _REMOVE_NODES:
        conns.pop(name, None)

    # -----------------------------------------------------------------------
    # 2. Add new nodes
    # -----------------------------------------------------------------------
    vsr       = _vsr_agent()
    haiku_vsr = _claude_haiku_vsr()
    voter_vsr = _nc_voter_vsr()
    anc_vsr   = _ancestry_search_vsr()
    wvr_vsr   = _write_voter_vsr()
    pvs       = _parse_vital_status()

    odd       = _obituary_deep_diver()
    openai_dd = _openai_deep_diver()
    pod       = _parse_obit_deep()

    scr_agent = _surname_crosser()
    haiku_scr = _claude_haiku_scr()
    anc_scr   = _ancestry_search_scr()
    voter_scr = _nc_voter_scr()
    wvr_scr   = _write_voter_scr()
    psc       = _parse_surname_crosser()

    cdp_tool  = _court_document_pull_tool()
    lvr_tool  = _load_voter_records_tool()

    new_nodes = [
        vsr, haiku_vsr, voter_vsr, anc_vsr, wvr_vsr, pvs,
        odd, openai_dd, pod,
        scr_agent, haiku_scr, anc_scr, voter_scr, wvr_scr, psc,
        cdp_tool, lvr_tool,
    ]
    nodes.extend(new_nodes)

    # -----------------------------------------------------------------------
    # 3. Update existing nodes
    # -----------------------------------------------------------------------

    # 3a. Rewire NC Voter Lookup + Write Ancestry Findings from Obituary Researcher
    #     to Obituary Deep Diver (update connections below — the tool nodes stay unchanged)

    # 3b. Person Compiler — update code
    pc = next(n for n in nodes if n["name"] == "Person Compiler")
    pc["parameters"]["jsCode"] = _updated_person_compiler_code()

    # 3c. Title Attorney — update system prompt + position to make room
    ta = next(n for n in nodes if n["name"] == "Title Attorney")
    opts = ta["parameters"]["options"]
    opts["systemMessage"] = _updated_ta_system_prompt(opts["systemMessage"])
    ta["position"] = [-18560, 19744]

    # 3d. Family Assembler — update system prompt
    fa = next(n for n in nodes if n["name"] == "Family Assembler")
    fa_opts = fa["parameters"]["options"]
    fa_opts["systemMessage"] = _updated_fa_system_prompt(fa_opts["systemMessage"])

    # 3e. Person Compiler position update
    pc["position"] = [-18320, 19744]

    # -----------------------------------------------------------------------
    # 4. Update connections
    # -----------------------------------------------------------------------

    # Worker pipeline rewiring:
    # Orch - Format Prompt → VSR (was: Candidate Selector)
    conns["Orch - Format Prompt"] = {"main": [[{"node": vsr["name"], "type": "main", "index": 0}]]}

    # VSR → Parse Vital Status (was: Candidate Selector → Parse Selection)
    conns[vsr["name"]] = {"main": [[{"node": pvs["name"], "type": "main", "index": 0}]]}

    # VSR model + tools
    conns[haiku_vsr["name"]] = {"ai_languageModel": [[{"node": vsr["name"], "type": "ai_languageModel", "index": 0}]]}
    conns[voter_vsr["name"]] = {"ai_tool": [[{"node": vsr["name"], "type": "ai_tool", "index": 0}]]}
    conns[anc_vsr["name"]]   = {"ai_tool": [[{"node": vsr["name"], "type": "ai_tool", "index": 0}]]}
    conns[wvr_vsr["name"]]   = {"ai_tool": [[{"node": vsr["name"], "type": "ai_tool", "index": 0}]]}

    # Parse Vital Status → Obituary Deep Diver
    conns[pvs["name"]] = {"main": [[{"node": odd["name"], "type": "main", "index": 0}]]}

    # Obituary Deep Diver → Parse Obit Deep (was: Obituary Researcher → Parse Obituary Output)
    conns[odd["name"]] = {"main": [[{"node": pod["name"], "type": "main", "index": 0}]]}

    # Obituary Deep Diver model
    conns[openai_dd["name"]] = {"ai_languageModel": [[{"node": odd["name"], "type": "ai_languageModel", "index": 0}]]}

    # Rewire existing Obituary Researcher tools → Obituary Deep Diver
    obit_tools = ["Brave Search", "Fetch Obituary Page", "Ancestry Search",
                  "Write Ancestry Findings", "NC Voter Lookup"]
    for tool_name in obit_tools:
        if tool_name in conns:
            conns[tool_name] = {"ai_tool": [[{"node": odd["name"], "type": "ai_tool", "index": 0}]]}

    # Parse Obit Deep → Surname Crosser
    conns[pod["name"]] = {"main": [[{"node": scr_agent["name"], "type": "main", "index": 0}]]}

    # Surname Crosser → Parse Surname Crosser
    conns[scr_agent["name"]] = {"main": [[{"node": psc["name"], "type": "main", "index": 0}]]}

    # Surname Crosser model + tools
    conns[haiku_scr["name"]] = {"ai_languageModel": [[{"node": scr_agent["name"], "type": "ai_languageModel", "index": 0}]]}
    conns[anc_scr["name"]]   = {"ai_tool": [[{"node": scr_agent["name"], "type": "ai_tool", "index": 0}]]}
    conns[voter_scr["name"]] = {"ai_tool": [[{"node": scr_agent["name"], "type": "ai_tool", "index": 0}]]}
    conns[wvr_scr["name"]]   = {"ai_tool": [[{"node": scr_agent["name"], "type": "ai_tool", "index": 0}]]}

    # Parse Surname Crosser → Title Attorney (was: Parse Obituary Output → Title Attorney)
    conns[psc["name"]] = {"main": [[{"node": "Title Attorney", "type": "main", "index": 0}]]}

    # Court Document Pull tool → Title Attorney
    conns[cdp_tool["name"]] = {"ai_tool": [[{"node": "Title Attorney", "type": "ai_tool", "index": 0}]]}

    # Load Voter Records tool → Family Assembler
    conns[lvr_tool["name"]] = {"ai_tool": [[{"node": "Family Assembler", "type": "ai_tool", "index": 0}]]}

    # -----------------------------------------------------------------------
    # 5. Save local version
    # -----------------------------------------------------------------------
    wf["nodes"] = nodes
    wf["connections"] = conns

    with open(V2_LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2)
    print(f"Written: {V2_LOCAL_FILE}")

    # -----------------------------------------------------------------------
    # 6. Save prod version (replace URLs)
    # -----------------------------------------------------------------------
    prod_str = json.dumps(wf, indent=2)
    prod_str = prod_str.replace(BASE_LOCAL, BASE_PROD)
    prod_str = prod_str.replace(N8N_LOCAL + "/webhook/heir-worker",
                                N8N_PROD + "/webhook/heir-worker")
    prod_str = prod_str.replace(N8N_LOCAL + "/webhook/heir-fa",
                                N8N_PROD + "/webhook/heir-fa")

    with open(V2_PROD_FILE, "w", encoding="utf-8") as f:
        f.write(prod_str)
    print(f"Written: {V2_PROD_FILE}")


if __name__ == "__main__":
    build()
