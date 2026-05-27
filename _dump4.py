import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)
node = next(n for n in wf["nodes"] if n["name"] == "Obituary Deep Diver")
print(node["parameters"]["options"]["systemMessage"])
