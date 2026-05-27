# Heir Tracer — New Orchestrator Design

> **Status:** Proposed. Replaces all nodes from Branch Planner through Genealogist with a
> single Heir Research Orchestrator agent + the existing Root Owner Research.

---

## Core Insight

The current system is a **conveyor belt**: each agent does one fixed job and passes the result
to the next. The problem is that research is not linear. Finding an obituary changes what
SkipGenie searches make sense. Finding a probate document changes whether an obituary is
even needed. Finding one sibling's voter record reveals a married name that unlocks a
different Ancestry search.

The new design is an **orchestrator with a goal**: given a person to research, figure out
their vital status, whether they left an estate, and who their heirs are. Use whatever tools
are needed, in whatever order makes sense given what you've learned so far.

---

## What Stays the Same

- **Root Owner Research** — already works correctly. No changes.
- **All backend tools** — SkipGenie, NC Voter, Ancestry, Brave Search, Court Search, ROA,
  Court Document Pull, all DB write endpoints — stay exactly as they are.
- **Database schema** — no changes to `heir_research_persons`, `heir_research_queue`,
  `heir_court_findings`, `heir_ancestry_records`, `heir_voter_records`.
- **`/heir/write-court-findings`**, **`/heir/upsert-person`**, **`/heir/queue-persons`** endpoints
  stay the same.

---

## What Changes

Everything between **Write Root Person** and the final output is replaced by one orchestrator.

| Old | New |
|-----|-----|
| Branch Planner (seeds queue) | Orchestrator decides who to research and in what order |
| Worker webhook + loop | Orchestrator loops internally per person |
| SG Analyzer | Tool call inside Orchestrator |
| Vital Status Researcher | Tool call inside Orchestrator |
| Obituary Deep Diver | Tool call inside Orchestrator |
| Surname Crosser | Tool call inside Orchestrator |
| Title Attorney | Tool call inside Orchestrator |
| Person Compiler | Orchestrator synthesizes and writes |
| Branch Decision | Orchestrator decides and queues |
| Family Assembler | Orchestrator reads all accumulated data |
| Intestate Expert | Orchestrator applies NC Ch. 29 |
| Genealogist | Orchestrator writes final tree |
| ~8 JS parse nodes | Eliminated — orchestrator reasons natively |

---

## Architecture

```
Webhook
  └─ Create Session
       └─ Root Owner Research  (unchanged)
            │
            └─ Write Root Person  (unchanged)
                 │
                 └─ Trigger Orchestrator Webhook
                          │
                          ▼
              ┌── Orchestrator Webhook ──────────────────────────┐
              │   (receives: person_name, session_id,             │
              │    property_id, county)                           │
              │                                                   │
              │   Heir Research Orchestrator (Agent)              │
              │     ├── [tools: SkipGenie, Voter, Ancestry,      │
              │     │    Brave, Deeds, all DB reads/writes]       │
              │     └── Court Researcher (sub-agent)              │
              │           ├── Court Search (name variants)        │
              │           ├── Register of Actions                 │
              │           └── Court Document Pull                 │
              │                                                   │
              │   → Write Person (final)                          │
              │   → Queue Persons (new discoveries)               │
              │   → Mark Person Done                              │
              │                                                   │
              │   If queue has more → Self Trigger (loop back) ──┘
              │   If queue empty    → Trigger Family Assembly
              └──────────────────────────────────────────────────

              Family Assembly  (lightweight — no research, just synthesis)
                └─ Load Family Dataset
                └─ Apply NC Ch. 29
                └─ Write Family Tree
```

---

## The Orchestrator Agent

### Identity

> You are the Heir Research Orchestrator. Your job is to determine the complete legal heir
> list for a deceased NC property owner and write that result to the database.

### Goal (not a sequence — an outcome)

Each invocation receives **one person** to research. For that person, determine:
1. **`vital_status`** — are they living or deceased?
2. **`estate_filed`** — did they file a probate in NC courts?
3. **`cascade_needed`** — do we need to find their heirs (because they died without a filed estate)?
4. **`cascade_relatives`** — who are their heirs if cascade is needed?

One invocation = one person. New persons discovered during research (children from an obit,
beneficiaries from a probate) are written to the DB queue and picked up by the next invocation.
The Orchestrator does not loop across persons — it loops within a single person's research.

---

### Reasoning Loop (per person)

The Orchestrator does not follow a fixed sequence. It reasons at each step: **"What do I
know? What am I still missing? What is the most useful thing to look up next?"**

Typical pattern for a deceased child:

```
1. What do I know about this person?
   → SkipGenie (name + county) — get matched identity, address, family context

2. Are they alive or dead?
   → NC Voter lookup — Active voter = living (high confidence)
   → If voter is Removed or not found → check SSDI (Ancestry collection 2442)
   → If SSDI confirms death → deceased. If not → check obituaries.

3. Did they leave a probate?
   → Call Court Researcher sub-agent (name + county)
   → Sub-agent handles all Court Search variants, ROA, and Document Pull internally
   → Returns: {estate_filed, had_will, named_persons[], case_number, case_url}
   → If estate_filed=true with named_persons → cascade_needed = false, use those heirs.

4. If no estate, find their heirs via obituary:
   → Ancestry Search (collection 61843) — obituary with children listed
   → Ancestry Record (detail page) — canonical full-name children list
   → Brave Search — public obituary text
   → If obit found → extract survivors. These are the authoritative heir list.

5. If obit names children not yet in the queue:
   → Call Queue Persons with each new name, relationship_hint, and maiden_name if known.
   → They will be picked up by the next Orchestrator invocation. Do not research them now.

6. If I still don't know who the heirs are:
   → Ancestry parent-mode search (mother/father = this person's name)
   → Census search (collection 2442) — 1940 household
   → Surname Crosser pattern: try Ancestry with last_name = root surname,
     look for children[] entries that name this person as parent.

7. Synthesize and hand off:
   → Write Person final record (vital_status, estate_filed, had_will, cascade_needed, cascade_relatives)
   → Write Court Findings if any estate was found (if not already written during step 3)
   → Queue Persons for any children/heirs not yet in the queue
   → Done — n8n marks this person done and self-triggers the webhook for the next queue item
```

### Key Behavioral Rules

**SkipGenie is for identity confirmation, not heir discovery. It is a paid service — never call it twice for the same person.**
- **Check the DB first.** Before calling SkipGenie for any person, call Load Person or Load Ancestry Records to see if a prior SkipGenie result was already saved for that name in this session or a prior one. If a stored result exists, use it — do not call the API again.
- **Save immediately.** Every SkipGenie response must be written to DB via Write Person (upsert-person) with `matched_identity` before moving on. If you skip this write and the session crashes, the paid result is lost and the API will be called again.
- **Use it to confirm identity.** Given a name like "Mary Justice", SkipGenie tells you: is this a real person, what is their DOB/DOD, where did they live, what is their deceased status? That's its job.
- **Its `possible_relatives` are cross-reference signals, not heirs.** If you're researching Mary Justice and SkipGenie lists "Lydia Hayes" as a relative, that confirms you found the right Mary Justice — it does not mean Lydia Hayes is Mary's heir.
- **Never infer children from shared last name or age gap alone.** SkipGenie has no mechanism for identifying parent-child relationships. A person listed as a relative who shares the last name "Hayes" and is younger could be a sibling, cousin, niece, or unrelated neighbor.
- **Always pass city or county — name + state alone returns nothing.** SkipGenie requires geographic narrowing. Pass the property county (e.g. "Wake") as city. Without it, the API returns an empty result even when the person exists in the database.

**Obituary > SkipGenie for heir discovery.**
- When an obituary explicitly lists surviving children, that list is closed and authoritative.
- Do not add SkipGenie relatives as additional children when an obituary is available.
- Only supplement with SkipGenie relatives if no obituary was found.

**Probate > Obituary for legal heir list.**
- If a probate document names heirs/beneficiaries, those are the legal heirs.
- `cascade_needed = false` once a probate with named persons is found.
- Pull and extract the document (Court Document Pull) before making this decision.

**New information can change the search strategy.**
- If an obituary names someone you haven't researched yet → research them.
- If SkipGenie returns a married name you didn't know → re-run Ancestry with that name.
- If a probate document lists a great-nephew as beneficiary → note that this branch ends.
- The Orchestrator decides what to do next based on what it just learned.

**Write as you go.**
- Write voter records to DB as soon as they're found.
- Write ancestry records to DB as soon as they're found.
- Write court findings to DB as soon as any estate case is located.
- Write the final person record only when research is complete for that person.

**NC Chapter 29 intestate succession governs the cascade decision.**
- If deceased + no estate → children are primary heirs. Research each child.
- If deceased + no children + no estate → surviving spouse gets half, then parents/siblings.
- If deceased + estate with named heirs → cascade to those named heirs only.
- Apply this at the time of synthesis, not in a separate node.

---

### Tools Available to the Orchestrator

---

#### RESEARCH TOOLS

---

##### `SkipGenie`
**What it does:** Searches a people-finder database for a person by name and location. Returns
possible matches, each with age, DOB, DOD, deceased flag, current and historical addresses,
phone numbers, emails, and a list of `possible_relatives`.

**When to use:**
- At the start of researching any new person, to confirm their identity and get their DOB/DOD/address.
- When you have a name but nothing else — SkipGenie gives you the anchor facts (is this person real,
  roughly when did they die, where did they live) that make every subsequent search more precise.
- When you need to confirm that the person you're researching is the same one the obituary or
  probate refers to (does their address match the county? does a known family member appear in
  their relatives list?).

**When NOT to use:**
- Do not call it if a stored result already exists in DB for this person in this session.
  Check Load Person or Load Ancestry Records first. SkipGenie is a paid per-call API — calling
  it twice for the same person wastes money and returns the same data.
- Do not use `possible_relatives` to build an heir list. Relatives on SkipGenie are connection
  signals, not family tree data. Their relationship type (child, sibling, cousin, spouse) is
  not stated and cannot be inferred from age or surname alone.
- Do not call it for a name that is only a first name or a partial name — it will return noise.

**Required parameters:** `first_name`, `last_name`, `state="NC"`, `city=<county name>`.
Name + state alone returns nothing. County is required to narrow the result set.

**Save immediately:** Write the matched identity to DB via `Write Person` before proceeding
to the next tool. If you skip this and the session crashes, the paid API result is gone.

**Output to use:** `matched_identity` (full_name, dob, dod, address), `vital_status_hint`
(deceased/living/unknown), `possible_relatives` (for identity cross-check only).

---

##### `NC Voter Lookup`
**What it does:** Searches the NC State Board of Elections voter registration database by name
and county. Returns voter records including registration status, full legal name, and city.

**When to use:**
- As the first vital status check for any person. An Active voter registration is the highest
  confidence signal that someone is alive — the NCSBE regularly purges deceased voters.
- To discover a married name. A woman who registered under her married name will show up here
  with her full legal current name, even if every other source has her maiden name.
- To confirm county — if the voter is registered in Wake County, that confirms geographic match
  with the property.

**When NOT to use:**
- Do not treat a missing voter record as proof of death. Many people are not registered or
  were purged for reasons other than death (moved out of state, voluntarily removed).
- Do not use a "Removed" status alone as a death signal — it means they were removed from
  the rolls, not necessarily that they died.

**Interpretation:**
- `Active` → living with high confidence. Stop here if living confirmation is all you need.
- `Removed` → investigate further. Check SSDI and obituaries.
- Not found → unknown. Move to SSDI and obituary search.

**Save immediately:** Write the result to DB via `Write Voter Record` even if not found
(record the null result). Downstream synthesis reads voter records from DB.

---

##### `Ancestry Search` (with automatic DB save)
**What it does:** Searches Ancestry.com for records matching a person. The tool both searches
and saves results to the DB in one call — no separate write step needed. Returns a
`records_summary` of matches with dob, dod, children[], parents[], spouse, collection name,
and source URL.

**Collections to know:**
- `61843` — U.S. Obituary Collection. The single most useful collection for heir research.
  Obituaries name surviving children with full married surnames, spouse, grandchildren,
  siblings, and parents. Use this first for any deceased person.
- `2442` — U.S. SSDI (Social Security Death Index) 1935–2014. Confirms death date and
  last residence state. Useful for vital status when voter lookup is inconclusive.
- `63277` — Family trees. Shows how others have structured this family. Useful for
  discovering children not mentioned in the obituary, but treat as a signal to verify —
  not as authoritative.

**When to use:**
- **Direct search (first_name + last_name + death_location + collection_id=61843):**
  First search for any deceased person. Finds their own obituary.
- **Parent-mode search (mother=<name> OR father=<name> + last_name=<surname> + collection_id=61843):**
  Finds obituaries where this person is named as a parent. Surfaces children who have their own
  obituaries, with full married surnames. Use this when the direct obit didn't name all children
  or when you suspect married daughters.
- **SSDI search (last_name + first_name + collection_id=2442):**
  When voter lookup returned unknown and direct obit search returned nothing. SSDI confirms
  death date and last residence ZIP code.
- **Census search (last_name + state=NC + collection_id=2442):**
  Use 1940 census to find household members — often surfaces siblings (Johnnie, Moses, Margaret)
  who don't appear in the obituary because they predeceased or were estranged.

**Record selection rules:**
- Hard reject: any record whose death_location is a state other than NC (unless the person
  is known to have moved).
- Prefer: dod year matches your estimated year ±2, children[] overlap with known relatives.
- After selecting a candidate, always follow up with `Ancestry Record` (the detail page)
  to get the canonical full-name children list — the search card often shows first names only.

**Do NOT use** if you already have a confirmed obituary with full children list from a prior
`Ancestry Search` in this session (check `Load Ancestry Records` first).

---

##### `Ancestry Record`
**What it does:** Fetches the detail page for a specific Ancestry record by source URL or
record ID. Returns a structured record with full field parsing: Name, Birth Date, Death Date,
Birth Place, Death Place, Spouse, Father, Mother, Child 1/2/3, Relatives.

**When to use:**
- **Always** after selecting a best-candidate from `Ancestry Search`. The search card is
  incomplete — children are often listed as "Mary" (first name only). The detail page gives
  "Mary Justice" (full married name). Without this step, you cannot queue the heir correctly.
- When a prior `Ancestry Search` returned children[] with only first names — re-fetch the
  detail page using the source_url from the stored record.
- When you have a record_id from a prior search that you didn't detail-fetch yet.

**Always use `source_url`, not the bare `record_id`.** For Newspapers.com obituaries
(collection 61843), the bare numeric ID resolves to the wrong endpoint and returns 404.
The source_url (e.g. `https://www.ancestry.com/search/collections/61843/records/835792513`)
is always reliable.

**Output to use:** `children[]` (canonical full-name list), `spouse_name`, `parents[]`,
`residence` (last known address for geographic confirmation).

---

##### `Brave Search`
**What it does:** Web search engine query. Returns page titles, URLs, and snippets from
public web results.

**When to use:**
- When `Ancestry Search` (collection 61843) returned no matching obituary, or matched a
  person in the wrong state.
- To find a publicly hosted obituary on a funeral home website, local newspaper, or
  legacy.com/findagrave.
- Search pattern: `"[FULL NAME] obituary [county] NC [approximate year]"`
  Example: `"Alyce Joye Hayes obituary Wake County NC 2024"`
- Can also be used to find court case mentions, news articles, or other public records
  that might confirm death or identify heirs.

**When NOT to use:**
- Do not use it before trying `Ancestry Search` — Ancestry has structured data, Brave returns
  raw text that requires parsing.
- Do not use it to find living persons — results may be stale or incorrect.

**Follow up with `Fetch Obituary Page`** if a promising URL is found. Brave Search only
returns snippets — the full obituary text (with the complete survivor list) requires fetching.

---

##### `Fetch Obituary Page`
**What it does:** Fetches the full HTML text of a webpage and extracts the readable content.

**When to use:**
- After `Brave Search` returns a funeral home or obituary URL. The snippet from Brave may
  show the name and date, but the full survivor list ("survived by her children...") is in
  the body text, which this tool retrieves.
- When the Ancestry detail page points to an external newspaper site for the full text.

**What to extract from the result:**
- Full survivor list: children, grandchildren, siblings, spouse
- Death date and location (confirms identity)
- Church, club, or organizational affiliations (useful for geographic confirmation)

**Do not call this for Ancestry.com URLs.** Ancestry requires a logged-in session that this
tool does not maintain. Use `Ancestry Record` for Ancestry URLs.

---

##### `Court Researcher` (sub-agent)
**What it is:** A dedicated sub-agent called by the Orchestrator for every deceased person.
It handles the entire probate research sequence internally and returns one clean structured
result. The Orchestrator never calls Court Search, Register of Actions, or Court Document
Pull directly — those tools live inside Court Researcher.

**When the Orchestrator calls it:**
- For every deceased person in scope, without exception — even if an obituary was already
  found. Probate supersedes obituary for the legal heir list.
- Pass: `person_name`, `county`, `session_id`, `property_id`.

**What Court Researcher does internally:**

1. **Court Search** — searches the NC Courts Portal by party name.
   - Name variant order (never skip):
     1. `"LAST, FIRST"` — no middle, no suffix. Most important variant — portal indexes by first+last only.
        `"HAYES, ALYCE"` finds case 24E002839-910; `"HAYES, ALYCE JOYE"` does not.
     2. `"LAST, FIRST MIDDLE"` — full name as provided.
     3. Last name only — `"HAYES"`. Noisy but catches edge cases.
     4. `"FIRST LAST"` — no comma. Catches differently indexed entries.
   - Case types that indicate a filed estate: `E` (Decedents' Estate), `SE` (Small Estate),
     `SP` (Special Proceedings), `PR` (Probate). Do not skip `SE` — it is the most common
     type for recent deaths.
   - Saves to DB via `Write Court Findings` immediately when a case is found — before pulling
     the document. If the document pull fails, the case reference is still recorded.

2. **Register of Actions** — fetches the event timeline for any found estate case.
   - Key events: `Letters Testamentary` = will exists; `Letters of Administration` = intestate;
     `Deed of Distribution` = real property already transferred to named heirs.
   - If `roa_unavailable=true` (WAF block): skip, use case data from Court Search directly.

3. **Court Document Pull** — downloads and parses the probate PDF.
   - Extracts `named_persons[]` with role (heir/executor/beneficiary) and `has_issue` (true/false/null).
   - `has_issue=false` is the highest-value signal in the system: permanently closes that branch.
   - If documents=[] or pull fails: returns the case reference only with a note.
   - Updates `Write Court Findings` with extracted named_persons and family_tree.

**What it returns to the Orchestrator:**
```json
{
  "estate_filed": true,
  "had_will": false,
  "case_number": "24E002839-910",
  "case_url": "...",
  "named_persons": [
    { "name": "Frederick Merritt", "role": "beneficiary", "has_issue": null }
  ],
  "notes": "Small estate. Letters of Administration issued 2024-03-01."
}
```

**Why it's a sub-agent and not direct tool calls:**
The probate research sequence (Search → ROA → Doc Pull) always runs as a unit with no
branching decisions the Orchestrator needs to make mid-sequence. The probate document text
is often very long — isolating it in a sub-agent keeps that text out of the Orchestrator's
context window, which degrades reasoning quality over many iterations.

---

##### `Wake Deeds` / `Buncombe Deeds` / `Mecklenburg Deeds`
**What they do:** Search the county Register of Deeds for recorded instruments where the
person appears as a grantor (seller). Returns deed book, page, doc type, grantee, and
recording date.

**When to use:**
- For any person who owned or may have owned real property in that county.
- A grantor search tells you: did this person transfer property before they died? If yes,
  and the transfer was to their heirs or estate, that's a chain-of-title signal.
- If the person transferred property to their children via deed during their lifetime, those
  children are named and their current legal names are on record.
- Also useful to confirm the person's address and approximate activity period.

**County routing:**
- Property in Wake County → use `Wake Deeds`
- Property in Buncombe County → use `Buncombe Deeds`
- Property in Mecklenburg County → use `Mecklenburg Deeds`
- Other counties → skip deed search, note `county_supported=false`

**Do not use for grantee search** — these tools only search the grantor index. To find what
someone bought, use court or assessor records.

---

#### DB READ TOOLS

---

##### `Load Property State`
**What it does:** Returns the full property record from DB: address, county, parcel ID,
current owners, deed transfer history, all document extractions, and any existing heir
research session linked to this property.

**When to use:**
- At the very start of a session to get property address and county (needed for SkipGenie
  city parameter and court search county).
- To retrieve the deed transfer history — prior transfers may name heirs or reveal
  estate transfers already recorded.
- To check if a prior research session exists for this property (avoid duplicating work).

**Key fields:** `property.county`, `property.current_owners`, `property.address.city`,
`appraiser_transfers` (grantor/grantee history), `extractions` (full deed text).

---

##### `Load Ancestry Records`
**What it does:** Returns all Ancestry records saved to DB for this session. Each record
includes the search name, collection, person_name, dob, dod, birth/death location, spouse,
parents[], children[], siblings[], source_url, and relevance score.

**When to use:**
- Before running `Ancestry Search` for any person — check if results are already saved.
  If the person was searched before (even in a prior session via a different queue item),
  the results are here and you should use them rather than re-calling the API.
- When synthesizing what is known about a person — the full ancestry picture for the session
  is here.
- After the Orchestrator has researched all persons, load this to build the complete family
  picture for the family tree write.

**Filter by `search_name`** to get records relevant to a specific person.
**Filter by `collection`** to separate obituaries (61843) from SSDI (2442) from census.

---

##### `Load Court Findings`
**What it does:** Returns all probate/estate court findings saved to DB for this session.
Each finding includes person_name, case_number, case_url, case_type, estate_filed, had_will,
named_persons[], probate_family_tree[], documents[], and notes.

**When to use:**
- Before running `Court Search` for any person — check if the court search was already done.
  If findings exist for this person, use them and skip the court search entirely.
- When synthesizing cascade_needed — if estate_filed=true with named_persons, cascade_needed=false.
- When looking for `has_issue=false` signals that permanently close a branch.

**Key signals:** `named_persons[].has_issue=false` → confirmed no children → close branch.
`named_persons[].role="beneficiary"` → legal heir regardless of family relationship.

---

##### `Load Voter Records`
**What it does:** Returns all NC voter records saved to DB for this session. Each record
includes search_name, full_name (legal married name), county, status (Active/Removed),
and search_context (which agent saved it).

**When to use:**
- Before running `NC Voter Lookup` for any person — check if the voter lookup was already done.
- To discover married names: if the voter record's `full_name` differs from the `search_name`,
  the person registered under a different (likely married) name. Use that full_name for
  Ancestry searches.
- To confirm living status across the whole session before final synthesis.

---

##### `Load Person`
**What it does:** Returns the full research record for a specific person in this session.
Includes matched_identity, vital_status, estate_filed, had_will, cascade_needed,
cascade_relatives, obituary_url, obituary_text, family_alive_at_death, and all
previously saved research phase data.

**When to use:**
- At the start of researching any person — check what's already known before calling
  any external APIs. If the person was partially researched in a prior run or
  was written by the root research phase, the record is here.
- To check if SkipGenie has already been called for this person (matched_identity populated = yes).
- To resume partial research without repeating completed steps.

---

##### `Load Family Dataset`
**What it does:** Returns all persons in this session with their complete research records —
vital_status, cascade_needed, cascade_relatives, estate_filed, obituary data, and court data.

**When to use:**
- At the final synthesis stage, after all individual persons have been researched.
- To build the complete family tree and apply NC Ch. 29 across all branches.
- To identify any person whose `cascade_needed=true` but whose children haven't been
  researched yet — they need to be added to the work queue.

---

#### DB WRITE TOOLS

---

##### `Write Person` (`/heir/upsert-person`)
**What it does:** Creates or updates a person record in `heir_research_persons`. If a record
for this `input_name` already exists in the session, it updates it. If not, it inserts a new one.
Returns person_id, session_id, and the echoed fields for use in subsequent tools.

**When to use:**
- **Immediately after SkipGenie** — write matched_identity, vital_status_hint, and the SG
  result before doing anything else. This prevents duplicate paid API calls on retry.
- **After determining vital_status** — update the record with vital_status=deceased/living/unknown.
- **After full synthesis** — final write with cascade_needed, cascade_relatives, estate_filed,
  had_will, obituary_url, obituary_text, claim_sources, notes.

**Key fields to write at each stage:**
- After SkipGenie: `matched_identity`, `vital_status` (from hint), `research_phase="skipgenie"`
- After voter/SSDI: `vital_status` (confirmed), `research_phase="vital_status"`
- After obit/court: `obituary_url`, `obituary_text`, `estate_filed`, `had_will`
- Final: `cascade_needed`, `cascade_relatives`, `research_phase="complete"`

**Idempotent** — safe to call multiple times for the same person. Later writes update specific
fields without overwriting others.

---

##### `Write Court Findings` (`/heir/write-court-findings`)
**What it does:** Persists a probate or estate court finding to `heir_court_findings`.
Stores case_number, case_url, case_type, estate_filed, had_will, named_persons[],
probate_family_tree[], documents[], and notes.

**When to use:**
- As soon as `Court Search` returns any estate/probate case — write immediately, before
  calling `Register of Actions` or `Court Document Pull`. The case reference is valuable
  even if the document pull fails.
- After `Court Document Pull` — update the finding with named_persons and family_tree.
- Even when Court Document Pull returns empty documents — write the case with
  `notes="Document pull failed — court case recorded only"`.

**session_id and property_id must be integers.** Do not pass string values or placeholder
text like "unknown_session". If you don't have a valid integer session_id, do not call
this tool.

---

##### `Write Voter Record` (`/heir/write-voter-records`)
**What it does:** Persists a voter lookup result to `heir_voter_records`. Stores search_name,
full_name (legal/married name), county, status (Active/Removed), and search_context.

**When to use:**
- After every `NC Voter Lookup` call, including when the person is not found. Write the null
  result — it records that the lookup was done and prevents re-calling the API.
- Write the full_name even when it differs from the search_name. That difference is a married
  name discovery — the downstream synthesis needs it.

---

##### `Queue Persons` (`/heir/queue-persons`)
**What it does:** Adds new persons to `heir_research_queue` with name, relationship_hint,
depth, and optional maiden_name. The Orchestrator reads from this queue to determine who
to research next.

**When to use:**
- When a new person is discovered from an obituary, probate document, or Ancestry record
  and they need to be researched.
- When `cascade_needed=true` for a deceased person — their children must be queued.
- Include `relationship_hint` (child, spouse, sibling, grandchild) and `maiden_name` if known.
- Do not queue: the root decedent themselves, "Estate of X", "Heirs of X", single-token
  names (first name only), or persons already in scope with a `done` status.

---

##### `Write Family Tree` (`/heir/write-family-tree`)
**What it does:** Writes the final resolved heir tree to DB. Stores the complete family
structure with each person's vital_status, relationship, share_fraction, and basis for inclusion.

**When to use:**
- Only once, at the very end, after all branches are resolved.
- Include every person in scope: resolved heirs, closed branches (with reason), and any
  unknowns with notes explaining why they couldn't be resolved.
- This is the record that gets read by the title attorney and the client-facing output.

---

### Internal State the Orchestrator Tracks

The Orchestrator tracks state only for the **current person** in this invocation:

```
{
  "current_person": "Alyce Joye Hayes",
  "relationship_hint": "child",
  "what_i_know": {
    "skipgenie_done": true,
    "voter_done": true,
    "vital_status": "deceased",
    "court_done": true,
    "estate_filed": true,
    "obit_done": false
  },
  "persons_to_queue": [
    { "name": "Frederick Merritt", "relationship_hint": "beneficiary" }
  ]
}
```

The DB queue (`heir_research_queue`) is the source of truth for who still needs research.
The Orchestrator does not need to know about other persons — n8n manages the loop externally.

---

### Termination Conditions (per invocation)

The Orchestrator is done with the current person when:
- Person is **living** — voter Active or confirmed living. Write person, queue nobody, done.
- Person is **deceased + estate filed with named heirs** — Court Researcher returned named_persons.
  Queue those persons, write person record, done.
- Person is **deceased + probate says `has_issue: false`** — confirmed no children. Write person, done.
- Person is **deceased + all search strategies exhausted** — write person with best known data, done.
- Vital status is **unknown after exhausting all sources** — write person as unknown, done. Do not
  discard — unknown persons are still included in the heir list by Family Assembly.

After writing the final person record, n8n (not the Orchestrator) handles:
- Mark Person Done in the queue
- Check if queue has remaining items
- If yes → Self Trigger Orchestrator Webhook with next person
- If no → Trigger Family Assembly

---

### Final Output (per invocation)

The Orchestrator returns a structured result for the one person it researched:

```json
{
  "person_name": "Alyce Joye Hayes",
  "vital_status": "deceased",
  "estate_filed": true,
  "had_will": false,
  "cascade_needed": false,
  "cascade_relatives": [
    { "name": "Frederick Merritt", "relationship_hint": "beneficiary" }
  ],
  "persons_queued": ["Frederick Merritt"],
  "notes": "Estate case 24E002839-910. Letters of Administration issued. Frederick Merritt named sole beneficiary."
}
```

Family Assembly handles the full cross-person synthesis, NC Ch. 29 share fractions, and
final family tree write once all queue items are done.

---

## Why This Is Better

| Problem in current design | How orchestrator solves it |
|--------------------------|---------------------------|
| Vital Status Researcher fires before obituary is found | Orchestrator finds the obit first if voter returns no result — then confirms death from obit |
| SkipGenie relatives wrongly labeled as children | Orchestrator explicitly knows SkipGenie relatives ≠ heirs, only confirms identity |
| Unknown persons permanently discarded at Vital Status Gate | Orchestrator keeps unknown persons open and continues researching them |
| New names found in obit can't trigger new SkipGenie lookups | Orchestrator immediately adds new names to its work queue |
| Person Compiler re-reads DB for data that's already in memory | Orchestrator synthesizes from its own working context — DB write is the final step |
| 8 separate JS parse nodes that break silently on format errors | Orchestrator reasons over native tool responses — no parsing nodes |
| Probate document text bloats the main agent context | Court Researcher sub-agent isolates document text — Orchestrator only sees the structured result |
| Branch Decision is a separate agent that re-reads DB | Orchestrator applies NC Ch. 29 inline at the moment of synthesis |
| Family Assembly has research agents, intestate logic, and JS parse nodes | Family Assembly becomes lightweight: just reads all person records and writes the tree — no research |
| Probate found but estate_filed=false because court search used wrong name variant | Orchestrator tries "LAST, FIRST" (no middle) as first retry, the most important variant |

---

## Implementation Plan

### Phase 1 — Design the Orchestrator prompt
Define the system message with:
- Identity and goal
- Reasoning loop pattern
- All behavioral rules (SkipGenie, obit precedence, NC Ch. 29)
- Tool list with descriptions (Court Researcher described as a sub-agent call, not individual tools)
- Termination conditions and output format

### Phase 2 — Build the Court Researcher sub-agent
Separate `@n8n/n8n-nodes-langchain.agent` node (or sub-workflow) with:
- Tools: Court Search, Register of Actions, Court Document Pull, Write Court Findings
- Input: `person_name`, `county`, `session_id`, `property_id`
- Output: `{estate_filed, had_will, case_number, case_url, named_persons[], notes}`
- Max iterations: 10 (fixed sequence, shouldn't need more)

### Phase 3 — Build the Orchestrator workflow
Nodes in the new Orchestrator workflow:
- **Orchestrator Webhook** — receives `person_name`, `session_id`, `property_id`, `county`
- **Heir Research Orchestrator** (Agent) — one person per invocation, max iterations: 20
  - Tools: SkipGenie, NC Voter, Ancestry Search, Ancestry Record, Brave Search, Fetch Obit Page,
    Wake/Buncombe/Mecklenburg Deeds, all DB reads, all DB writes, Court Researcher (as tool call)
- **Mark Person Done** — marks queue item as done
- **Check Queue Status** — checks if any pending items remain
- **If Queue Empty** — routes to Self Trigger or Family Assembly
- **Self Trigger Orchestrator** — HTTP POST back to Orchestrator Webhook with next person
- **Trigger Family Assembly** — HTTP POST to Family Assembly webhook when queue is empty

### Phase 4 — Simplify Family Assembly
Family Assembly no longer does research. It only:
- Loads all person records (Load Family Dataset)
- Applies NC Ch. 29 to compute share fractions
- Writes the final family tree (Write Family Tree)
Remove: Family Assembler agent, Intestate Expert agent, all JS parse nodes, FA Queue Cascade,
FA Trigger Worker. Replace with one lightweight agent or a simple code node.

### Phase 5 — Wire connections
Replace the wire from Write Root Person → Branch Planner with:
Write Root Person → Trigger Orchestrator Webhook (with first person from cascade_relatives)

Remove all nodes from Branch Planner through Genealogist in the old Worker and FA workflows.

### Phase 5 — Test on known cases
Use session 75 (Lydia Hayes) as the validation case. Expected outcome:
- Alyce Joye Hayes → Court Researcher finds 24E002839-910 → Frederick Merritt identified → branch closed
- Mary Justice → deceased, no children → branch closed
- Troy Hayes → deceased, no children (per probate family tree) → branch closed
- Johnnie Hayes / Moses Hayes / Margaret Hayes → research each, determine if children exist
- Grandchildren (Carrie Wilkerson, Cecillia Hunter, Alexander Massenburg) → research as level-2 heirs

---

## Tips & Tricks for Best Performance

These are operational patterns learned from real runs. They are not rules — they are
**heuristics that consistently produce better results** when applied by the Orchestrator.

---

### 1. Always Check the DB Before Any External API Call

Before calling SkipGenie, NC Voter, Ancestry Search, or Court Search for any person, load
their existing record first. The priority order is:

```
Load Person → Load Ancestry Records → Load Court Findings → Load Voter Records
→ THEN decide what to call
```

This single habit eliminates the most common waste in the system:
- A second SkipGenie call for someone already searched (paid, returns same result)
- A second Ancestry Search for someone whose obituary is already in DB (slow, unnecessary)
- A second Court Search for someone already confirmed to have no estate

If `Load Person` returns `research_phase="complete"` for a person, skip all tool calls —
they are done.

---

### 2. Optimal Tool Order for a New Person

When you start researching a person you know nothing about, follow this sequence. Each step
uses the result of the previous one to make the next call more precise:

```
1. Load Person          → check what's already saved
2. SkipGenie            → confirm identity, get DOB/DOD/address, city=county
3. NC Voter Lookup      → Active = living (stop here if confirmed)
4. Court Search         → LAST, FIRST (no middle) first, then variants
5. Ancestry Search 61843 → direct obit search (name + death_location=NC)
6. Ancestry Record      → detail page for the best obit candidate
7. Brave Search         → only if Ancestry obit search returned nothing
8. Fetch Obituary Page  → only after Brave Search found a promising URL
```

If step 3 (Voter) returns Active → skip steps 4–8. Living persons have no estate and no
heirs to cascade.

If step 4 (Court Search) finds an estate with named persons → skip step 5–8. Probate
supersedes obituary. Extract the family tree and close the branch.

---

### 3. Reading Ancestry Search Results to Pick the Right Record

Ancestry Search returns multiple candidate records. Pick the best one using this scoring:

**Strong match signals (hard confirm):**
- death_location contains "NC" or a North Carolina county
- dod year is within ±3 years of your expected death window
- children[] or parents[] overlap with names you already know from this session

**Soft match signals (use as tiebreakers):**
- birth_location matches the county you're working in
- spouse name matches a name from the obituary or SkipGenie result
- collection is 61843 (obituary) — preferred over 63277 (family tree) which is user-contributed

**Hard reject:**
- death_location is another state (California, Texas, etc.) — wrong person unless you
  have strong evidence the person moved
- dod is 20+ years off from your expected window
- no overlap whatsoever with known family members

**After selecting:** Always call `Ancestry Record` with the source_url — never stop at the
search card. The full detail page has complete children[] with married surnames. The search
card shows first names only.

---

### 4. When to Stop Searching and Close a Branch

Do not keep searching indefinitely. Close a branch as soon as you hit any of these conditions:

| Condition | Action |
|-----------|--------|
| Active voter registration found | `vital_status=living` → branch closed. Living persons are their own heirs. |
| Court probate with `has_issue=false` in named_persons | `cascade_needed=false` → permanently closed. No children. |
| Probate with named beneficiaries | Use those beneficiaries. Do not search for other heirs. |
| Obituary with explicit children list | That list is the closed heir set. Do not supplement with SkipGenie relatives. |
| All 4 Court Search variants returned no estate cases | `estate_filed=false`. Move on. |
| Ancestry obit + Brave Search both returned nothing | Note `obituary_not_found`. Still write person with what you know. |

Do not keep retrying tools that already returned clean null results. "Not found" is a valid
and complete answer — record it and move on.

---

### 5. Court Search: What to Do When All Variants Return Noise

"Noise" means the search returned cases for the wrong person (wrong county, different person
with same name, divorce or criminal case, not estate).

**Check case type first.** If the cases are all `CR` (criminal), `CV` (civil), `D` (divorce),
`J` (juvenile) — the person has no estate. Move on.

**If case type looks right but name seems off:**
- Pull Register of Actions to verify the decedent name in the first filing
- Look for the petition date — does it match when you'd expect this person to have died?
- Check the county — NC Courts Portal shows multi-county results; filter to the right county

**If you see an estate case but aren't sure it's the right person:**
- Pull the first document (usually the Petition for Letters) — it names the decedent's address,
  date of death, and surviving kin. Match against SkipGenie DOD and address.

**Last resort:** If 4 variants all return zero estate cases, record `estate_filed=false` and
move to obituary research. Do not invent a 5th variant.

---

### 6. Handling Unknown Vital Status

Unknown vital status is not a dead end — it is a work state. Never discard a person because
their vital status is unknown. Keep them in `open_branches` and work through this checklist:

```
Step 1: NC Voter Lookup         → Active = living. Not found = still unknown.
Step 2: SSDI search (Ancestry 2442) → confirms death date if they died before 2014
Step 3: Direct obit search (Ancestry 61843) → confirms death if obit exists
Step 4: Brave Search for name + "obituary" + NC → finds recent deaths not on Ancestry
Step 5: SkipGenie deceased flag  → `vital_status_hint=deceased` is a soft signal, not proof
Step 6: If still unknown after all 5 → write vital_status="unknown" and close the branch
         with note "unable to confirm vital status after exhausting all sources"
```

Unknown status after step 6 does not mean no heirs. Under NC Ch. 29, an heir whose status
is unknown is still included in the heir list — the title opinion notes the uncertainty.

---

### 7. Recognizing and Closing a Branch Quickly

The fastest closes come from these signals — check for them before starting deep research:

**Fastest close:** Active voter → one tool call → done
```
NC Voter Lookup → status=Active → vital_status=living → close immediately
```

**Second fastest close:** Probate with has_issue=false
```
Court Search → Court Document Pull → named_persons[x].has_issue=false → close permanently
```

**Third fastest:** Probate with named beneficiary who is not a typical heir (great-nephew, neighbor, friend)
```
Court Document Pull → beneficiary is a single non-relative → that person gets the share
→ stop researching all other branches for this deceased person
```

**Watch for chain closes:** If you confirm Person A is deceased with no children, AND Person B
(their sibling) is also deceased with no children, AND there's a third sibling C who is the
sole living person in that generation — you can close A and B in the same synthesis step
without separate tool calls for each, using what you've already gathered.

---

### 8. Married Name Discovery Workflow

Many female heirs in NC records are indexed under their maiden name in early documents
(deed, probate) but under their married name in current records (voter, recent obit).

When you discover a married name, use it immediately to unlock new searches:

```
1. NC Voter Lookup returns full_name "Mary Justice" when you searched "Mary Hayes"
   → You now have her married name.
   → Re-run Ancestry Search with last_name="Justice" + first_name="Mary" + collection=61843
   → Re-run Court Search with "JUSTICE, MARY"
   → Update Write Person with matched_identity.current_name="Mary Justice", maiden_name="Hayes"

2. SkipGenie returns a different full name than the search name (e.g. searched "Alyce Hayes",
   matched "Alyce Joye Cable")
   → Check if this is a married alias or a wrong match
   → If the DOB/address confirms it's the right person, use the new name for Ancestry

3. Obituary says "survived by daughter Mary Justice (née Hayes) of Raleigh"
   → maiden_name="Hayes", married_name="Justice" — explicitly stated
   → Use "Mary Justice" for all subsequent searches
```

Do not search for the same person under two different names simultaneously — you'll save
duplicate records. Resolve the name first, then search once with the correct name.

---

### 9. SkipGenie Efficiency Rules

SkipGenie is the only paid tool per call. Apply these rules to get maximum value per dollar:

**Get it right on the first call:**
- Always pass city=county (e.g. `city="Wake"`). Name+state returns nothing.
- Use the full known name (first + last, no middle) — middle names sometimes cause mismatches.
- If DOB is known from a prior source, include it to narrow the match.

**Read the result deeply the first time:**
- Extract DOB, DOD, address, all current and historical addresses, and possible_relatives.
- Note the possible_relatives list even if you're not using it for heir discovery — it's
  useful for identity confirmation in later searches. "Does this obit mention any of these relatives?"

**What to do with possible_relatives:**
- Scan for names you already know from this session. A relative match = you have the right person.
- If you're researching Person A and their SkipGenie returns Person B (already in your scope)
  as a relative → confirm these are the same family branch, not separate people.
- Never add a SkipGenie relative to the heir list directly. They are signals, not heirs.

**Save before you do anything else:**
- Immediately after SkipGenie → Write Person with matched_identity + vital_status_hint.
- This is non-negotiable. If the session crashes before this write, the paid result is lost.

---

### 10. Source Priority Reference

When two sources conflict, use this hierarchy:

```
1. Court probate document (highest)    — legal, filed, enforceable
2. Probate Register of Actions         — official court timeline
3. Obituary (Ancestry 61843 or web)    — intentional public declaration
4. SSDI (Ancestry 2442)               — government death record
5. NC Voter registration              — state administrative record
6. SkipGenie matched identity         — third-party aggregator (soft)
7. Family tree (Ancestry 63277)       — user-contributed, unverified (soft)
8. SkipGenie possible_relatives       — lowest — signal only, not evidence
```

Example: An obituary says "Troy Hayes had no children." A SkipGenie relative named "Troy Hayes Jr." appears. The obituary wins — do not add Troy Hayes Jr. as an heir. Verify if "Troy Hayes Jr." is even a real distinct person before doing anything with that name.

---

## Open Questions

1. **Max iterations** — a family with 6 children, each needing 3-5 tool calls, could need 30+
   iterations. Need to set `maxIterations` high enough (suggest 60) without infinite loops.

2. **Session county forwarding** — already fixed in v3 build: Trigger Worker Init now passes
   county. The orchestrator receives it in its input.

3. **Partial writes on failure** — if the orchestrator crashes mid-run (LLM timeout, WAF block),
   what's the recovery path? Consider a checkpoint: write each person's record as soon as it's
   resolved, not only at the end.

4. **Cost** — one 60-iteration agentic run per session vs. 10 smaller agents. Likely comparable
   or cheaper per heir because there's no duplicate DB reading across multiple agents.

5. **Multi-property concurrency** — the orchestrator is stateless between runs; multiple sessions
   can run in parallel without interference.
