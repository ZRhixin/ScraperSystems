import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

# Full Person Compiler code
pc = next(n for n in wf["nodes"] if n["name"] == "Person Compiler")
print("=== Person Compiler ===")
print(pc["parameters"]["jsCode"])
print("\n\n=== Vital Status Researcher (full prompt) ===")
vsr = next(n for n in wf["nodes"] if n["name"] == "Vital Status Researcher")
print(vsr["parameters"]["options"]["systemMessage"])
