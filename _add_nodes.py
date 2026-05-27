import json, sys, uuid
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

nodes = wf["nodes"]
conns = wf["connections"]

# Get positions of reference nodes for placement
court_doc_pull = next(n for n in nodes if n["name"] == "Court Document Pull")
load_ancestry_fa = next(n for n in nodes if n["name"] == "Load Ancestry Records")

cdp_pos = court_doc_pull["position"]
lar_pos = load_ancestry_fa["position"]

# -----------------------------------------------------------------------
# Node 1: Write Court Findings (tool for Title Attorney)
# -----------------------------------------------------------------------
write_cf_id = str(uuid.uuid4())
write_cf_node = {
    "id": write_cf_id,
    "name": "Write Court Findings",
    "type": "n8n-nodes-base.httpRequestTool",
    "typeVersion": 4.4,
    "position": [cdp_pos[0], cdp_pos[1] + 240],
    "parameters": {
        "toolDescription": "### Write Court Findings\n```\nPersist probate court document findings extracted from the NC courts portal.\nCall this after Court Document Pull returns results for an estate case.\nSaves the probate family tree and named persons so the Family Assembler can use them.\nRequired: session_id, property_id, person_name (the person whose estate was searched).\nInput: {\n  session_id, property_id, person_name,\n  case_number, case_url, case_type,\n  estate_filed (bool), had_will (bool|null),\n  probate_family_tree: [{name, generation, vital_status, has_issue, parent_of, notes}],\n  probate_no_issue: [name, ...],\n  named_persons: [{name, relationship, vital_status, share, address, notes}],\n  documents: (full documents array from Court Document Pull),\n  decedent_name, decedent_dod, document_type, extraction_summary\n}\nOutput: { finding_id, session_id, person_name, probate_family_tree_count, named_persons_count }\n```",
        "method": "POST",
        "url": "https://scraper.trustedheirsolutions.com/heir/write-court-findings",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={\n  \"session_id\": {{ $fromAI(\"session_id\", \"Heir research session ID\") }},\n  \"property_id\": {{ $fromAI(\"property_id\", \"Property ID\") }},\n  \"person_name\": \"{{ $fromAI(\"person_name\", \"Full name of the person whose estate was searched\") }}\",\n  \"case_number\": \"{{ $fromAI(\"case_number\", \"Court case number, e.g. 24E002839-910\") }}\",\n  \"case_url\": \"{{ $fromAI(\"case_url\", \"Register of Actions URL for the estate case\") }}\",\n  \"case_type\": \"{{ $fromAI(\"case_type\", \"E or SP\") }}\",\n  \"estate_filed\": {{ $fromAI(\"estate_filed\", \"true if estate was filed, false if not\") }},\n  \"had_will\": {{ $fromAI(\"had_will\", \"true=testate, false=intestate, null=unknown\") }},\n  \"probate_family_tree\": {{ $fromAI(\"probate_family_tree\", \"family_tree array from Court Document Pull extraction\") }},\n  \"probate_no_issue\": {{ $fromAI(\"probate_no_issue\", \"Array of names confirmed has_issue=false\") }},\n  \"named_persons\": {{ $fromAI(\"named_persons\", \"named_persons array from Court Document Pull extraction\") }},\n  \"documents\": {{ $fromAI(\"documents\", \"Full documents array from Court Document Pull\") }},\n  \"decedent_name\": \"{{ $fromAI(\"decedent_name\", \"Decedent name from the probate filing\") }}\",\n  \"decedent_dod\": \"{{ $fromAI(\"decedent_dod\", \"Date of death from the probate filing\") }}\",\n  \"document_type\": \"{{ $fromAI(\"document_type\", \"application | family_tree | other\") }}\",\n  \"extraction_summary\": \"{{ $fromAI(\"extraction_summary\", \"One sentence summary of what the document contains\") }}\"\n}",
        "options": {}
    }
}

# -----------------------------------------------------------------------
# Node 2: Load Court Findings (tool for Family Assembler)
# -----------------------------------------------------------------------
load_cf_id = str(uuid.uuid4())
load_cf_node = {
    "id": load_cf_id,
    "name": "Load Court Findings",
    "type": "n8n-nodes-base.httpRequestTool",
    "typeVersion": 4.4,
    "position": [lar_pos[0] + 240, lar_pos[1]],
    "parameters": {
        "toolDescription": "### Load Court Findings\n```\nLoad all probate court document findings saved by the Title Attorney for this session.\nCall this at the start of Family Assembler to get legally sworn family tree data.\nProbate documents are the highest-trust source for family relationships and heir status.\nInput: { session_id }\nOutput: { session_id, count, findings: [{\n  person_name, case_number, case_type,\n  probate_family_tree: [{name, generation, vital_status, has_issue, parent_of}],\n  probate_no_issue: [name],\n  named_persons: [{name, relationship, vital_status, share, address}],\n  decedent_name, decedent_dod, extraction_summary\n}]}\nKEY FIELDS:\n  probate_family_tree[].has_issue=false → confirmed no children (branch extinct — do NOT cascade)\n  probate_family_tree[].generation: 0=decedent, positive=descendants, negative=ancestors\n  named_persons[].relationship → legally stated relationship to decedent\n```",
        "method": "POST",
        "url": "https://scraper.trustedheirsolutions.com/heir/court-findings",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ { \"session_id\": $fromAI(\"session_id\", \"Heir research session ID\") } }}",
        "options": {}
    }
}

nodes.append(write_cf_node)
nodes.append(load_cf_node)

# -----------------------------------------------------------------------
# Wire Write Court Findings → Title Attorney (as ai_tool)
# -----------------------------------------------------------------------
if "Write Court Findings" not in conns:
    conns["Write Court Findings"] = {
        "ai_tool": [[{"node": "Title Attorney", "type": "ai_tool", "index": 0}]]
    }

# -----------------------------------------------------------------------
# Wire Load Court Findings → Family Assembler (as ai_tool)
# -----------------------------------------------------------------------
if "Load Court Findings" not in conns:
    conns["Load Court Findings"] = {
        "ai_tool": [[{"node": "Family Assembler", "type": "ai_tool", "index": 0}]]
    }

with open("others/heirtracer/workflow_v2.json", "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Nodes added and wired:")
print(f"  Write Court Findings (id={write_cf_id[:8]}...) → Title Attorney")
print(f"  Load Court Findings  (id={load_cf_id[:8]}...) → Family Assembler")

# Verify tool lists
for ag in ["Title Attorney", "Family Assembler"]:
    tools = [src for src, targets in conns.items()
             for port, cl in targets.items()
             for c_list in cl
             for c in c_list
             if c.get("node") == ag and c.get("type") == "ai_tool"]
    print(f"\n{ag} tools: {tools}")
