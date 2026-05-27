import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

conns = wf.get("connections", {})

# Show what tools are connected to each agent
agents = ["Obituary Deep Diver", "Genealogist", "Vital Status Researcher", "Surname Crosser", "Title Attorney"]
for ag in agents:
    tools = []
    for src, targets in conns.items():
        for port, conn_list in targets.items():
            for conns_inner in conn_list:
                for c in conns_inner:
                    if c.get("node") == ag and c.get("type") == "ai_tool":
                        tools.append(src)
    print(f"\n{ag} tools: {tools}")

# Check for session recovery node
recovery = [n["name"] for n in wf["nodes"] if "recover" in n["name"].lower() or "stuck" in n["name"].lower()]
print(f"\nRecovery nodes: {recovery}")

# Check what connects FROM Recover Stuck Sessions
if "Heir Recover Stuck" in conns or any("recover" in k.lower() for k in conns):
    for k in conns:
        if "recover" in k.lower():
            print(f"Recovery connections: {k} -> {conns[k]}")
