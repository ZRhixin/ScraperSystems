import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

nodes = wf["nodes"]

# -----------------------------------------------------------------------
# FIX: Person Compiler — inject probate names as highest priority + fuzzy dedup
# -----------------------------------------------------------------------
pc_node = next(n for n in nodes if n["name"] == "Person Compiler")
old_cascade_section = """// cascade_relatives come directly from Parse Surname Crosser (already merged + deduplicated)
const cascade_relatives = scr.cascade_relatives || [];"""

new_cascade_section = """// Priority 0: Probate court document family tree — legally sworn filings, highest trust
const probateFamilyTree = (courtCheck.probate_family_tree || []);
const cascade_from_probate = [];
const probate_name_keys = new Set();

function normKey(n) {
  return (n || '').toUpperCase().replace(/[^A-Z ]/g, '').trim().replace(/\\s+/g, ' ');
}
function lastName(key) { const p = key.split(' '); return p[p.length - 1] || ''; }
function firstThree(key) { return (key.split(' ')[0] || '').slice(0, 3); }
function fuzzyMatch(a, b) {
  // Same last name + first 3 chars of first name match → treat as same person
  return lastName(a) === lastName(b) && firstThree(a) === firstThree(b) && firstThree(a).length >= 3;
}

for (const person of probateFamilyTree) {
  const name = (person.name || '').trim();
  if (!name || name.length < 3) continue;
  const key = normKey(name);
  if (probate_name_keys.has(key)) continue;
  probate_name_keys.add(key);
  const rel = person.generation < 0 ? 'parent' :
              person.generation > 0 ? 'child' : 'family_member';
  cascade_from_probate.push({
    name,
    relationship: rel,
    source: 'probate',
    vital_status: person.vital_status || 'unknown',
    has_issue: person.has_issue !== undefined ? person.has_issue : null,
  });
}

// Merge: probate first, then SCR — drop SCR entries that fuzzy-match a probate name (trust legal record)
const seen_final = new Set(probate_name_keys);
const cascade_relatives = [...cascade_from_probate];
for (const rel of (scr.cascade_relatives || [])) {
  const key = normKey(rel.name || '');
  if (!key || key.length < 3) continue;
  // Skip if exact match OR fuzzy match (same last name + first 3 chars) already from a legal record
  const hasLegalMatch = [...probate_name_keys].some(pk => fuzzyMatch(key, pk));
  if (!seen_final.has(key) && !hasLegalMatch) {
    seen_final.add(key);
    cascade_relatives.push(rel);
  }
}"""

old_js = pc_node["parameters"]["jsCode"]
if old_cascade_section in old_js:
    pc_node["parameters"]["jsCode"] = old_js.replace(old_cascade_section, new_cascade_section)
    print("FIX Person Compiler: probate priority + fuzzy dedup applied")
else:
    print("ERROR: Person Compiler cascade section not found")
    print(repr(old_js[old_js.find("cascade_relative"):old_js.find("cascade_relative")+200]))

# -----------------------------------------------------------------------
# FIX: Vital Status Researcher — legal record name flexibility
# -----------------------------------------------------------------------
vsr_node = next(n for n in nodes if n["name"] == "Vital Status Researcher")
old_vsr_step1 = """STEP 1 — CANDIDATE SELECTION
The prompt you receive contains the full candidate-scoring context (SKIPGENIE CANDIDATES, PROPERTY IDENTITY SIGNALS, PERSONS ALREADY RESEARCHED). Apply the scoring rules exactly as described and identify the best matching candidate. If the top score is 0 or below, set selected_index: null."""

new_vsr_step1 = """STEP 1 — CANDIDATE SELECTION
The prompt you receive contains the full candidate-scoring context (SKIPGENIE CANDIDATES, PROPERTY IDENTITY SIGNALS, PERSONS ALREADY RESEARCHED). Apply the scoring rules exactly as described and identify the best matching candidate. If the top score is 0 or below, set selected_index: null.

LEGAL RECORD NAME TRUST: The name being searched may come from a probate filing, obituary, deed, or death certificate. Legal record spellings are authoritative — SkipGenie may have variant spellings for the same person. When matching candidates:
  - Treat first names as matching if they share the first 3+ letters: "Johnie" = "John", "Alyce" = "Alice", "Freddie" = "Fred"
  - Exact last name match is required
  - Do NOT reject a candidate solely because the first name spelling differs slightly from the search name
  - When a legal record name and a SkipGenie name conflict, the legal record name is correct"""

old_vsr = vsr_node["parameters"]["options"]["systemMessage"]
if old_vsr_step1 in old_vsr:
    vsr_node["parameters"]["options"]["systemMessage"] = old_vsr.replace(old_vsr_step1, new_vsr_step1)
    print("FIX Vital Status Researcher: legal name trust added")
else:
    print("ERROR: VSR step 1 not found")

# -----------------------------------------------------------------------
# FIX: Orch - Format Prompt — add legal name note to scoring
# -----------------------------------------------------------------------
fmt_node = next(n for n in nodes if n["name"] == "Orch - Format Prompt")
old_score_note = "    + 'TIEBREAKER: if two candidates score equally, prefer the NC-addressed one.\\n'\n"
new_score_note = (
    "    + 'TIEBREAKER: if two candidates score equally, prefer the NC-addressed one.\\n'\n"
    "    + 'LEGAL RECORD NAMES: The search name may come from a probate filing or deed — trust it over SkipGenie spellings.\\n'\n"
    "    + '  Treat first names as matching if they share the first 3+ letters (Johnie=John, Alyce=Alice, Freddie=Fred).\\n'\n"
    "    + '  Apply +2 last-name bonus if the last name matches, regardless of first-name spelling variation.\\n'\n"
)
old_fmt_js = fmt_node["parameters"]["jsCode"]
if old_score_note in old_fmt_js:
    fmt_node["parameters"]["jsCode"] = old_fmt_js.replace(old_score_note, new_score_note)
    print("FIX Orch - Format Prompt: legal name note added")
else:
    print("ERROR: Orch - Format Prompt tiebreaker line not found")

with open("others/heirtracer/workflow_v2.json", "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)
print("\nworkflow_v2.json saved.")
