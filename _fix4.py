import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

nodes = wf["nodes"]

# -----------------------------------------------------------------------
# Update Title Attorney — add Write Court Findings step after Task 3
# -----------------------------------------------------------------------
ta = next(n for n in nodes if n["name"] == "Title Attorney")
old_ta_task3 = """## TASK 3 — PROBATE COURT DOCUMENT PULL
If Court Search returns a case with case_type 'E' (Estate) or 'SP' (Special Proceedings):
  1. Call Court Document Pull with the register_of_actions_url from that case result.
     The URL looks like: https://portal-nc.tylertech.cloud/app/RegisterOfActions/?id=...
     Pass it as the 'url' parameter to Court Document Pull.
  2. The extraction returns a family_tree array with has_issue per person:
     - has_issue=false → confirmed no children (branch extinct — extremely valuable)
     - has_issue=true  → confirmed has children
     - has_issue=null  → not stated in document
  3. Add a note to your output: 'probate_document_pulled: true' and include key
     has_issue=false findings in your notes field.
  4. If the endpoint returns an error or documents: [], skip silently.

Include probate findings in your OUTPUT:
  court_check.probate_family_tree: the family_tree array from the extraction (or [] if none)
  court_check.probate_no_issue: array of names confirmed has_issue=false"""

new_ta_task3 = """## TASK 3 — PROBATE COURT DOCUMENT PULL
If Court Search returns a case with case_type 'E' (Estate) or 'SP' (Special Proceedings):
  1. Call Court Document Pull with the register_of_actions_url from that case result.
     The URL looks like: https://portal-nc.tylertech.cloud/app/RegisterOfActions/?id=...
     Pass it as the 'url' parameter to Court Document Pull.
  2. The extraction returns a family_tree array with has_issue per person:
     - has_issue=false → confirmed no children (branch extinct — extremely valuable)
     - has_issue=true  → confirmed has children
     - has_issue=null  → not stated in document
  3. Call Write Court Findings to persist the probate data. Pass:
     - session_id and property_id (from your input context)
     - person_name: the name of the person being researched
     - case_number, case_url, case_type from the Court Search result
     - estate_filed: true, had_will: true/false/null based on case type
     - probate_family_tree: the family_tree array from the extraction
     - probate_no_issue: array of names where has_issue=false
     - named_persons: the named_persons array from the extraction
     - documents: the full documents array
     - decedent_name, decedent_dod: from the first document's extraction
     - extraction_summary: one sentence describing what was found
  4. Add a note to your output: 'probate_document_pulled: true' and include key
     has_issue=false findings in your notes field.
  5. If Court Document Pull returns an error or documents: [], still call Write Court Findings
     with estate_filed: true and empty arrays, so Family Assembler knows the pull was attempted.

Include probate findings in your OUTPUT:
  court_check.probate_family_tree: the family_tree array from the extraction (or [] if none)
  court_check.probate_no_issue: array of names confirmed has_issue=false"""

old_prompt = ta["parameters"]["options"]["systemMessage"]
if old_ta_task3 in old_prompt:
    ta["parameters"]["options"]["systemMessage"] = old_prompt.replace(old_ta_task3, new_ta_task3)
    print("Title Attorney: Write Court Findings step added to Task 3")
else:
    print("ERROR: Title Attorney Task 3 pattern not found")

# -----------------------------------------------------------------------
# Update Family Assembler — add Load Court Findings as a required step
# -----------------------------------------------------------------------
fa = next(n for n in nodes if n["name"] == "Family Assembler")
fa_prompt = fa["parameters"]["options"]["systemMessage"]

old_fa_step = """  2. **Load Obituary Texts** (HTTP POST `/heir/obituary-text` with session_id)"""
new_fa_step = """  2. **Load Court Findings** (MANDATORY — call before any other analysis)
     Call Load Court Findings with session_id.
     This returns probate_family_tree data from legally sworn court filings — the highest-trust source.
     For each finding:
       - probate_family_tree[].has_issue=false → branch confirmed extinct (no children, no cascade)
       - probate_family_tree[].generation: 0=decedent, positive=descendants, negative=ancestors
       - named_persons[].relationship → legally stated relationship to decedent
     Use these findings as AUTHORITATIVE when mapping relationships. A relationship stated in a
     probate filing overrides anything inferred from obituaries or Ancestry records.
  3. **Load Obituary Texts** (HTTP POST `/heir/obituary-text` with session_id)"""

if old_fa_step in fa_prompt:
    fa["parameters"]["options"]["systemMessage"] = fa_prompt.replace(old_fa_step, new_fa_step)
    print("Family Assembler: Load Court Findings step added")
else:
    print("ERROR: Family Assembler step pattern not found")
    # Show context around where it should be
    idx = fa_prompt.find("Load Obituary Texts")
    print(f"  Context: {repr(fa_prompt[max(0,idx-50):idx+100])}")

with open("others/heirtracer/workflow_v2.json", "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)
print("\nworkflow_v2.json saved.")
