import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

fa = next(n for n in wf["nodes"] if n["name"] == "Family Assembler")
prompt = fa["parameters"]["options"]["systemMessage"]

# Find the actual step pattern used
idx = prompt.find("Load Obituary Texts")
print(repr(prompt[max(0,idx-200):idx+300]))
