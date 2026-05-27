import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

for name in ["Worker - Prepare Item", "Orch - Prep"]:
    node = next(n for n in wf["nodes"] if n["name"] == name)
    print(f"\n=== {name} ===")
    print(node["parameters"].get("jsCode",""))

# Also show Queue Cascade Relatives full JSON body
qcr = next(n for n in wf["nodes"] if n["name"] == "Queue Cascade Relatives")
print("\n=== Queue Cascade Relatives jsonBody ===")
print(qcr["parameters"].get("jsonBody",""))
