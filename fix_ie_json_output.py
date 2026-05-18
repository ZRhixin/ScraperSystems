import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('others/heirtracer/workflow_skeleton.json', encoding='utf-8') as f:
    wf = json.load(f)

for n in wf['nodes']:
    if n['name'] == 'Intestate Expert':
        sm = n['parameters']['options']['systemMessage']

        # Prepend the mandatory JSON rule at the very top
        prefix = (
            'MANDATORY OUTPUT RULE — READ THIS FIRST:\n'
            'Your ENTIRE response must be a single raw JSON object.\n'
            'Start your response with "{". End your response with "}".\n'
            'NO markdown. NO analysis text. NO headers. NO code fences. NO explanation before or after the JSON.\n'
            'Do your reasoning internally. Only the final JSON object goes in your response.\n'
            'If you write even one word outside the JSON braces, the downstream system breaks.\n'
            '\n'
        )
        if not sm.startswith('MANDATORY'):
            n['parameters']['options']['systemMessage'] = prefix + sm
            print('Prepended mandatory JSON rule to Intestate Expert')

        # Also reduce maxIterations to prevent token bloat
        if 'maxIterations' not in n['parameters'].get('options', {}):
            n['parameters']['options']['maxIterations'] = 5
            print('Set maxIterations = 5')

        break

with open('others/heirtracer/workflow_skeleton.json', 'w', encoding='utf-8') as f:
    json.dump(wf, f, ensure_ascii=False, indent=2)

print('File saved')
