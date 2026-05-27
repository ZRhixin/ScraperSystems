# Heir Tracer — Performance Gaps & Improvement Roadmap

## Baseline: What the Current System Actually Produces

Tested against **Session 37 — LYDIA L HAYES (Property 3)**. Human-verified ground truth provided for comparison.

| Metric | Result |
|---|---|
| Heirs correctly identified | 1 of 12 (8%) |
| Wrong vital status | 1 (TROY HAYES — AI said living, human says deceased) |
| Living heirs with shares found | 0 of 5 |
| Ownership share coverage | ~0% |
| False positives researched | 14 people not in the heir tree |
| Ancestry records collected | 0 (tools wired but never called) |
| Fractional shares computed | 0 |

---

## Root Cause: The Surname Boundary Problem

The real heir tree for Lydia Hayes looks like this:

```
LYDIA L HAYES (root decedent)
├── ALYCE JOYE HAYES (deceased)          ← AI found (only correct hit)
├── TROY L HAYES (deceased)              ← AI found wrong person (living Troy, different person)
├── Johnnie Hayes (deceased)             ← missed
├── MARY HAYES JUSTICE (deceased)
│   └── CARRIE J WILKERSON — 33%        ← missed
├── Moses Hayes (deceased)
│   └── FREDERICK D MERRITT — 33%       ← missed
└── [deceased child]
    └── ALEXANDER M MASSENBURG (deceased)
        ├── ALEXANDRIA JEFFERS — 11%     ← missed
        ├── CHARLOTTE MASSENBURG — 11%   ← missed
        └── WILLIAM MASSENBURG — 11%     ← missed
```

Every living heir has a **different last name than Hayes** (Wilkerson, Merritt, Massenburg, Jeffers).
The system stayed entirely inside the Hayes surname bubble because:

1. **SkipGenie `possible_relatives` is address-based**, not genealogical. It links people who lived at the same address. It will never connect "Mary Hayes Justice" → "Carrie J. Wilkerson" because they are different surnames at different addresses.

2. **Obituary survivor extraction is broken.** Alyce's obit was the one correct anchor. If the system had extracted her survivors and siblings, it would have pivoted to the right family branches. Instead, `family_alive_at_death: []` for every single deceased person researched.

3. **Ancestry tools were never called.** Zero ancestry records despite tools being connected. An Ancestry search for Alyce Hayes (born Wake County 1933) would have surfaced her family record with children listed under different surnames.

4. **No relationship typing.** Every cascade relative enters the queue as `relationship: "unknown"`. The system has no way to prioritize actual children over random address neighbors.

---

## Known Bugs (Fix First)

These block correct output regardless of any other improvements.

### Bug 1 — Obituary Researcher doesn't extract survivors
**What happens:** Agent finds and reads the obituary, but `family_alive_at_death` is always `[]`.
**Impact:** The primary source of cross-surname family links produces nothing.
**Fix:** Update Obituary Researcher system prompt to explicitly extract and output a structured `survivors` list: `[{name, relationship}]`. Parse "survived by her daughter Mary Hayes Justice of Wake Forest, NC" → `{name: "MARY HAYES JUSTICE", relationship: "daughter"}`. Feed this list directly into cascade queue with proper `relationship_hint`.

### Bug 2 — Ancestry tools never called
**What happens:** Tool nodes are wired to agents but system prompts don't effectively instruct agents to use them.
**Impact:** Zero genealogical cross-referencing. All 4 deceased persons (Alyce, Gordon, Michael, Milton) had no Ancestry lookup.
**Fix:** Make Ancestry search a **required step** in the Obituary Researcher, not optional. After confirming deceased status, always call `Ancestry Search` with birth_year, death_location="North Carolina", gender derived from relationship.

### Bug 3 — Session recovery after crash
**What happens:** When n8n crashes mid-processing, the queue item stays in `processing` state. The session never resumes.
**Fix:** Add a stuck-session recovery query on n8n startup:
```sql
UPDATE heir_research_queue
SET status = 'pending', started_at = NULL
WHERE status = 'processing'
  AND started_at < NOW() - INTERVAL '30 minutes';
```

### Bug 4 — TROY HAYES wrong person selected
**What happens:** SkipGenie returned a living Troy Hayes (age 63, Montclair NJ). The correct Troy L. Hayes is deceased. The Orchestrator selected the wrong candidate.
**Impact:** A deceased heir is marked living — their branch never cascades.
**Fix:** When SkipGenie returns a candidate and a death record or obituary is found for someone with the same name, the Selector should prefer the deceased match when the property context strongly suggests a death (NC property, same county).

### Bug 5 — cascade_relatives not merged from all sources
**What happens:** `Person Compiler` builds `cascade_relatives` only from SkipGenie `possible_relatives`. Obituary survivors and Ancestry `children[]` — the most genealogically accurate sources — are stored in DB but never fed into the cascade queue.
**Fix:** `Person Compiler` should merge: SkipGenie possible_relatives + obit survivors (from `family_alive_at_death`) + Ancestry children[]. Deduplicate by name. This is the single biggest structural gap.

---

## Improvement Roadmap

### Phase 1 — Fix What's Broken (Before Any New Features)
*Goal: stop researching wrong people, start crossing surname boundaries.*

1. **Fix obituary survivor extraction** (Bug 1) — parse structured `survivors[]` from obit text
2. **Force Ancestry search on every deceased person** (Bug 2) — required step, not optional
3. **Merge cascade sources** (Bug 5) — obit survivors + Ancestry children + SkipGenie into one deduplicated queue input
4. **Add stuck-session recovery** (Bug 3)
5. **Add depth cap** — enforce `max_depth = 5` in `queue_persons` handler. Prevents runaway cascades.

Expected outcome after Phase 1: the system would have found Mary Hayes Justice (from Alyce's obit survivors or Ancestry), then cascaded to Carrie Wilkerson. It would not have wasted 14 researcher cycles on unrelated Hayes families.

---

### Phase 2 — Relationship-Aware Cascade
*Goal: know what kind of relative we're queuing, not just a name.*

Currently every queue entry has `relationship_hint: "unknown"`. The system can't tell a child from a neighbor.

**Add relationship typing to cascade queue:**
- Obituary survivors → `relationship_hint: "child"` / `"sibling"` / `"spouse"`
- Ancestry children[] → `relationship_hint: "child"`
- Ancestry spouse_name → `relationship_hint: "spouse"`
- SkipGenie possible_relatives → `relationship_hint: "possible_relative"` (lowest priority)

**Add priority ordering to Worker:** research confirmed children and siblings first, possible_relatives last. Skip possible_relatives entirely if children/siblings are available for that branch.

**Add disqualification propagation:** When Intestate Expert marks a person `branch_status = "disqualified"`, flag their subtree in the queue. Before queueing X's relatives, check X's branch_status. If disqualified with no surviving children, skip the queue insert.

---

### Phase 3 — Additional Data Sources
*Goal: cross-reference with sources that don't rely on address proximity.*

**Priority order by cost/value:**

| Source | What it gives | Cost |
|---|---|---|
| **FindAGrave** | Death date, spouse, children listed in memorial comments | Free |
| **NC Probate Records (eFileNC)** | If estate filed, lists ALL heirs by court order | Free |
| **NC Register of Deeds** | Post-death deed transfers naming heirs | Free |
| **FamilySearch** | Census/birth/death records, no paywall, links family across surnames | Free |
| **NC Vital Records** | Death certificates — authoritative next-of-kin with relationship | Free after 50 years |
| **SSDI** | Confirms death date + state | Free |

**NC Probate** is the highest-ROI addition. If an estate was opened, the clerk already identified every heir, their relationship, and their contact info. One lookup replaces the entire cascade for that branch.

**FindAGrave** is the easiest to scrape. Memorial pages often list survivors in the condolence comments (as seen in Alyce's obit page).

---

### Phase 4 — Person Identity Resolution
*Goal: stop researching the same person twice under different name variants.*

The same heir will appear as:
- "John R. Hayes" (SkipGenie)
- "John Robert Hayes" (Ancestry)
- "Johnny Hayes" (obituary)
- "J. Hayes" (deed record)

Currently all 4 get inserted as separate queue entries.

**Add fuzzy name matching + DOB confirmation before queue insert:**
1. Before inserting a name into `heir_research_queue`, check `heir_research_persons` for names within Levenshtein distance 2 of the first + last name
2. If DOB or address overlaps, skip the insert — treat as same person
3. On match, merge the new relationship_hint into the existing record

---

### Phase 5 — Maiden Name Tracking
*Goal: research married women using their birth surname.*

Female heirs who married are nearly unresearchable without their maiden name. "Carrie J. Wilkerson" can't be found on Ancestry or in census records without knowing she was "Carrie Hayes" before marriage.

**Add maiden name extraction:**
- Obituaries often state: "born Carrie Hayes, now of Wake Forest" or "formerly Hayes"
- Ancestry marriage records link birth surname to married name
- NC marriage records (Register of Deeds) are searchable by surname

When a female heir's name is found in records with a parenthetical or "née", extract and store the maiden name. Re-run Ancestry search using maiden name.

---

### Phase 6 — Fractional Share Calculation & Final Report
*Goal: produce the actual deliverable — ownership percentages.*

The system finds who the heirs are but never calculates shares. NC Ch. 29 rules are deterministic given the family tree.

**Add share calculation to Family Assembler / Intestate Expert:**

```
Per stirpes distribution:
- Each living child of the decedent gets an equal share
- Each deceased child's share passes equally to their living children
- Spouse share computed first (NC Ch. 29 §29-14): varies by children/parents present
```

**Output format target:**
```json
{
  "heirs": [
    {"name": "CARRIE J WILKERSON", "relationship": "grandchild", "share_fraction": "1/3", "share_pct": 33.33, "living": true},
    {"name": "FREDERICK D MERRITT", "relationship": "grandchild", "share_fraction": "1/3", "share_pct": 33.33, "living": true},
    {"name": "ALEXANDRIA JEFFERS", "relationship": "great-grandchild", "share_fraction": "1/9", "share_pct": 11.11, "living": true}
  ],
  "total_coverage": 99.99,
  "gaps": ["Moses Hayes branch — no death certificate found, children unknown"],
  "confidence": "medium"
}
```

---

## Summary: What to Fix in What Order

| Phase | Change | Expected Impact |
|---|---|---|
| **Bug fixes** | Extract obit survivors, force Ancestry, merge cascade sources | Eliminates false positives, discovers cross-surname heirs |
| **Phase 1** | Depth cap, session recovery | Prevents runaway cascades, handles crashes |
| **Phase 2** | Relationship-aware cascade, disqualification propagation | Researches real family first, stops dead branches |
| **Phase 3** | FindAGrave + NC Probate scrapers | Biggest coverage expansion for free |
| **Phase 4** | Fuzzy name deduplication | Stops researching the same person multiple times |
| **Phase 5** | Maiden name tracking | Unlocks female heir branches |
| **Phase 6** | Fractional share calculation | Produces the actual deliverable |

The bugs and Phase 1 together are the minimum viable fix. Without them the workflow produces the wrong family tree regardless of how many people it researches.
