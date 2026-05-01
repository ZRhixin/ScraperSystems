Chain-of-Title Scraper — Build Spec
What to build, in order.
Overview
Goal: Given a parcel ID, produce a structured conclusion about the current owner, how they acquired the property, how they hold title, and the supporting documents — with flags on anything unresolved.
Four layers, in order: Scout → Investigate → Conclude → Verify. Each reads from and writes to the database. Pass IDs between n8n nodes, never payloads.
Two databases: Scraper DB owns the investigation (raw captures, sessions, trace, chain conclusions). Production FPILS receives only the final vesting conclusion as a seed fact — that handoff is a future step, not part of this build.
Schema changes (scraper DB)
Add the following tables. Foreign keys to properties.id. All tables include id serial PK, created_at, updated_at unless noted.
appraiser_transfer_history
Prior deeds the property appraiser associates with this parcel. Scout writes; Investigate Phase A verifies each row.
property_id (FK)
book, page, instrument_number (nullable)
recorded_date (nullable)
grantor_raw, grantee_raw (text as shown by appraiser)
short_legal_raw (text as shown by appraiser)
verification_status: pending | verified | verified_with_discrepancy | not_findable
verification_notes (text)
verified_at (timestamp, nullable)
rod_captures
Raw captures from Register of Deeds. Immutable once written.
property_id (FK)
source_url
capture_type: grantee_search_result | grantor_search_result | document_image | index_page
book, page, instrument_number (nullable — what we think this is)
raw_content (bytea or file path for PDF/image)
ocr_text (text, nullable)
ocr_confidence (numeric, nullable)
captured_at
parse_status: captured | extracted | failed | needs_human
parse_error (text, nullable)
court_captures
Same structure as rod_captures, for Clerk of Superior Court records (estate files, orders of distribution, etc.). Include:
court_case_number, document_type, same OCR/parse fields as rod_captures.
document_extractions
Structured fields extracted from a captured document, plus a 1-2 sentence summary. One row per parsed document.
capture_id (FK to rod_captures or court_captures — use two nullable columns or a polymorphic pattern, Z's call)
property_id (FK)
document_type: warranty_deed | quitclaim | corrective_deed | deed_of_distribution | deed_of_trust | mortgage | release | lis_pendens | judgment_lien | affidavit_of_death | estate_order | other
grantor_names (jsonb array)
grantee_names (jsonb array)
recorded_date, instrument_date
book, page, instrument_number
vesting_language (text — raw language about how grantees hold title)
legal_description_full (text, nullable — metes and bounds if present)
legal_description_short (text, nullable)
plat_book, plat_page (nullable)
conveys_multiple_parcels (boolean)
references_prior_deed_book, references_prior_deed_page (nullable — when the deed cites a prior deed)
legal_match_to_parcel: high | medium | low | none
legal_match_method: plat_reference | metes_bounds | narrative | chain_logic_only
legal_match_notes (text)
summary (text — 1-2 sentence AI-generated plain-language summary)
flags (jsonb array of flag strings)
investigation_sessions
One row per property investigation. Tracks overall state.
property_id (FK)
status: pending | in_progress | settled | flagged_for_review
current_phase: A | B | C | D | E | done
started_at, completed_at
iteration_count (int)
stop_reason (text, nullable)
investigation_questions
Open/resolved questions the investigator is chasing. Example: "does grantor Holding have a prior grantee deed?"
session_id (FK)
question (text)
actions_taken (jsonb)
resolution: resolved | unresolved_flagged | abandoned
resolution_notes (text)
investigation_trace
Append-only log of what the investigator did. For audit and Verify-layer review.
session_id (FK)
step_number (int)
action (text — what was done)
input (jsonb — what was passed in)
output (jsonb — what came back)
timestamp
incidental_records
Mortgages, liens, releases, lis pendens found during investigation. Captured and summarized but not reasoned about.
property_id (FK)
extraction_id (FK to document_extractions)
record_type
summary (text)
chain_conclusions
Final output per property. One active row per property (supersede, don't overwrite).
property_id (FK)
status: active | superseded
current_owners (jsonb array of normalized names with deceased flags)
acquisition_type: deed | inheritance_with_deed_of_distribution | inheritance_court_only | unresolved
acquisition_document_refs (jsonb — book/page or case number references)
vesting: sole | tenancy_by_entirety | jtwros | tenants_in_common | trust | entity | unresolved
vesting_evidence (text — the specific language that established vesting)
legal_description_confidence: high | medium | low
supporting_document_refs (jsonb)
flags (jsonb array)
verify_status: pending | approved | objection_raised | flagged_for_human
verify_objections (jsonb, nullable)
superseded_by_id (FK to chain_conclusions, nullable)
properties — add these columns
scout_completed_at
investigation_status (mirrors investigation_sessions.status for quick filtering)
chain_conclusion_id (FK to active chain_conclusions row)
Layer 1 — Scout
Input: parcel_id, state, county.
Output: populated properties row, populated appraiser_transfer_history rows.
AI reasoning: None. Pure extraction.
Steps
Query the property appraiser for the parcel.
Extract and store on properties: parcel identity, address, short legal, parsed subdivision/block/lot if possible, plat book/page, full legal if available, current owner name(s), last sale date.
Extract the appraiser's transfer history. For each prior deed the appraiser lists, create an appraiser_transfer_history row with verification_status=pending.
Set properties.scout_completed_at.
County adapter pattern
Each county has a different appraiser website. Build a Scout adapter per county exposing one method: fetchAppraiserData(parcelId) returning a normalized payload. Adapter handles the site-specific scraping. Scout logic itself is county-agnostic.
Layer 2 — Investigate
Input: property_id (must have Scout complete).
Output: populated rod_captures, court_captures, document_extractions, incidental_records; investigation_sessions marked settled or flagged; investigation_trace filled in.
AI reasoning: Yes — this is an agent loop with tools.
Phase A — Verify appraiser transfer history
For each appraiser_transfer_history row with verification_status=pending:
Pull the deed at the claimed book/page from the ROD. Store in rod_captures.
Run the document-read pattern (below) to produce a document_extractions row.
Compare extracted grantor, grantee, date, and legal description against what the appraiser claimed.
Update verification_status to verified, verified_with_discrepancy, or not_findable. Record verification_notes.
Phase B — Independent ROD search
For the current owner name on file:
Search ROD as grantee. Pull any deeds not already in Phase A. Run document-read on each.
Search ROD as grantor. Pull any deeds. Run document-read on each.
Flag any corrective deeds, confirmation deeds, or quitclaims encountered — these are signals for Phase C to investigate.
Phase C — Chain-back verification (one hop)
Identify the deed that made the current owner the grantee. For that deed's grantor:
Search ROD as grantee. Verify they received the property (legal description matches parcel).
If found and clean → chain settled. Mark session done.
If not found → try name variants (see below). If still not found → open an investigation_question and dig further: check for referenced prior deeds in the current deed's text, look for corrective deeds, look for multi-deed-per-page old records.
If a corrective deed appears, find what it's correcting (pull the referenced prior deed). Resolve the conflict.
Stop after max depth (default 3 hops back) or after name-variant budget is exhausted.
Phase D — Estate path (only if needed)
Run only if: current owner has no grantee deed found, OR chain terminates in a deceased owner with no subsequent deed.
Search Clerk of Superior Court by owner name for estate files. Store in court_captures.
Pull estate file, order of distribution, deed of distribution if present. Run document-read on each.
Determine acquisition path or flag as unresolved.
Phase E — Incidental gathering
Throughout Phases B-D, any document encountered that isn't a chain deed (mortgages, deeds of trust, releases, lis pendens, judgment liens, affidavits of death) gets the document-read treatment and an incidental_records row. No deep analysis, just capture + summary.
Document-read pattern (subroutine, used everywhere)
For every document the system pulls:
Download raw PDF/image. Store in rod_captures or court_captures.
Run OCR. Store text and confidence. If OCR confidence is below threshold (suggest 0.75), flag for human and stop processing this doc.
Run AI extraction to produce document_extractions row with structured fields + 1-2 sentence summary.
Run legal description match against the parcel. Record match method and confidence.
If extraction is ambiguous or low-confidence, flag.
Name variants
When a search doesn't find an expected record, try (in order, stop when found):
Middle initial variations (with and without)
Nickname swaps (Robert ↔ Bob, Joseph ↔ Joe ↔ Joey)
First/last transposition
Common surname spelling variants (Stephens ↔ Stevens)
Corporate suffix variations (Inc. ↔ Corp. ↔ Co.; 1st ↔ First)
Budget: max 5 variant attempts per name. After that, stop and log to investigation_questions as unresolved.
Stopping conditions
Chain-back clean → status=settled.
Max depth (3 hops) reached without resolution → status=flagged_for_review.
Name variants exhausted → status=flagged_for_review.
Low-OCR document central to chain → status=flagged_for_review.
Estate path returns nothing and no deed exists → status=flagged_for_review.
Hard time cap (suggest 10 min per property) → status=flagged_for_review.
AI settings
Extraction steps in document-read: moderate temperature (OCR tolerance).
Investigator agent reasoning (what to do next): low temperature.
Every fact written must cite the specific capture_id or extraction_id it came from.
Layer 3 — Conclude
Input: investigation_sessions (settled), document_extractions, incidental_records.
Output: chain_conclusions row with status=active.
AI reasoning: Yes. Temperature 0.
Steps
Identify current owner(s). Normalize names. Flag deceased status based on signals (+ symbol, "heirs" adjacent, /EST suffix, confirmed from estate records).
Identify acquisition path from the settled chain: which deed made them owner, or which estate/order of distribution.
Determine vesting using NC rules:
One grantee → sole
Two grantees with "husband and wife" or "married" language → tenancy_by_entirety
Two+ grantees with explicit "joint tenants with right of survivorship" language → jtwros
Two+ grantees without qualifying language → tenants_in_common (NC default)
Grantee is a trust → trust
Grantee is LLC/corp/entity → entity
Store vesting_evidence — the specific deed language that determined the vesting type.
Compute overall legal_description_confidence from the chain's extractions.
Copy flags from investigation into chain_conclusions.flags.
Set verify_status=pending. Write row. Update properties.chain_conclusion_id.
Supersession
If a chain_conclusion already exists for this property, set the old row's status=superseded and populate superseded_by_id on the old row. Never overwrite.
Layer 4 — Verify
Input: chain_conclusions (verify_status=pending), document_extractions. Does NOT read investigation_trace on first pass.
Output: updated chain_conclusions with verify_status=approved, objection_raised, or flagged_for_human.
AI reasoning: Yes. Different model instance / fresh prompt. Temperature 0.
Steps
Read the conclusion and all referenced document_extractions. Do NOT read investigation_trace.
Ask: does each claim in the conclusion have evidence in the extractions? What's the weakest link?
If every claim is supported → set verify_status=approved.
If a claim is weak or contradicted by extractions → set verify_status=objection_raised and populate verify_objections with structured objections (claim, evidence_against, suggested_next_step).
If the objection is fundamental or can't be resolved by more investigation → set verify_status=flagged_for_human.
Handling objections
objection_raised → orchestrator routes back to Investigate with the objection as context. Investigate tries to resolve. New conclusion supersedes old one.
flagged_for_human → case goes to a human review queue. No further automated action.
Orchestration
n8n flow
Scout node → reads property_id, runs Scout adapter, writes properties + appraiser_transfer_history, signals complete.
Investigate node → reads property_id, runs agent loop with tools (ROD search, court search, document download, OCR, extraction). Writes to all investigation tables. Signals settled or flagged.
Conclude node → reads property_id, runs conclusion prompt. Writes chain_conclusions row.
Verify node → reads chain_conclusion_id, runs verify prompt. Updates chain_conclusions.
Loopback: if Verify returns objection_raised, route back to Investigate with objection context. Max one loop per property to prevent cycles; second objection → flagged_for_human.
State handling
Every node reads from DB, writes to DB. Pass only IDs between nodes.
Raw captures are immutable once written.
Conclusions use supersession (status field + superseded_by_id), never overwrite.
Every AI-produced fact must cite its source capture_id or extraction_id.
Application-layer enforcement: reject any document_extractions insert that doesn't reference a valid capture_id.
Build order
1. Schema migrations.
2. Document-read subroutine (download + OCR + extraction + summary). Testable in isolation.
3. Scout for one county (start with Wake since we have the test case). Validate appraiser data captures correctly.
4. Investigate Phase A only. Validate it correctly verifies or flags appraiser-listed deeds.
5. Investigate Phases B and C. Test against 631 East Nelson as the regression case — if the system reconstructs the 1941/1944/1954 chain correctly, Investigate is working.
6. Investigate Phases D and E.
7. Conclude.
8. Verify.
9. Orchestration loop including Verify-to-Investigate objection routing.
10. Second county adapter to validate the adapter pattern.
Test cases to keep around
631 East Nelson Ave, Wake Forest NC — the corrective-deed case. System must reconstruct the 1941→1944→1954 chain through Phase B/C searches even if appraiser doesn't list all three deeds.
A clean modern case — one recent deed, one grantor chain-back, no complications.
An estate case — current owner deceased, no successor deed, inheritance via court records.
A cursive/handwritten deed case — tests OCR confidence thresholds and human-flag routing.
