import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

fa = next(n for n in wf["nodes"] if n["name"] == "Family Assembler")

old_step = "STEP 3 — Load full obituary texts\nCall Load Obituary Texts with the session_id."
new_step = """STEP 2b — Load Court Findings (MANDATORY — highest-trust source)
Call Load Court Findings with the session_id BEFORE any relationship mapping.
Returns probate_family_tree data from legally sworn court filings.
For each finding:
  - probate_family_tree[].has_issue=false → branch confirmed extinct (no children — skip cascade)
  - probate_family_tree[].has_issue=true  → confirmed has children
  - probate_family_tree[].generation: 0=decedent, positive=descendants, negative=ancestors
  - named_persons[].relationship → legally stated relationship to decedent
A relationship stated in a probate filing OVERRIDES anything inferred from obituaries or Ancestry.
A name spelled in a probate filing is the AUTHORITATIVE spelling — prefer it over SkipGenie variants.

STEP 3 — Load full obituary texts
Call Load Obituary Texts with the session_id."""

if old_step in fa["parameters"]["options"]["systemMessage"]:
    fa["parameters"]["options"]["systemMessage"] = fa["parameters"]["options"]["systemMessage"].replace(old_step, new_step)
    print("Family Assembler: Load Court Findings step added")
else:
    print("ERROR: still not found")

with open("others/heirtracer/workflow_v2.json", "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)
print("Saved.")
