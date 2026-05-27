import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

# Verify Obituary Deep Diver
obit = next(n for n in wf["nodes"] if n["name"] == "Obituary Deep Diver")
msg = obit["parameters"]["options"]["systemMessage"]
checks = [
    ("survivors format", "FULL NAME UPPERCASE" in msg),
    ("survivors mandatory", "NEVER empty if obituary names survivors" in msg),
    ("Ancestry mandatory", "THIS STEP IS MANDATORY. YOU MUST CALL IT." in msg),
    ("max tool calls 12", "MAX TOOL CALLS: 12" in msg),
    ("step 3b exists", "STEP 3b" in msg),
]
print("=== Obituary Deep Diver ===")
for label, ok in checks:
    print(f"  {'OK' if ok else 'MISSING'}: {label}")

# Verify Orch - Format Prompt scoring
fmt = next(n for n in wf["nodes"] if n["name"] == "Orch - Format Prompt")
js = fmt["parameters"]["jsCode"]
score_checks = [
    ("out-of-state penalty", "ALL addresses are outside NC" in js),
    ("deceased+relationship bonus", "deceased=true AND relationship_hint" in js),
    ("tiebreaker NC", "TIEBREAKER" in js),
    ("living penalty", "deceased=false AND the person is expected" in js),
]
print("\n=== Orch - Format Prompt ===")
for label, ok in score_checks:
    print(f"  {'OK' if ok else 'MISSING'}: {label}")

print("\n=== Bug 3 (server-side) ===")
with open("heir/handlers.py", encoding="utf-8") as f:
    h = f.read()
print(f"  {'OK' if 'INTERVAL' in h and 'Auto-recover' in h else 'MISSING'}: auto-recover in next_person")
