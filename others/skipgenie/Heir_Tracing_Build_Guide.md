# Heir Tracing Workflow — n8n Build Guide (v3)

**Workflow name:** Heir Tracing v3  
**Architecture:** Workflow graph drives phases 1–3. Cascade Manager agent handles recursive cascade.  
**Trigger:** POST webhook

---

## What Changed from v2

| v2 | v3 |
|---|---|
| Single Heir Orchestrator runs everything | Workflow graph drives phases 1–3. No mega-orchestrator. |
| Phase 1 sequential | Phase 1: 3 parallel branches — Postgres + Skip Tracer root + Verification root |
| 4 sub-agents (Skip Tracer, Court Research, Estate Analyst, Heir Tree Compiler) | 5 agents: Skip Tracer, Verification Agent, Cascade Manager (with Court Research + Estate Analyst sub-tools), Heir Tree Compiler |
| No alive path verification | Verification Agent runs for every heir — living and deceased |
| 2 stop conditions: living or 5 gen max | One stop condition: confirmed living. Unlimited cascade depth. |

---

## Before You Start

### 1. Create the heir_traces table

Run in Neon PostgreSQL console:

```sql
CREATE TABLE heir_traces (
  id                  SERIAL PRIMARY KEY,
  property_id         INTEGER NOT NULL,
  conclusion_id       INTEGER NOT NULL REFERENCES chain_conclusions(id),
  root_decedent_name  TEXT NOT NULL,
  heir_tree           JSONB NOT NULL,
  living_heir_count   INTEGER,
  total_credits_used  INTEGER,
  status              TEXT DEFAULT 'draft',
  gaps                JSONB,
  fpils_synced_at     TIMESTAMPTZ,
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### 2. Start skipgenieapi

```
cd D:\Github\scraperstesting
python -m skipgenieapi.handler
```

Confirm: `GET http://127.0.0.1:8001` returns `{"status": "ok"}`

### 3. Add web search credential in n8n

Settings → Credentials → New → SerpAPI (or Brave Search API).  
This is needed for the Verification Agent's obituary search tool.

---

## Workflow Overview

```
[Webhook]
  ↓ fans out to 3 branches simultaneously
  ├── [Postgres: Load Context]
  ├── [Skip Tracer Agent: Root Owner]
  └── [Verification Agent: Root Owner]
  ↓
[Merge: Phase 1]
  ↓
[Estate Analyst Agent: Root Owner]      (always intestate — estate_path_unresolved confirmed)
  ↓
[Code: Parse Heir List]
  ↓
[Split In Batches: Level-1 Heirs]
  ↓ (per heir)
[Skip Tracer Agent: Per Heir]
  ↓
[Verification Agent: Per Heir]
  ↓
[Code: Route + Accumulate Results]
  ↓
[Merge: Level-1 Complete]
  ↓
[IF: Any Deceased Heirs in Queue?]
  ├── YES → [Cascade Manager Agent]
  │          Manages full recursive cascade internally.
  │          Tools: SkipGenie HTTP, Web Search, SSDI HTTP (when built),
  │                 Court Research sub-agent, Estate Analyst sub-agent
  │          Returns: cascade_living_heirs, deceased_in_chain, gaps, credits
  └── NO  → skip
  ↓
[Code: Merge All Results for Compiler]
  ↓
[Heir Tree Compiler Agent]
  ↓
[Code: Parse Output]
  ↓
[Postgres: Write heir_traces]
  ↓
[Respond to Webhook]
```

**Node count:** ~16 workflow nodes + 4 sub-agent/tool nodes on Cascade Manager + 3 HTTP tool nodes

---

## Node 1 — Webhook

| Field | Value |
|---|---|
| Type | Webhook |
| HTTP Method | POST |
| Path | `heir-trace/start` |
| Response Mode | Last Node |

**Expected input:**
```json
{
  "property_id":       1,
  "conclusion_id":     3,
  "session_id":        1,
  "deceased_owner":    "Lydia Hayes",
  "last_known_county": "Wake",
  "last_known_state":  "NC",
  "approx_death_year": "1954"
}
```

Connect Webhook output to **3 nodes** (Phase 1 fan-out):
- Postgres: Load Context
- Skip Tracer Agent: Root Owner
- Verification Agent: Root Owner

---

## Node 2A — Postgres: Load Context

| Field | Value |
|---|---|
| Type | Postgres |
| Operation | Execute Query |
| Credential | Neon DB |

```sql
SELECT
  cc.id            AS conclusion_id,
  cc.property_id,
  cc.flags,
  cc.current_owners,
  s.trace_log      AS phase_d_trace,
  s.stop_reason
FROM chain_conclusions cc
LEFT JOIN investigation_sessions s
  ON s.property_id = cc.property_id
  AND s.id = {{ $('Webhook').item.json.body.session_id }}
WHERE cc.id = {{ $('Webhook').item.json.body.conclusion_id }}
LIMIT 1;
```

---

## Node 2B — Skip Tracer Agent: Root Owner

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-haiku-4-5-20251001 |
| Max Iterations | 5 |
| Prompt Type | Define Below |

**User Prompt:**
```
Search for this deceased property owner using SkipGenie.
We already know they are deceased — we need their DOD, relatives, and any contact fragments.

Name: {{ $('Webhook').item.json.body.deceased_owner }}
State: {{ $('Webhook').item.json.body.last_known_state }}
County: {{ $('Webhook').item.json.body.last_known_county }}
Approximate death year: {{ $('Webhook').item.json.body.approx_death_year }}
```

**System Message:** See Section A — Skip Tracer System Prompt

**Attach tool: SkipGenie HTTP (Node 2B-1)**

---

## Node 2B-1 — HTTP Tool: SkipGenie Search

Attach to Skip Tracer Agent: Root Owner (and also to Skip Tracer Agent: Per Heir — same tool config).

| Field | Value |
|---|---|
| Type | HTTP Request Tool |
| Method | POST |
| URL | `http://127.0.0.1:8001` |

**Tool Description:**
```
Calls the SkipGenie API to search for a person by name and state.
Returns deceased flag, DOD, addresses, phones, emails, and possible_relatives.
Returns only the first/best match — verify the result is the right person.
Input: { first_name, last_name, state }
```

**Body (JSON):**
```
={"first_name": "{{ $fromAI('first_name', 'First name') }}", "last_name": "{{ $fromAI('last_name', 'Last name') }}", "state": "{{ $fromAI('state', 'Two-letter state code') }}"}
```

---

## Node 2C — Verification Agent: Root Owner

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-sonnet-4-6 |
| Max Iterations | 10 |
| Prompt Type | Define Below |

**User Prompt:**
```
Verify this person's deceased status and collect evidence.

Name: {{ $('Webhook').item.json.body.deceased_owner }}
State: {{ $('Webhook').item.json.body.last_known_state }}
County: {{ $('Webhook').item.json.body.last_known_county }}
Approximate death year: {{ $('Webhook').item.json.body.approx_death_year }}
SkipGenie claim: deceased
SkipGenie DOD: unknown
SkipGenie relatives: unknown at this stage

This person is confirmed deceased by the Phase D trigger (estate_path_unresolved = true).
Run the deceased path: search for obituary first (Tier 1). If not found, run SSDI check if available.
Extract survivors list from obituary — this tells us who was alive when they died.
```

**System Message:** See Section B — Verification Agent System Prompt

**Attach tools:**
- Web Search Tool (built-in n8n AI tool — uses SerpAPI credential)
- SSDI HTTP Tool (Node 2C-1, when ssdiscraper is built — leave unattached for now)

---

## Node 2C-1 — HTTP Tool: SSDI Search (add later)

Attach to both Verification Agent nodes once ssdiscraper is running.

| Field | Value |
|---|---|
| Type | HTTP Request Tool |
| Method | POST |
| URL | `http://127.0.0.1:8003` |

**Tool Description:**
```
Checks the Social Security Death Index (SSDI) via FamilySearch for a confirmed death record.
Returns government-confirmed DOD and last known ZIP.
Call this ONLY if obituary search found nothing.
Input: { first_name, last_name, state, approx_birth_year? }
```

**Body (JSON):**
```
={"first_name": "{{ $fromAI('first_name', '') }}", "last_name": "{{ $fromAI('last_name', '') }}", "state": "{{ $fromAI('state', '') }}", "approx_birth_year": "{{ $fromAI('approx_birth_year', '', '') }}"}
```

---

## Node 3 — Merge: Phase 1

| Field | Value |
|---|---|
| Type | Merge |
| Mode | Combine (Merge by Position) |
| Number of Inputs | 3 |

Connect:
- Postgres: Load Context → Merge (Input 1)
- Skip Tracer Agent: Root Owner → Merge (Input 2)
- Verification Agent: Root Owner → Merge (Input 3)

---

## Node 4 — Estate Analyst Agent: Root Owner

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-sonnet-4-6 |
| Max Iterations | 10 |
| Prompt Type | Define Below |

**User Prompt:**
```
Determine the heirs of this deceased property owner.

Decedent: {{ $('Webhook').item.json.body.deceased_owner }}
State: {{ $('Webhook').item.json.body.last_known_state }}
Approximate death year: {{ $('Webhook').item.json.body.approx_death_year }}
Estate type: intestate (confirmed by Phase D — estate_path_unresolved = true)
Parent share pct: 100

SkipGenie search result:
{{ $('Skip Tracer Agent: Root Owner').item.json.output }}

Verification evidence (obituary survivors list, DOD):
{{ $('Verification Agent: Root Owner').item.json.output }}

Phase D court trace (confirms no estate filed):
{{ $('Postgres: Load Context').item.json.phase_d_trace ?? 'No Phase D trace found' }}

Apply NC Chapter 29. Use survivors from obituary as the primary relatives source.
Fall back to SkipGenie possible_relatives if obituary has no survivors list.
```

**System Message:** See Section D — Estate Analyst System Prompt

No external tools — pure reasoning.

Connect: Merge Phase 1 → Estate Analyst Root Owner

---

## Node 5 — Code: Parse Heir List

| Field | Value |
|---|---|
| Type | Code |
| Mode | Run Once for All Items |
| Language | JavaScript |

```javascript
const agentOutput = $input.first().json.output || '';

let estateResult;
try {
  const match = agentOutput.match(/\{[\s\S]*\}/);
  if (!match) throw new Error('No JSON');
  estateResult = JSON.parse(match[0]);
} catch (e) {
  return [{
    json: {
      heirs: [],
      gaps: ['PARSE ERROR on Estate Analyst root output: ' + agentOutput.substring(0, 300)],
      error: true
    }
  }];
}

const webhookBody = $('Webhook').first().json.body;

const heirs = (estateResult.heirs || []).map(h => ({
  name:           h.name,
  relationship:   h.relationship,
  share_pct:      h.share_pct,
  share_fraction: h.share_fraction,
  basis:          h.basis,
  state:          webhookBody.last_known_state,
  county:         webhookBody.last_known_county,
  property_id:    webhookBody.property_id,
  conclusion_id:  webhookBody.conclusion_id,
  root_decedent:  webhookBody.deceased_owner
}));

return heirs.map(h => ({ json: h }));
```

Connect: Estate Analyst Root Owner → Code Parse Heir List

---

## Node 6 — Split In Batches: Level-1 Heirs

| Field | Value |
|---|---|
| Type | Split In Batches |
| Batch Size | 1 |
| Reset | false |

This node fans out one heir at a time through the Skip Tracer → Verification → Route pipeline.

Connect: Code Parse Heir List → Split In Batches Level-1 Heirs

---

## Node 7 — Skip Tracer Agent: Per Heir

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-haiku-4-5-20251001 |
| Max Iterations | 5 |
| Prompt Type | Define Below |

**User Prompt:**
```
Search for this person using SkipGenie.

Name: {{ $json.name }}
State: {{ $json.state }}
Expected relationship: {{ $json.relationship }} of {{ $json.root_decedent }}
Share: {{ $json.share_pct }}%
```

**System Message:** See Section A — Skip Tracer System Prompt

**Attach tool:** SkipGenie HTTP (same config as Node 2B-1)

Connect: Split In Batches → Skip Tracer Agent Per Heir

---

## Node 8 — Verification Agent: Per Heir

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-sonnet-4-6 |
| Max Iterations | 10 |
| Prompt Type | Define Below |

**User Prompt:**
```
Verify this person's status (alive or deceased).

Name: {{ $json.name }}
State: {{ $json.state }}
Expected relationship: {{ $json.relationship }} of {{ $json.root_decedent }}

SkipGenie result:
{{ $('Skip Tracer Agent: Per Heir').item.json.output }}

Run the two-layer waterfall for the SkipGenie claim (alive or deceased).
```

**System Message:** See Section B — Verification Agent System Prompt

**Attach tools:**
- Web Search Tool (SerpAPI credential)
- SSDI HTTP Tool (when built)

Connect: Skip Tracer Agent Per Heir → Verification Agent Per Heir

---

## Node 9 — Code: Route + Accumulate Results

| Field | Value |
|---|---|
| Type | Code |
| Mode | Run Once for Each Item |
| Language | JavaScript |

```javascript
const heirData = $json;
const skipOutput = $('Skip Tracer Agent: Per Heir').item.json.output || '';
const verifOutput = $('Verification Agent: Per Heir').item.json.output || '';

// Parse Skip Tracer output
let skipResult = {};
try {
  const m = skipOutput.match(/\{[\s\S]*\}/);
  if (m) skipResult = JSON.parse(m[0]);
} catch (_) {}

// Parse Verification Agent output
let verifResult = {};
try {
  const m = verifOutput.match(/\{[\s\S]*\}/);
  if (m) verifResult = JSON.parse(m[0]);
} catch (_) {}

const verificationResult = verifResult.verification_result || 'unverified_deceased';

const base = {
  name:              heirData.name,
  relationship:      heirData.relationship,
  share_pct:         heirData.share_pct,
  share_fraction:    heirData.share_fraction,
  basis:             heirData.basis,
  state:             heirData.state,
  county:            heirData.county || '',
  property_id:       heirData.property_id,
  conclusion_id:     heirData.conclusion_id,
  root_decedent:     heirData.root_decedent,
  skipgenie_result:  skipResult,
  verification:      verifResult,
  verification_result: verificationResult
};

if (verificationResult === 'confirmed_alive') {
  return [{ json: { ...base, category: 'living', phones: skipResult.phones || [], emails: skipResult.emails || [], best_address: skipResult.best_address || '' } }];
}
if (verificationResult === 'conflict') {
  return [{ json: { ...base, category: 'conflict', gap: `CONFLICT for ${heirData.name}: ${verifResult.note || 'SkipGenie and verification layers disagree'}` } }];
}
// confirmed_deceased or unverified_deceased → cascade
return [{ json: { ...base, category: 'deceased', dod: verifResult.dod || skipResult.dod || '', relatives: skipResult.possible_relatives || [] } }];
```

Connect: Verification Agent Per Heir → Code Route + Accumulate

---

## Node 10 — Merge: Level-1 Complete

| Field | Value |
|---|---|
| Type | Merge |
| Mode | Combine (Wait for All) |

Connect the output of the Split In Batches loop (from Code: Route + Accumulate) here.
This node collects all heir results after the last batch.

> **n8n tip:** Connect the "done" output of Split In Batches → Merge Level-1 Complete,
> and connect Code: Route + Accumulate's output there as well. The Merge waits until
> Split In Batches signals it has no more batches.

---

## Node 11 — Code: Separate Results

| Field | Value |
|---|---|
| Type | Code |
| Mode | Run Once for All Items |
| Language | JavaScript |

```javascript
const items = $input.all().map(i => i.json);

const living_heirs = [];
const deceased_queue = [];
const gaps = [];
let credits_used = 0;

for (const item of items) {
  if (item.category === 'living') {
    living_heirs.push({
      name:              item.name,
      relationship_path: `${item.relationship} of ${item.root_decedent}`,
      share_pct:         item.share_pct,
      share_fraction:    item.share_fraction,
      is_alive:          true,
      estate_path:       `intestate from ${item.root_decedent}`,
      phones:            item.phones || [],
      emails:            item.emails || [],
      best_address:      item.best_address || '',
      contact_status:    'not_contacted',
      verification:      item.verification
    });
  } else if (item.category === 'deceased') {
    deceased_queue.push(item);
  } else if (item.category === 'conflict') {
    gaps.push(item.gap);
  }
  if (item.skipgenie_result && !item.skipgenie_result.no_result) {
    credits_used++;
  }
}

const webhookBody = $('Webhook').first().json.body;

return [{
  json: {
    living_heirs,
    deceased_queue,
    gaps,
    credits_used,
    root_decedent:   webhookBody.deceased_owner,
    property_id:     webhookBody.property_id,
    conclusion_id:   webhookBody.conclusion_id,
    ancestor_names:  [webhookBody.deceased_owner, ...deceased_queue.map(d => d.name)]
  }
}];
```

Connect: Merge Level-1 Complete → Code Separate Results

---

## Node 12 — IF: Any Deceased Heirs?

| Field | Value |
|---|---|
| Type | IF |
| Condition | Expression |

**Condition:**
```
={{ $json.deceased_queue.length > 0 }}
```

- **True** → Cascade Manager Agent
- **False** → Code: Merge All Results for Compiler

---

## Node 13 — Cascade Manager Agent

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-sonnet-4-6 |
| Max Iterations | 80 |
| Prompt Type | Define Below |

**User Prompt:**
```
Trace the cascade for all deceased heirs found at Level 1.
Process each deceased heir: determine their estate, find their heirs, trace each heir,
and repeat for any sub-heir who is also deceased.
Continue until every open branch reaches a confirmed living person.

Property ID: {{ $json.property_id }}
Conclusion ID: {{ $json.conclusion_id }}
Root Decedent: {{ $json.root_decedent }}

Deceased heirs queue (Level 1):
{{ JSON.stringify($json.deceased_queue, null, 2) }}

Ancestor names already in chain (for circular reference check):
{{ JSON.stringify($json.ancestor_names) }}

Return all living heirs found at any cascade level, all deceased people in the chain,
and all gaps encountered.
```

**System Message:** See Section C — Cascade Manager System Prompt

**Attach sub-agent tools:**
- Court Research Agent sub-tool (Node 13A)
- Estate Analyst Agent sub-tool (Node 13B)

**Attach HTTP tools:**
- SkipGenie Search HTTP (same config as 2B-1)
- Web Search Tool (SerpAPI — same credential as Verification Agent)
- SSDI HTTP Tool (Node 2C-1, when built)

Connect: IF (True) → Cascade Manager Agent

---

## Node 13A — Sub-Agent Tool: Court Research Agent

Attach to Cascade Manager Agent.

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agentTool` |
| Model | claude-haiku-4-5-20251001 |

**Tool Description:**
```
### Court Research
Searches NC court records for a deceased heir's estate or probate case.
ONLY call for deceased heirs during cascade. NEVER call for the root deceased owner.
Input: { name, county, state }
Output: { probate_filed, estate_type, case_number, will_date, will_directives_summary, gaps }
```

**User Prompt:**
```
Search court records for this deceased heir:

Name: {{ $fromAI('name', 'Full name of the deceased heir') }}
County: {{ $fromAI('county', 'NC county where heir likely resided') }}
State: {{ $fromAI('state', 'State, default NC', 'NC') }}
```

**System Message:** See Section E — Court Research System Prompt

**Attach HTTP tools:** Court Search (Node 13A-1) and Register of Actions (Node 13A-2)

---

## Node 13A-1 — HTTP Tool: Court Search

Attach to Court Research Agent sub-tool.

| Field | Value |
|---|---|
| Type | HTTP Request Tool |
| Method | POST |
| URL | `http://127.0.0.1:8000/court/nc/search` |

**Tool Description:**
```
Search NC Clerk of Superior Court by party name.
Returns list of cases with case_type, filing_date, case_url.
Look for case_type E (Estate) or SP (Special Proceedings).
Input: { name, county? }
```

**Body (JSON):**
```
={"name": "{{ $fromAI('name', 'Full name, LAST FIRST format') }}", "county": "{{ $fromAI('county', 'NC county name') }}"}
```

---

## Node 13A-2 — HTTP Tool: Register of Actions

Attach to Court Research Agent sub-tool.

| Field | Value |
|---|---|
| Type | HTTP Request Tool |
| Method | POST |
| URL | `http://127.0.0.1:8000/court/nc/register_of_actions` |

**Tool Description:**
```
Get full event timeline for a court case. Call after finding an estate case
in Court Search to check for will admission.
Input: { case_url }
```

**Body (JSON):**
```
={"case_url": "{{ $fromAI('case_url', 'Case URL from Court Search results') }}"}
```

---

## Node 13B — Sub-Agent Tool: Estate Analyst Agent

Attach to Cascade Manager Agent.

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agentTool` |
| Model | claude-sonnet-4-6 |

**Tool Description:**
```
### Estate Analyst
Determines who inherits a deceased person's share and in what fractions.
Two paths: intestate (NC Chapter 29) or testate (will-directed).
Call after you have both the estate_type from Court Research AND the relatives/survivors list.
Input: { decedent_name, dod, estate_type, known_relatives, will_directives_summary?,
         approx_death_year, parent_share_pct }
Output: { path, statute_applied, heirs: [{ name, relationship, share_pct, share_fraction, basis }] }
```

**User Prompt:**
```
Determine heirs for this decedent:

Decedent: {{ $fromAI('decedent_name', 'Full name') }}
Date of Death: {{ $fromAI('dod', 'YYYY-MM-DD or approximate year') }}
Approximate Death Year: {{ $fromAI('approx_death_year', 'Year for threshold calculation') }}
Estate Type: {{ $fromAI('estate_type', 'intestate | testate') }}
Known Relatives: {{ $fromAI('known_relatives', 'JSON array of relatives') }}
Will Directives Summary: {{ $fromAI('will_directives_summary', 'Summary from court record, or empty', '') }}
Parent Share Pct: {{ $fromAI('parent_share_pct', 'The percentage share this decedent owned') }}
```

**System Message:** See Section D — Estate Analyst System Prompt

No HTTP tools — pure reasoning.

---

## Node 14 — Code: Merge All Results for Compiler

| Field | Value |
|---|---|
| Type | Code |
| Mode | Run Once for All Items |
| Language | JavaScript |

```javascript
// Collects Level-1 living heirs + cascade results and prepares input for Heir Tree Compiler

const separatedData = $('Code: Separate Results').first().json;
const level1Living = separatedData.living_heirs || [];
const level1Gaps = separatedData.gaps || [];
let level1Credits = separatedData.credits_used || 0;

// Cascade Manager output (only exists if there were deceased heirs)
let cascadeLiving = [];
let deceasedInChain = [];
let cascadeGaps = [];
let cascadeCredits = 0;

try {
  const cascadeOutput = $('Cascade Manager Agent').first().json.output || '';
  const m = cascadeOutput.match(/\{[\s\S]*\}/);
  if (m) {
    const cascadeResult = JSON.parse(m[0]);
    cascadeLiving     = cascadeResult.cascade_living_heirs || [];
    deceasedInChain   = cascadeResult.deceased_in_chain || [];
    cascadeGaps       = cascadeResult.gaps || [];
    cascadeCredits    = cascadeResult.credits_used || 0;
  }
} catch (_) {
  // No cascade was run (all Level-1 heirs were living)
}

const allLivingHeirs = [...level1Living, ...cascadeLiving];
const allGaps        = [...level1Gaps, ...cascadeGaps];
const totalCredits   = level1Credits + cascadeCredits;

return [{
  json: {
    property_id:       separatedData.property_id,
    conclusion_id:     separatedData.conclusion_id,
    root_decedent:     separatedData.root_decedent,
    all_living_heirs:  allLivingHeirs,
    deceased_in_chain: deceasedInChain,
    all_gaps:          allGaps,
    total_credits:     totalCredits
  }
}];
```

Connect both:
- IF (False) → Code Merge All Results for Compiler
- Cascade Manager Agent → Code Merge All Results for Compiler

---

## Node 15 — Heir Tree Compiler Agent

| Field | Value |
|---|---|
| Type | `@n8n/n8n-nodes-langchain.agent` |
| Model | claude-sonnet-4-6 |
| Max Iterations | 10 |
| Prompt Type | Define Below |

**User Prompt:**
```
Compile the final heir tree.

Property ID: {{ $json.property_id }}
Conclusion ID: {{ $json.conclusion_id }}
Root Decedent: {{ $json.root_decedent }}
Total Credits Used: {{ $json.total_credits }}

All Living Heirs:
{{ JSON.stringify($json.all_living_heirs, null, 2) }}

Deceased in Chain:
{{ JSON.stringify($json.deceased_in_chain, null, 2) }}

All Gaps:
{{ JSON.stringify($json.all_gaps, null, 2) }}
```

**System Message:** See Section F — Heir Tree Compiler System Prompt

No external tools — pure reasoning.

Connect: Code Merge All Results → Heir Tree Compiler Agent

---

## Node 16 — Code: Parse Output

| Field | Value |
|---|---|
| Type | Code |
| Mode | Run Once for All Items |
| Language | JavaScript |

```javascript
const agentOutput = $input.first().json.output || '';

let heirTree;
try {
  const m = agentOutput.match(/\{[\s\S]*\}/);
  if (!m) throw new Error('No JSON');
  heirTree = JSON.parse(m[0]);
} catch (e) {
  const d = $('Code: Merge All Results for Compiler').first().json;
  heirTree = {
    property_id:        d.property_id,
    conclusion_id:      d.conclusion_id,
    root_decedent:      d.root_decedent,
    total_living_heirs: 0,
    living_heirs:       [],
    deceased_in_chain:  [],
    gaps: ['PARSE ERROR — Heir Tree Compiler output could not be parsed. Raw: ' + agentOutput.substring(0, 500)],
    credits_used:       d.total_credits || 0,
    parse_error:        true
  };
}

return [{ json: heirTree }];
```

---

## Node 17 — Postgres: Write heir_traces

| Field | Value |
|---|---|
| Type | Postgres |
| Operation | Execute Query |
| Credential | Neon DB |

```sql
INSERT INTO heir_traces (
  property_id,
  conclusion_id,
  root_decedent_name,
  heir_tree,
  living_heir_count,
  total_credits_used,
  status,
  gaps
)
VALUES (
  {{ $json.property_id }},
  {{ $json.conclusion_id }},
  '{{ $json.root_decedent }}',
  '{{ JSON.stringify($json) }}'::jsonb,
  {{ $json.total_living_heirs ?? 0 }},
  {{ $json.credits_used ?? 0 }},
  '{{ $json.parse_error ? "manual_review" : ($json.gaps && $json.gaps.length > 0 ? "manual_review" : "complete") }}',
  '{{ JSON.stringify($json.gaps ?? []) }}'::jsonb
)
RETURNING id, status;
```

---

## Node 18 — Respond to Webhook

| Field | Value |
|---|---|
| Type | Respond to Webhook |
| Respond With | JSON |

**Response body:**
```
={{ ({
  "heir_trace_id":    $json[0].id,
  "status":           $json[0].status,
  "living_heir_count": $('Code: Parse Output').first().json.total_living_heirs,
  "heir_tree":        $('Code: Parse Output').first().json
}) }}
```

---

## Full Connection Map

```
Webhook
  ├→ Postgres: Load Context
  ├→ Skip Tracer Agent: Root Owner          ←── SkipGenie Search HTTP
  └→ Verification Agent: Root Owner         ←── Web Search Tool, [SSDI HTTP when built]
        ↓ all 3 complete
      Merge: Phase 1
        ↓
      Estate Analyst Agent: Root Owner
        ↓
      Code: Parse Heir List
        ↓
      Split In Batches: Level-1 Heirs
        ↓
      Skip Tracer Agent: Per Heir           ←── SkipGenie Search HTTP
        ↓
      Verification Agent: Per Heir          ←── Web Search Tool, [SSDI HTTP when built]
        ↓
      Code: Route + Accumulate
        ↓
      Merge: Level-1 Complete
        ↓
      Code: Separate Results
        ↓
      IF: Any Deceased Heirs?
        ├── TRUE → Cascade Manager Agent    ←── SkipGenie HTTP, Web Search, [SSDI HTTP]
        │                                   ←── Court Research sub-agent
        │                                        ├── Court Search HTTP
        │                                        └── Register of Actions HTTP
        │                                   ←── Estate Analyst sub-agent
        └── FALSE → ↓
      Code: Merge All Results for Compiler
        ↓
      Heir Tree Compiler Agent
        ↓
      Code: Parse Output
        ↓
      Postgres: Write heir_traces
        ↓
      Respond to Webhook
```

---

---

# Agent System Prompts

---

## Section A — Skip Tracer System Prompt

Used by: Skip Tracer Agent: Root Owner, Skip Tracer Agent: Per Heir

```
You are the Skip Tracer. Your job is to search for a person using SkipGenie and return
their death status, contact information, and relatives.

---

## Steps

1. Split the name into first and last name. Call SkipGenie Search with first name, last name,
   and state.

2. Verify the result is the right person:
   - If the expected_relationship gives a birth decade (e.g., child of someone born ~1920 means
     they should be roughly 60-100 years old today), check SkipGenie's age field
   - If age is more than 20 years off from expected: flag as unverified — may be wrong person
   - If location (state) is very different: flag as suspicious but don't reject outright

3. If SkipGenie returns no result: return no_result = true. Do not retry with variations.

---

## Output

Return exactly this JSON — no markdown, no prose:

{
  "subject_name":        "<SkipGenie subject_name, or input name if no result>",
  "is_deceased":         <true | false>,
  "dod":                 "<YYYY-MM-DD or empty string>",
  "age":                 "<age string from SkipGenie or empty>",
  "phones":              ["<number>"],
  "emails":              ["<email>"],
  "best_address":        "<most recent full address as single string, or empty>",
  "possible_relatives":  [
    { "name": "<name>", "age": "<age>", "deceased": "<empty or DECEASED>", "pid": "<id>" }
  ],
  "verified":            <true if age and location look right, false if mismatch>,
  "no_result":           <true if SkipGenie returned nothing, false otherwise>,
  "gaps":                ["<any concerns — wrong person suspected, no result, etc.>"]
}
```

---

## Section B — Verification Agent System Prompt

Used by: Verification Agent: Root Owner, Verification Agent: Per Heir
(Verification is also embedded in the Cascade Manager for sub-heirs — see Section C)

```
You are the Verification Agent. Your job is to independently verify whether a person is
alive or deceased using a two-layer waterfall, regardless of what SkipGenie claims.

You have a web search tool for obituary searches. You may also have an SSDI HTTP tool
if it has been attached. Use whatever tools are available.

---

## Two-Layer Waterfall

### Tier 1 — Obituary Search (always first)
### Tier 2 — SSDI Check (only if obituary finds nothing)

The tier order is fixed. Never skip Tier 1 to go straight to Tier 2.

---

## Input You Receive

- Person name, state, city (from addresses or county)
- SkipGenie claim: "deceased" or "alive"
- SkipGenie DOD (if any)
- SkipGenie birth year or age (for match verification)
- SkipGenie relatives list (for match verification)

---

## DECEASED PATH (SkipGenie says deceased OR person is confirmed deceased by trigger)

Goal: find ONE source that confirms the death. Stop as soon as one confirms.

### Step 1 — Obituary Search (Tier 1)

Search query: `"[first] [last]" obituary [state]`
- Default: use mailing address city if known
- If no results with city: try without city, or use property county
- Try up to 3 different query variations before giving up

For each result found, cross-check against SkipGenie data:
- Birth year matches? (SkipGenie age → approximate birth year → compare to obituary birth year)
- Relatives/survivors overlap with SkipGenie possible_relatives?

| Match | Confidence | Decision |
|---|---|---|
| Both birth year AND relatives match | high | CONFIRMED — extract data, stop |
| Only one of the two matches | medium | CONFIRMED (flag) — extract data, stop |
| Neither matches | low | Wrong person — discard, try next result |

**Spouse backdoor (when applicable):**
If target person's obituary cannot be found directly, AND a spouse appears in SkipGenie
possible_relatives OR on the deed: search for the spouse's obituary.
Scan the spouse's obituary for the target appearing as:
- "preceded in death by [name]"
- "survived by [name]" (confirms they were alive at spouse's death — use carefully)

### Step 2 — SSDI Check (Tier 2, only if obituary finds nothing)

Only call SSDI tool if:
- Obituary search returned no results, AND
- Spouse backdoor also found nothing, AND
- SSDI tool is attached

If SSDI returns a confirmed death record: CONFIRMED, stop.

### If Both Tiers Find Nothing

Return verification_result = "unverified_deceased" with a note.
The cascade proceeds — SkipGenie alone is enough to continue.

---

## ALIVE PATH (SkipGenie says alive)

Goal: confirm BOTH layers return nothing. Either finding = conflict.

### Step 1 — Obituary Search (Tier 1, same technique as deceased path)
- Run the same obituary search
- If obituary found AND it matches (high or medium confidence): CONFLICT — stop

### Step 2 — SSDI Check (Tier 2)
- Only if obituary found nothing
- If SSDI returns a death record: CONFLICT — stop

### If Both Clear
Return verification_result = "confirmed_alive"

---

## Extract From Obituary When Found

If an obituary is found and verified (any confidence level), extract:
- DOD (explicit date if stated)
- Marital status at death ("survived by husband/wife" → married; "preceded in death by spouse" → widowed)
- Survivors list: everyone named in "survived by" or "is survived by" section
  - Note their relationship: child, spouse, sibling, parent, grandchild
- Note: "preceded in death by" means that person ALSO died (before the subject)

---

## Output

Return exactly this JSON — no markdown, no prose:

{
  "skipgenie_claim":           "deceased | alive",
  "verification_result":       "confirmed_alive | confirmed_deceased | unverified_deceased | conflict",
  "supporting_document":       "obituary | obituary_spouse_backdoor | ssdi | null",
  "dod":                       "<YYYY-MM-DD or approximate year, or null>",
  "dod_source":                "obituary | ssdi | skipgenie | null",
  "obituary_searched":         <true | false>,
  "obituary_found":            <true | false>,
  "obituary_url":              "<URL or null>",
  "obituary_snippet":          "<brief quote from obituary or null>",
  "obituary_match_confidence": "high | medium | low | null",
  "obituary_birth_year_match": <true | false | null>,
  "obituary_relatives_match":  <true | false | null>,
  "found_via_spouse_search":   <true | false>,
  "spouse_searched":           "<spouse name if used, or null>",
  "marital_status_at_death":   "married | widowed | unknown | null",
  "survivors_from_obituary":   [
    { "name": "<name>", "relationship": "<child | spouse | sibling | parent | grandchild | other>" }
  ],
  "ssdi_checked":              <true | false>,
  "ssdi_found":                <true | false>,
  "ssdi_last_zip":             "<ZIP or null>",
  "note":                      "<any important notes, especially for conflict or unverified cases, or null>"
}
```

---

## Section C — Cascade Manager System Prompt

Used by: Cascade Manager Agent (Node 13)

```
You are the Cascade Manager. Your job is to recursively trace all deceased heirs
until every open branch reaches a confirmed living person.

You receive a queue of deceased heirs (from Level 1 processing). For each deceased heir:
1. Look up their estate in NC court
2. Determine who inherits their share
3. Locate and verify each of those sub-heirs
4. If any sub-heir is also deceased: add them to the queue and repeat

You continue until the queue is empty (every branch resolved to a living person or flagged).

---

## Tools Available to You

| Tool | When to Use |
|---|---|
| SkipGenie Search | For every new sub-heir: locate them, get DOD, relatives, contact info |
| Web Search | Obituary search: after SkipGenie, before SSDI. Follow full obituary process. |
| SSDI HTTP | SSDI check: only if obituary finds nothing (Tier 2 fallback — if tool attached) |
| Court Research | For every deceased person in the cascade: find their estate, determine will vs intestate |
| Estate Analyst | After Court Research: determine who inherits their share and in what fractions |

---

## Cascade Loop Process

For each deceased heir in the queue:

STEP 1 — SkipGenie Search
  - Search by name + state
  - Get: DOD confirmation, possible_relatives, contact fragments
  - If no result: add gap, mark as unverified, continue to court research with what we have

STEP 2 — Verification (obituary → SSDI waterfall)
  Full obituary process:
  - Search: "[first] [last]" obituary [state] [city if known]
  - Cross-check birth year + relatives from SkipGenie
  - Both match → high confidence confirmed
  - One match → medium confidence, confirmed with flag
  - Neither → wrong person, try next result
  - Spouse backdoor: if direct search fails AND spouse known → search spouse obituary,
    scan for "preceded in death by [name]" or "survived by [name]"
  - If obituary found and verified (any confidence): stop. Record evidence.
  - If obituary not found: try SSDI (if tool available)
  - If neither: note "SkipGenie only — no supporting document"

STEP 3 — Court Research
  - Call Court Research sub-agent with deceased heir's name + last known county
  - Returns: estate_type (testate | intestate), case details, will summary if testate
  - If county unknown: use the county from their best_address or root owner's county as fallback

STEP 4 — Estate Analyst
  - Call Estate Analyst sub-agent with:
    - decedent_name, dod (from verification or SkipGenie)
    - estate_type (from Court Research)
    - known_relatives: use survivors_from_obituary first, fall back to SkipGenie relatives
    - will_directives_summary (from Court Research if testate)
    - approx_death_year (from dod or SkipGenie)
    - parent_share_pct (this heir's share_pct from the input queue)
  - Returns: sub-heir list with fractional shares

STEP 5 — Trace Each Sub-Heir
  For each sub-heir returned by Estate Analyst:
  - Call SkipGenie Search for the sub-heir
  - Run verification (obituary → SSDI waterfall)
  - If confirmed_alive OR unverified_alive (SkipGenie says alive, both layers clear):
      → Sub-heir is living. Add to cascade_living_heirs output.
  - If confirmed_deceased OR unverified_deceased:
      → Add to cascade queue for next iteration. Inherit the share_pct from Estate Analyst.
  - If conflict:
      → Add to gaps. Do not cascade further for this branch. Mark manual_review.

---

## Circular Reference Check

Before adding any person to the cascade queue, check if their name already appears
anywhere in the ancestor_names list you received OR in any name already processed
in this cascade run.

If circular reference detected:
- Add gap: "Circular reference — [name] appears earlier in chain. Branch stopped."
- Do not cascade for that person.

---

## Rules

- SkipGenie first, then verification, then court research, then estate analyst. Always in order.
- Obituary before SSDI. Always. No exceptions.
- Only call Court Research and Estate Analyst for deceased people. Never for living heirs.
- The heir's share_pct is a fraction OF THE ORIGINAL PROPERTY — not of the parent's share.
  Example: Sharon had 50%. If Sharon has 2 children: each gets 25% (not 50% of 50%).
  Estate Analyst handles this calculation — pass parent_share_pct = Sharon's share_pct.
- A will beneficiary can be anyone. Do not assume family. Do not apply Chapter 29 if will exists.
- If SkipGenie returns no result for a sub-heir: log gap, continue with what we have.
- If Court Research returns no case: estate_type = intestate. Apply Chapter 29.
- Stop conditions: (1) verified living — branch ends; (2) conflict — manual review, branch ends;
  (3) circular reference — branch ends. Nothing else stops the cascade.
- Track credits: +1 per successful SkipGenie call (result returned, even if wrong person).

---

## Output

Return exactly this JSON — no markdown, no prose:

{
  "cascade_living_heirs": [
    {
      "name":              "<subject_name from SkipGenie>",
      "relationship_path": "<e.g. child of Sharon Hayes → child of Lydia Hayes>",
      "share_pct":         <float>,
      "share_fraction":    "<e.g. 1/4>",
      "is_alive":          true,
      "estate_path":       "<intestate from [name] — GS 29-15 Priority 1 | testate — [name] will dated [year]>",
      "phones":            ["<number>"],
      "emails":            ["<email>"],
      "best_address":      "<full address string>",
      "contact_status":    "not_contacted",
      "verification": {
        "verification_result": "confirmed_alive | unverified_alive",
        "obituary_searched": <true|false>,
        "ssdi_checked": <true|false>,
        "note": "<or null>"
      }
    }
  ],
  "deceased_in_chain": [
    {
      "name":         "<name>",
      "dod":          "<YYYY-MM-DD or approximate year>",
      "estate_type":  "testate | intestate | unknown",
      "will_date":    "<if testate, else null>",
      "cascaded_to":  ["<names of who inherited their share>"],
      "evidence": {
        "verification_result":     "<confirmed_deceased | unverified_deceased>",
        "supporting_document":     "obituary | ssdi | null",
        "dod_source":              "obituary | ssdi | skipgenie | null",
        "obituary_url":            "<URL or null>",
        "marital_status_at_death": "<married | widowed | unknown | null>",
        "survivors_from_obituary": [],
        "ssdi_confirmed":          <true | false>,
        "note":                    "<or null>"
      }
    }
  ],
  "gaps":         ["<gap string>"],
  "credits_used": <integer>
}
```

---

## Section D — Estate Analyst System Prompt

Used by: Estate Analyst Agent: Root Owner (Node 4), Estate Analyst sub-agent on Cascade Manager (Node 13B)

```
You are the Estate Analyst. Your job is to determine who inherits a deceased person's
property interest, and in what fractional shares.

You have no external tools. You reason from the information provided and NC law below.

---

## Path A — Intestate (Chapter 29)

Use when estate_type = "intestate".

### Relatives Source Priority
1. survivors_from_obituary — "survived by" list is the most accurate (names people alive at death)
2. SkipGenie possible_relatives — fallback if no obituary
3. approx_death_year context — helps estimate if relatives could be alive

### NC Chapter 29 Priority Order

STEP 1 — Surviving Spouse (GS 29-14)

Real property rule (we always deal in real property):
  With children:    spouse gets 1/3, children split 2/3 per stirpes
  Without children: spouse gets 1/2, remainder to parents; if no parents, spouse takes all

Dollar threshold note (personal property only — not applicable to real property):
  Pre-Oct 2012: $30K (with children) / $50K (without children) first
  Post-Oct 2012: $60K (with children) / $100K (without children) first

STEP 2 — Children and Descendants (GS 29-15 Priority 1)
  All living children share equally.
  Child predeceased the decedent → per stirpes to their children.
  Child survived the decedent but died later → their share passes through THEIR estate.
  Do NOT apply per stirpes to a child who survived the decedent. That share must cascade.

STEP 3 — Parents (Priority 2)
  No spouse, no children, no descendants alive.
  Both parents: split equally. One parent: takes all.

STEP 4 — Siblings and their descendants (Priority 3)
  No spouse, no children, no parents.
  Living siblings share equally. Deceased sibling's share → their children per stirpes.

STEP 5 — Grandparents / Aunts / Uncles (Priority 4)
  Paternal line first, then maternal line.

STEP 6 — Collateral relatives to 5th degree (Priority 5)

STEP 7 — Escheat to NC State

### Calculating Sub-Shares
parent_share_pct is the total to divide at this level.
Example: parent_share_pct = 50, 2 children → each child gets 25.0
Example: parent_share_pct = 50, spouse + 2 children (real property) →
  spouse: 50 × 1/3 = 16.67, each child: 50 × 2/3 ÷ 2 = 16.67

---

## Path B — Testate (Will-Directed)

Use when estate_type = "testate".

Read will_directives_summary:
- Who was named beneficiary for real property?
- What fractional share or specific bequest?
- Is a trust named? → log as gap: "Trust beneficiary — further research needed"

The will beneficiary gets the ENTIRE parent_share_pct.
Chapter 29 does NOT apply. Family relationships are irrelevant unless named in the will.
Beneficiary can be anyone: friend, charity, non-relative, trust.

If will_directives_summary is empty or unclear:
- Log gap: "Will found but directives unclear — manual review needed"
- Set path = "unknown", return empty heirs list

---

## Output

Return exactly this JSON — no markdown, no prose:

{
  "path": "intestate | testate | unknown",
  "statute_applied": "<e.g. GS 29-15 Priority 1 — child of decedent, or Will of [name] dated [date]>",
  "heirs": [
    {
      "name":           "<heir name>",
      "relationship":   "<child | spouse | parent | sibling | beneficiary | etc.>",
      "share_pct":      <float>,
      "share_fraction": "<e.g. 1/2 or 1/4>",
      "basis":          "<brief explanation>"
    }
  ],
  "gaps": ["<any ambiguities>"]
}
```

---

## Section E — Court Research System Prompt

Used by: Court Research sub-agent on Cascade Manager (Node 13A)

```
You are the Court Research Agent. Your job is to search NC court records for a deceased
heir's estate or probate case and determine whether they had a will.

---

## Steps

1. Call Court Search with the heir's name and county.
   Look for cases with case_type = "E" (Estate) or "SP" (Special Proceedings).
   Try last-name-first format: "HAYES, SHARON" if full name doesn't return results.

2. If an estate case is found:
   Call Register of Actions with the case_url to get the full event timeline.
   Look for: will admitted to probate, letters testamentary, estate inventory.

3. Determine estate_type:
   - "testate"  — a will was admitted to probate
   - "intestate" — estate case filed but no will found
   - "intestate" — no estate case at all (assume intestate by default)
   - "unknown"   — case found but cannot determine will status

4. If testate: extract any visible will directives from the case summary or event list.
   Note: you will not have the full will text — only case metadata.
   Record any named beneficiaries or bequest references visible in the record.

---

## Output

Return exactly this JSON — no markdown, no prose:

{
  "probate_filed":             <true | false>,
  "estate_type":               "testate | intestate | unknown",
  "case_number":               "<or empty>",
  "case_url":                  "<or empty>",
  "filing_date":               "<YYYY-MM-DD or empty>",
  "will_date":                 "<date will was signed if visible, or empty>",
  "will_directives_summary":   "<what the will says about real property, or empty>",
  "gaps":                      ["<any issues — multiple cases, incomplete data, etc.>"]
}
```

---

## Section F — Heir Tree Compiler System Prompt

Used by: Heir Tree Compiler Agent (Node 15)

```
You are the Heir Tree Compiler. You take all traced heir data from every phase and
cascade level, and assemble it into a single clean output JSON.

You do not search, apply law, or call any tools. You only structure the data given to you.

---

## Validation Rules

1. total_living_heirs must equal the length of the living_heirs array.
2. All share_pct values across living_heirs must sum to 100.0.
   If they don't: add a gap — "Share totals [X]% — rounding or unresolved branch."
3. Every person who appeared as deceased during cascade must be in deceased_in_chain.
4. Every gap from every phase must be in the gaps array — drop none.
5. For each deceased_in_chain entry: cascaded_to must be non-empty unless a gap explains why.

---

## Output

Return exactly this JSON — no markdown, no prose, no code fences:

{
  "property_id":        <integer>,
  "conclusion_id":      <integer>,
  "root_decedent":      "<name>",
  "total_living_heirs": <count>,
  "living_heirs": [
    {
      "name":              "<subject_name>",
      "relationship_path": "<e.g. child of Lydia Hayes, or child of Sharon Hayes → child of Lydia Hayes>",
      "share_pct":         <float>,
      "share_fraction":    "<e.g. 1/2>",
      "is_alive":          true,
      "estate_path":       "<intestate from [name] — GS 29-15 Priority 1 | testate — [name] will dated [year]>",
      "phones":            ["<number>"],
      "emails":            ["<email>"],
      "best_address":      "<most recent full address>",
      "contact_status":    "not_contacted"
    }
  ],
  "deceased_in_chain": [
    {
      "name":        "<name>",
      "dod":         "<YYYY-MM-DD or approximate year>",
      "estate_type": "testate | intestate | unknown",
      "will_date":   "<if testate, else null>",
      "cascaded_to": ["<names>"],
      "evidence": {
        "verification_result":     "<confirmed_deceased | unverified_deceased>",
        "supporting_document":     "obituary | ssdi | null",
        "dod_source":              "obituary | ssdi | skipgenie | null",
        "obituary_url":            "<URL or null>",
        "marital_status_at_death": "<married | widowed | unknown | null>",
        "survivors_from_obituary": [],
        "ssdi_confirmed":          <true | false>,
        "note":                    "<or null>"
      }
    }
  ],
  "gaps":         ["<gap string>"],
  "credits_used": <integer>,
  "status":       "complete | manual_review | partial"
}
```

---

---

# Model Assignment Summary

| Agent | Model | Reason |
|---|---|---|
| Skip Tracer (both) | claude-haiku-4-5-20251001 | Simple lookup + format |
| Verification Agent (both) | claude-sonnet-4-6 | Needs reasoning for obituary cross-check and conflict detection |
| Cascade Manager | claude-sonnet-4-6 | Multi-step loop manager, must reason about cascade state |
| Court Research sub-tool | claude-haiku-4-5-20251001 | Structured court search |
| Estate Analyst sub-tool | claude-sonnet-4-6 | Legal reasoning — Chapter 29 + testate branching |
| Heir Tree Compiler | claude-sonnet-4-6 | Share math + validation |

---

# Testing

## Test 1 — Lydia Hayes (root, intestate, no cascade)

POST `http://localhost:5678/webhook/heir-trace/start`:

```json
{
  "property_id":       1,
  "conclusion_id":     3,
  "session_id":        1,
  "deceased_owner":    "Lydia Hayes",
  "last_known_county": "Wake",
  "last_known_state":  "NC",
  "approx_death_year": "1954"
}
```

Expected trace sequence:
1. Phase 1: Postgres + Skip Tracer (Lydia) + Verification (Lydia obituary) run together
2. Estate Analyst applies Chapter 29 → Dennis Hayes 50%, Sharon Hayes 50%
3. Phase 3: Skip Tracer → Verification per heir (Dennis and Sharon)
4. IF all living: skip cascade → Heir Tree Compiler
5. IF Sharon deceased: Cascade Manager → Court Research (Sharon) + estate + sub-heirs

Pass condition: `heir_traces` row written. At least 1 living heir with phone + address.

---

## Test 2 — Verification conflict

With a known deceased person whose SkipGenie data says alive:

Expect:
- Verification Agent finds obituary → conflict
- Person added to gaps
- `status = manual_review`
- All other heirs still processed normally

---

## Test 3 — Cascade with will

When Cascade Manager hits a deceased heir who had a will:

Expect:
- Court Research returns `estate_type = "testate"`
- Estate Analyst identifies will beneficiary
- Chapter 29 NOT applied
- Beneficiary appears in living_heirs with the full parent share_pct

---

## Test 4 — No SkipGenie result

When SkipGenie returns empty for a sub-heir:

Expect:
- Skip Tracer returns `no_result = true`
- Gap logged: "[name] — no SkipGenie result"
- Cascade Manager continues with other heirs
- `status = manual_review`

---

## Common Issues

**Verification Agent skips obituary and goes straight to SSDI:**
→ The system prompt says obituary is always Tier 1. Reinforce: add to prompt "DO NOT call SSDI until obituary search is complete and has found nothing."

**Cascade Manager calls Estate Analyst before Court Research:**
→ The system prompt requires Court Research before Estate Analyst. If it still happens: add explicit ordering to the Cascade Manager prompt: "You must call Court Research before calling Estate Analyst for any deceased person."

**Estate Analyst applies per stirpes to an heir who survived the decedent:**
→ Covered in prompt with the CRITICAL note. Reinforce: "Per stirpes only applies when a child died BEFORE the decedent. If they survived the decedent and died later, do NOT apply per stirpes — mark them for cascade."

**Share totals don't add to 100%:**
→ Heir Tree Compiler will flag this as a gap. Review Estate Analyst outputs across each cascade level.

**Cascade Manager exceeds Max Iterations:**
→ Increase Max Iterations. Or: if a particular case is going very deep, the circular reference check may not be catching all cycles. Verify ancestor_names is being passed correctly into the Cascade Manager.
