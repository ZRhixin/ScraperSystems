import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

targets = ["Obituary Deep Diver", "Genealogist", "Person Compiler", "Surname Crosser", "Vital Status Researcher", "Orch - SkipGenie Result"]
for name in targets:
    node = next((n for n in wf["nodes"] if n["name"] == name), None)
    if not node:
        print(f"=== {name} --- NOT FOUND ===")
        continue
    t = node["type"].split(".")[-1]
    print(f"\n=== {name} ({t}) ===")
    params = node.get("parameters", {})
    if "jsCode" in params:
        print(params["jsCode"][:4000])
    elif "systemMessage" in params.get("options", {}):
        print(params["options"]["systemMessage"][:4000])
    elif "text" in params:
        print(str(params["text"])[:2000])
    else:
        print(json.dumps(params, indent=2)[:3000])
