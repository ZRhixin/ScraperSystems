import re, json

html = open("court/nc/results_sample.html").read()
m = re.search(r'"data"\s*:\s*\{\s*"Data"\s*:\s*(\[)', html)
if not m:
    print("No data found")
    raise SystemExit()

depth = 0
start = m.start(1)
for i in range(start, len(html)):
    if html[i] == "[":
        depth += 1
    elif html[i] == "]":
        depth -= 1
        if depth == 0:
            raw = html[start:i+1]
            break

parties = json.loads(raw)
if parties and parties[0].get("CaseResults"):
    case = parties[0]["CaseResults"][0]
    for k, v in case.items():
        print(f"{k}: {str(v)[:120]}")
else:
    print("No CaseResults found")
    print("Keys:", list(parties[0].keys()) if parties else "empty")
