import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)
nodes = {n["name"]: n for n in wf["nodes"]}
def get_text(name):
    n = nodes[name]
    return n["parameters"].get("jsCode","") + n["parameters"].get("jsonBody","") + n["parameters"].get("options",{}).get("systemMessage","")

checks = [
    ("Worker - Prepare Item",    "depth: item.depth"),
    ("Orch - Prep",              "depth: d.depth"),
    ("Orch - Format Prompt",     "depth: prep.depth"),
    ("Parse Vital Status",       "depth:             ctx.depth"),
    ("Parse Surname Crosser",    "depth:             vst.depth"),
    ("Person Compiler",          "current_depth:"),
    ("Person Compiler",          "hasProbateData"),
    ("Person Compiler",          "!(estFiled === true && hasProbateData)"),
    ("Queue Cascade Relatives",  "nextDepth"),
    ("Queue Cascade Relatives",  "depth: nextDepth"),
]
for node_name, search in checks:
    found = search in get_text(node_name)
    print(f"  {'OK' if found else 'MISSING'}: [{node_name}] {search}")
