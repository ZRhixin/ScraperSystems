import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

checks = [
    ("Person Compiler", "probate", "cascade_from_probate"),
    ("Person Compiler", "fuzzy dedup", "fuzzyMatch"),
    ("Person Compiler", "probate source tag", "'source: '\"'\"'probate'"),
    ("Vital Status Researcher", "legal name trust", "LEGAL RECORD NAME TRUST"),
    ("Vital Status Researcher", "first 3 letters rule", "first 3+ letters"),
    ("Orch - Format Prompt", "legal name note", "LEGAL RECORD NAMES"),
    ("Orch - Format Prompt", "3-letter match example", "Johnie=John"),
]

nodes = {n["name"]: n for n in wf["nodes"]}
for node_name, label, search in checks:
    node = nodes.get(node_name, {})
    params = node.get("parameters", {})
    text = params.get("jsCode", "") + params.get("options", {}).get("systemMessage", "")
    # Handle the escaped quote trick
    search_clean = search.replace("'\"'\"'", "'")
    found = search_clean in text
    print(f"  {'OK' if found else 'MISSING'}: [{node_name}] {label}")
