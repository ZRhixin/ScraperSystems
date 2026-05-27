import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("others/heirtracer/workflow_v2.json", encoding="utf-8") as f:
    wf = json.load(f)

nodes = wf["nodes"]
fixes = []

# -----------------------------------------------------------------------
# FIX DEPTH: Worker - Prepare Item — add depth to output
# -----------------------------------------------------------------------
wpi = next(n for n in nodes if n["name"] == "Worker - Prepare Item")
old = """  queue_id:          item.queue_id,
  loop_context:      'worker'"""
new = """  queue_id:          item.queue_id,
  depth:             item.depth || 0,
  loop_context:      'worker'"""
if old in wpi["parameters"]["jsCode"]:
    wpi["parameters"]["jsCode"] = wpi["parameters"]["jsCode"].replace(old, new)
    fixes.append("Worker - Prepare Item: depth added")
else:
    fixes.append("ERROR: Worker - Prepare Item pattern not found")

# -----------------------------------------------------------------------
# FIX DEPTH: Orch - Prep — forward depth
# -----------------------------------------------------------------------
prep = next(n for n in nodes if n["name"] == "Orch - Prep")
old = """  queue_id: d.queue_id,
  _last: last,"""
new = """  queue_id: d.queue_id,
  depth: d.depth || 0,
  _last: last,"""
if old in prep["parameters"]["jsCode"]:
    prep["parameters"]["jsCode"] = prep["parameters"]["jsCode"].replace(old, new)
    fixes.append("Orch - Prep: depth forwarded")
else:
    fixes.append("ERROR: Orch - Prep pattern not found")

# -----------------------------------------------------------------------
# FIX DEPTH: Orch - Format Prompt — forward depth in output
# -----------------------------------------------------------------------
fmt = next(n for n in nodes if n["name"] == "Orch - Format Prompt")
old = """  queue_id: prep.queue_id,
  property_context: propertyCtx,"""
new = """  queue_id: prep.queue_id,
  depth: prep.depth || 0,
  property_context: propertyCtx,"""
if old in fmt["parameters"]["jsCode"]:
    fmt["parameters"]["jsCode"] = fmt["parameters"]["jsCode"].replace(old, new)
    fixes.append("Orch - Format Prompt: depth forwarded")
else:
    fixes.append("ERROR: Orch - Format Prompt pattern not found")

# -----------------------------------------------------------------------
# FIX DEPTH: Parse Vital Status — forward depth from context
# -----------------------------------------------------------------------
pvs = next(n for n in nodes if n["name"] == "Parse Vital Status")
old = """  queue_id:          ctx.queue_id,
  county:            prop.county"""
new = """  queue_id:          ctx.queue_id,
  depth:             ctx.depth || 0,
  county:            prop.county"""
if old in pvs["parameters"]["jsCode"]:
    pvs["parameters"]["jsCode"] = pvs["parameters"]["jsCode"].replace(old, new)
    fixes.append("Parse Vital Status: depth forwarded")
else:
    fixes.append("ERROR: Parse Vital Status pattern not found")

# -----------------------------------------------------------------------
# FIX DEPTH: Parse Surname Crosser — forward depth from vst
# -----------------------------------------------------------------------
psc = next(n for n in nodes if n["name"] == "Parse Surname Crosser")
old = """  loop_context:      vst.loop_context || 'worker',
  relationship_hint: vst.relationship_hint || '',"""
new = """  loop_context:      vst.loop_context || 'worker',
  depth:             vst.depth || 0,
  relationship_hint: vst.relationship_hint || '',"""
if old in psc["parameters"]["jsCode"]:
    psc["parameters"]["jsCode"] = psc["parameters"]["jsCode"].replace(old, new)
    fixes.append("Parse Surname Crosser: depth forwarded")
else:
    fixes.append("ERROR: Parse Surname Crosser pattern not found")

# -----------------------------------------------------------------------
# FIX DEPTH: Person Compiler — expose current_depth in output
# -----------------------------------------------------------------------
pc = next(n for n in nodes if n["name"] == "Person Compiler")
old = """  maiden_name:        scr.maiden_name || obit.maiden_name || '',
  skipgenie_deceased: orch.skipgenie_deceased,"""
new = """  current_depth:      scr.depth || orch.depth || 0,
  maiden_name:        scr.maiden_name || obit.maiden_name || '',
  skipgenie_deceased: orch.skipgenie_deceased,"""
if old in pc["parameters"]["jsCode"]:
    pc["parameters"]["jsCode"] = pc["parameters"]["jsCode"].replace(old, new)
    fixes.append("Person Compiler: current_depth added to output")
else:
    fixes.append("ERROR: Person Compiler maiden_name pattern not found")

# -----------------------------------------------------------------------
# FIX CASCADE_NEEDED: Person Compiler — probate data awareness
# -----------------------------------------------------------------------
old_cascade = "const cascade_needed = vital_status === 'deceased' && estFiled !== true;"
new_cascade = """const hasProbateData = (courtCheck.probate_family_tree || []).length > 0;
// cascade needed when: deceased AND NOT (estate was filed AND we successfully extracted the family tree)
// If estate filed but PDF pull failed (no probate_family_tree), still cascade to find heirs
const cascade_needed = vital_status === 'deceased' && !(estFiled === true && hasProbateData);"""
if old_cascade in pc["parameters"]["jsCode"]:
    pc["parameters"]["jsCode"] = pc["parameters"]["jsCode"].replace(old_cascade, new_cascade)
    fixes.append("Person Compiler: cascade_needed fixed (probate-aware)")
else:
    fixes.append("ERROR: cascade_needed pattern not found")

# -----------------------------------------------------------------------
# FIX DEPTH: Queue Cascade Relatives — pass depth+1 to server
# -----------------------------------------------------------------------
qcr = next(n for n in nodes if n["name"] == "Queue Cascade Relatives")
old_qcr = """  return {
    session_id: pc.session_id,
    property_id: pc.property_id,
    persons: (pc.cascade_relatives || [])
      .map(r => ({
        name: (r.name || '').replace(/\\s*\\(.*?\\)/g, '').trim(),
        relationship_hint: (r.relationship || 'cascade_heir').substring(0, 120)
      }))
      .filter(r => isValidName(r.name))
  };"""
new_qcr = """  const nextDepth = (pc.current_depth || 0) + 1;
  return {
    session_id: pc.session_id,
    property_id: pc.property_id,
    depth: nextDepth,
    persons: (pc.cascade_relatives || [])
      .map(r => ({
        name: (r.name || '').replace(/\\s*\\(.*?\\)/g, '').trim(),
        relationship_hint: (r.relationship || 'cascade_heir').substring(0, 120),
        depth: nextDepth
      }))
      .filter(r => isValidName(r.name))
  };"""
if old_qcr in qcr["parameters"]["jsonBody"]:
    qcr["parameters"]["jsonBody"] = qcr["parameters"]["jsonBody"].replace(old_qcr, new_qcr)
    fixes.append("Queue Cascade Relatives: depth+1 passed to server")
else:
    fixes.append("ERROR: Queue Cascade Relatives pattern not found")

with open("others/heirtracer/workflow_v2.json", "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Results:")
for f in fixes:
    print(f"  {'OK' if not f.startswith('ERROR') else 'FAIL'}: {f}")
