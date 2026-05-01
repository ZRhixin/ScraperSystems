{
  "nodes": [
    {
      "parameters": {
        "promptType": "define",
        "text": "={{ $json.body }}",
        "options": {
          "systemMessage": "You are extracting structured property data from a county property appraiser page. You are given the raw text or HTML content of one parcel's appraiser record.\n \nReturn ONLY a JSON object matching this exact structure. No markdown. No code fences. No prose before or after.\n \n{\n  \"parcel_id\": \"\",\n  \"secondary_parcel_id\": null,\n  \"property_address\": {\"street\": null, \"city\": null, \"state\": null, \"zip\": null},\n  \"county\": \"\",\n  \"current_owners\": [\n    {\"raw_name\": \"\", \"owner_order\": 1}\n  ],\n  \"short_legal_raw\": null,\n  \"short_legal_parsed\": {\"subdivision\": null, \"block\": null, \"lot\": null},\n  \"plat_book\": null,\n  \"plat_page\": null,\n  \"full_legal_description\": null,\n  \"last_sale_date\": null,\n  \"transfer_history\": [\n    {\n      \"book\": null,\n      \"page\": null,\n      \"instrument_number\": null,\n      \"recorded_date\": null,\n      \"grantor_raw\": null,\n      \"grantee_raw\": null,\n      \"short_legal_raw\": null\n    }\n  ],\n  \"extraction_notes\": []\n}\n \nRULES:\n- Preserve owner names exactly as shown. Do not normalize capitalization or punctuation.\n- If a field is not present in the source, use null.\n- transfer_history may be an empty array if no prior transfers are shown.\n- short_legal_parsed: only populate a sub-field if you can identify it with high confidence from the short_legal_raw text.\n  Example: \"Lot 19 Block 7 Country Club Estates\" → {\"subdivision\": \"Country Club Estates\", \"block\": \"7\", \"lot\": \"19\"}\n- Do not invent data. When uncertain, leave null and add a note to extraction_notes describing what was unclear.\n- Do not interpret or correct names. \"Hayes, Lydia heirs\" stays as \"Hayes, Lydia heirs\"."
        }
      },
      "type": "@n8n/n8n-nodes-langchain.agent",
      "typeVersion": 3.1,
      "position": [192, 0],
      "id": "2b4d31b3-ed3e-4b8c-afde-0c4b1020164f",
      "name": "AI Agent"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://127.0.0.1:8000/county/mecklenburg/deeds",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1600, 832],
      "id": "b43dde35-910d-490e-b961-e543e63bec17",
      "name": "Mecklenburg Deeds"
    },
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "scout",
        "responseMode": "responseNode",
        "options": {}
      },
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2.1,
      "position": [-80, 0],
      "id": "330d5e17-3d37-48cb-af1d-623f3adcb76d",
      "name": "HeirMatrix",
      "webhookId": "3743445f-5ce7-4852-af2a-fca6cb11ec83"
    },
    {
      "parameters": {
        "toolDescription": "Search Wake County property assessor by parcel ID, owner name, or address. Use this tool when county is \"wake\" and you need property details, legal description, last transfer date, and book/page of the last recorded deed. Search by parcel ID first, fall back to owner name or address if parcel returns nothing.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/county/wake/assessor",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "search_type", "value": "={{ $fromAI('search_type', 'Search mode: id (parcel ID), owner (last name), address (street name), pin') }}"},
            {"name": "real_estate_id", "value": "={{ $fromAI('real_estate_id', 'Parcel or real estate ID, used when search_type is id') }}"},
            {"name": "last_name", "value": "={{ $fromAI('last_name', 'Owner last name, used when search_type is owner') }}"},
            {"name": "first_name", "value": "={{ $fromAI('first_name', 'Owner first name, used when search_type is owner') }}"},
            {"name": "street_name", "value": "={{ $fromAI('street_name', 'Street name, used when search_type is address') }}"},
            {"name": "street_number", "value": "={{ $fromAI('street_number', 'Street number, used when search_type is address') }}"}
          ]
        },
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [448, 320],
      "id": "e3b3b8ce-7cc1-4d6a-b317-32cd89e7aa83",
      "name": "Wake Assessor"
    },
    {
      "parameters": {
        "jsCode": "const raw = $input.first().json.output;\n\n// Strip markdown code blocks if present\nconst cleaned = raw\n  .replace(/```json\\n?/g, '')\n  .replace(/```\\n?/g, '')\n  .trim();\n\n// Find the JSON object\nconst start = cleaned.indexOf('{');\nconst end = cleaned.lastIndexOf('}');\nconst jsonStr = cleaned.slice(start, end + 1);\n\nreturn [{ json: JSON.parse(jsonStr) }];"
      },
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [560, 0],
      "id": "be4b0052-4f7f-4fd0-95b2-a248f95c270f",
      "name": "Code in JavaScript"
    },
    {
      "parameters": {
        "promptType": "define",
        "text": "=Begin investigation for property_id: {{ $json.body.property_id }}",
        "options": {
          "systemMessage": "You are the Chain-of-Title Investigator for a North Carolina property.\n\nGOAL: Establish how the current owner acquired this property, and verify the chain back ONE hop — i.e., confirm that the grantor on the acquisition deed actually held title at the time of transfer. Stop once verified, or flag for human review if you cannot verify.\n\nTOOLS:\n  - Load Property State → get property, transfers, session\n  - Read Document → runs Claude extraction, returns extraction\n  - Court Search → search NC courts by name\n  - Register of Actions → get case events by case_url\n  - Court Pull → saves court case to DB\n  - Update Appraiser Verification → mark transfer verified/not_findable\n  - Log Incidental → record mortgage/lien found along the way\n  - Open Question → log unresolved gap\n  - Resolve Question → close a question\n  - Wake Deeds Search → search Wake County deeds by name or document number. Returns book/page refs. (Phase B, C only)\n  - Pull Deed → pulls deed by book/page for any county, saves to DB, returns capture_id (Phase A, B, C, E)\n  - Settle Chain → end investigation as complete\n  - Flag Review → end investigation as flagged\n\nPHASES (run in order; loop back if new findings require it):\n\nPHASE A — Verify appraiser transfer history.\nFor each appraiser_transfer_history row (verification_status = \"pending\"):\n  1. Call Pull Deed\n     { \"property_id\": <property_id>, \"county\": <property.county>, \"book\": <transfer.book>, \"page\": <transfer.page> }\n     → Returns capture_id, grantor, grantee, recording_date, doc_type\n     If 501 returned: county not yet supported — set verification_status to not_findable, move to next row.\n     If 404 returned: deed not found at that location — set verification_status to not_findable.\n  2. Call Read Document\n     { \"capture_id\": <capture_id>, \"capture_table\": \"rod_captures\", \"parcel_reference\": { \"parcel_id\": <property.parcel_id>, \"county\": <property.county> } }\n     → Returns extraction_id and structured fields\n  3. Compare extracted grantor, grantee, date, legal_match_to_parcel against the appraiser's claim.\n  4. Call Update Appraiser Verification\n     - \"verified\" if all fields match\n     - \"verified_with_discrepancy\" if deed exists but fields differ\n     - \"not_findable\" if deed not found\n\n\nPHASE B — Independent ROD search.\nUse the appropriate county search tool based on property.county.\nCurrently implemented: Wake County → use Wake Deeds Search.\nIf county has no search tool yet, skip Phase B and proceed to Phase C.\n\nIf property.county = \"wake\": use Wake Deeds Search.\nOtherwise: no search tool available for this county — skip to Phase C.\n\n1. Call Wake Deeds Search: { \"search_type\": \"name\", \"surname\": <owner_surname>, \"first_name\": <owner_first>, \"role\": \"grantee\" }\n   For every result not already captured: call Pull Deed (book, page, county, property_id) → Read Document.\n2. Repeat with role: \"grantor\".\n3. Mark any corrective/quitclaim/confirmation deed — these are signals for Phase C.\n\n\nPHASE C — Chain-back verification (one hop).\n1. Identify the acquisition deed — the most recent deed where current owner is grantee, with legal_match_to_parcel = \"high\" or \"medium\". Call this \"primary.\"\n2. If no such deed exists, jump to Phase D.\n3. Take primary's grantor(s). For each grantor:\n   a. Call Wake Deeds Search: { \"search_type\": \"name\", \"surname\": <grantor_surname>, \"first_name\": <grantor_first>, \"role\": \"grantee\" }\n      (Only if property.county = \"wake\". Otherwise skip to step 3e.)\n   b. For each result: call Pull Deed (book, page, county, property_id) → Read Document.\n   c. Look for a deed where grantor received this property (legal_match_to_parcel ≥ medium).\n   d. If found AND doc_type is a normal conveyance (warranty_deed, deed_of_distribution, etc.) → link verified. Call Settle Chain with session_id and stop_reason summarizing what was verified.\n\n      EXCEPTION — If the found deed is a corrective_deed, quitclaim, or confirmation deed:\n      These deeds are NEVER the end of a chain. They fix or clarify a prior conveyance — they do not originate one. You must find the original deed that this corrective deed refers back to.\n      i.   Note the corrective deed's grantor (the person who conveyed in the corrective deed).\n      ii.  Search for that grantor as grantee to find the original deed they received for this parcel.\n      iii. Call Wake Deeds Search: { \"search_type\": \"name\", \"surname\": <corrective_grantor_surname>, \"first_name\": <corrective_grantor_first>, \"role\": \"grantee\" }\n      iv.  For each result: call Pull Deed → Read Document.\n      v.   Look for the original deed where the corrective grantor first received this parcel (legal_match_to_parcel ≥ medium).\n      vi.  Once found, the verified chain is: [original grantor] → [corrective grantor] → (corrective deed) → [acquisition grantor] → [current owner]. Call Settle Chain summarizing the full corrective chain.\n      vii. If the original deed is not found after 5 attempts → Call Open Question describing the gap, then Call Flag Review with stop_reason \"corrective_deed_original_not_found\".\n\n   e. If NOT found → try name variants (see Name Variants section). Budget: 5 attempts.\n   f. If primary references a prior deed (references_prior_deed_book/page populated) → Call Pull Deed → Read Document on that reference. Confirm whether it is the grantor's grantee deed for this parcel.\n   g. If still unresolved → Call Open Question describing the gap, and consider going one more hop back (max depth = 3 hops).\n\n\nPHASE D — Estate path.\nTrigger if: no acquisition deed exists for current owner as grantee, OR primary is a deed_of_distribution type, OR chain terminates in a deceased owner with no subsequent deed.\n1. Call Court Search with deceased owner's name.\n2. Call Court Pull → Read Document on the estate file, order of distribution, and deed of distribution if any exist.\n3. If acquisition path is established through court records → Call Settle Chain with session_id and stop_reason summarizing the estate path.\n4. If estate records don't resolve → Call Flag Review with session_id and stop_reason: \"estate_path_unresolved\".\n\n\nPHASE E — Incidental gathering (runs throughout B-D).\nWhen name searches surface non-chain documents (deeds of trust, mortgages, releases, lis pendens, judgment liens, affidavits of death):\n- Call Pull Deed (book, page, county, property_id) → Read Document\n- Do not deeply analyze these or alter the chain logic based on them.\n\n\nNAME VARIANTS (when a search doesn't find an expected record):\nBudget: MAX 5 variant attempts per name.\nOrder:\n  1. Add or remove middle initial\n  2. Nickname substitution (Robert ↔ Bob; Joseph ↔ Joe / Joey; Catherine ↔ Kate / Cathy; William ↔ Bill; James ↔ Jim / Jimmy; Richard ↔ Dick / Rick)\n  3. First/last name transposition\n  4. Common surname spelling variants (Stephens ↔ Stevens; Smith ↔ Smyth; double letters like Ann ↔ Anne)\n  5. Corporate suffix and prefix variants (Inc. ↔ Corp. ↔ Co. ↔ LLC; 1st ↔ First; with/without \"The\")\nAfter 5 attempts without success: stop. Call Open Question describing what wasn't found. Proceed or flag based on criticality.\n\n\nSTOPPING CONDITIONS (call Flag Review with the given reason):\n- \"chain_unresolved_at_max_depth\" — walked 3 hops back without resolution\n- \"name_variants_exhausted\" — couldn't find an expected record after full variant budget\n- \"ocr_below_threshold_on_critical_document\" — a document central to the chain has extraction_confidence = \"low\"\n- \"estate_path_unresolved\" — Phase D found nothing\n- \"legal_description_mismatch_unresolvable\" — a central document doesn't match the parcel and no explanation found\n- \"corrective_deed_original_not_found\" — found a corrective deed but could not locate the original deed it corrects\n- \"time_budget_exceeded\" — 10 minutes elapsed\n\n\nDISCIPLINE:\n- Every finding cites the capture_id or extraction_id that supports it.\n- The appraiser's transfer history is a hypothesis to be verified — never assumed correct.\n- Legal descriptions are checked on every deed. A deed's name match without a legal match is not a chain link.\n- Corrective and quitclaim deeds are NEVER the end of a chain — they are evidence of a prior conveyance. Always find the deed being corrected before settling. A clean chain requires both the original deed AND the corrective deed.\n- When uncertain, flag. Do not guess.\n- Do not skip Phase C. One-hop verification is the whole point — no verification, no settlement.\n\nCall either Settle Chain or Flag Review exactly once to end the investigation.",
          "maxIterations": 50
        }
      },
      "type": "@n8n/n8n-nodes-langchain.agent",
      "typeVersion": 3.1,
      "position": [1408, 0],
      "id": "809ff187-33a8-4b32-a61d-0be62610f3e3",
      "name": "AI Agent1"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://127.0.0.1:8000/scout/write",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ $json }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.4,
      "position": [800, 304],
      "id": "474743d9-cb0c-4832-bb6a-532ceded6539",
      "name": "HTTP Request"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://127.0.0.1:8000/county/buncombe/deeds",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1600, 576],
      "id": "bc64796e-4254-45a6-947e-61e4b97c722d",
      "name": "Buncombe Deeds"
    },
    {
      "parameters": {
        "options": {}
      },
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.5,
      "position": [816, 0],
      "id": "74d2d0c0-8362-4b18-b479-d2c7aa5b1508",
      "name": "Respond to Webhook"
    },
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "investigate",
        "options": {}
      },
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2.1,
      "position": [1120, 0],
      "id": "8b9910da-4080-42b6-9546-3949c41cbc5d",
      "name": "HeirMatrix1",
      "webhookId": "92ca12ff-d26b-429f-839a-201142ad6093"
    },
    {
      "parameters": {
        "toolDescription": "Call this first at the start of every investigation. Returns the property details, all appraiser transfer history rows, all prior document extractions, and the investigation session. Required: property_id (integer).",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/property-state",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2384, 576],
      "id": "1c9d7495-bac6-4e13-b9c4-c963bbd42573",
      "name": "Load Property State"
    },
    {
      "parameters": {
        "toolDescription": "Search NC Clerk of Superior Court by party name. Use for Phase D estate path when current owner is deceased and no deed exists. Required: name (full name or last name). Optional: county.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/court/nc/search",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "name", "value": "={{ $fromAI('name', 'Full name or last name to search, e.g. HAYES or HAYES, LYDIA') }}"},
            {"name": "county", "value": "={{ $fromAI('county', 'County name to filter results, leave empty for statewide search') }}"}
          ]
        },
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1952, 320],
      "id": "662d1b0d-631a-468c-b9b5-6d4fe158d681",
      "name": "Court Search"
    },
    {
      "parameters": {
        "toolDescription": "Get all events for a specific court case and returns the foreclosure stage. Call after court search when you need to inspect a case in detail. Required: case_url (from the search results).",
        "method": "POST",
        "url": "http://127.0.0.1:8000/court/nc/register_of_actions",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2160, 320],
      "id": "6bfd73de-caf1-43ba-9695-8fe999394f32",
      "name": "Register of Actions"
    },
    {
      "parameters": {
        "toolDescription": "Runs Claude extraction on a saved PDF capture. Call this after Pull Deed with the returned capture_id. Returns structured deed fields: grantor, grantee, document type, vesting language, legal description, flags. Required: capture_id, capture_table (rod_captures or court_captures), parcel_reference (object with parcel_id and county).",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/read-document",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1952, 576],
      "id": "caea04e3-d4ea-4082-a164-ba1fe4cd724f",
      "name": "Read Document"
    },
    {
      "parameters": {
        "toolDescription": "Saves a court case to the database. Call this after court search when you want to permanently record a case for this property. Required: property_id, case_url. Optional: court_case_number, document_type, case_data (the full case object from search results).",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/court-pull",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2384, 320],
      "id": "6f129cac-f298-4bd2-8f5c-b9f1b7d6431d",
      "name": "Court Pull"
    },
    {
      "parameters": {
        "toolDescription": "Marks an appraiser transfer history row as verified, verified_with_discrepancy, or not_findable after you have attempted to find and read the deed. Call this for every transfer row in Phase A. Required: transfer_id, verification_status. Optional: verification_notes.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/update-appraiser-verification",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1968, 848],
      "id": "56bb8ae8-45e8-49c3-b6a9-da816b2cd43f",
      "name": "Update Appraiser Verification"
    },
    {
      "parameters": {
        "toolDescription": "Records a non-chain document found during investigation such as a mortgage, deed of trust, lien, release, or lis pendens. Required: property_id, extraction_id, record_type, summary.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/log-incidental",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2176, 848],
      "id": "941d2fd4-2958-4aa1-a158-e29f126a446e",
      "name": "Log Incidental"
    },
    {
      "parameters": {
        "toolDescription": "Records an unresolved question you are actively investigating. Call when you encounter a gap or discrepancy you cannot immediately answer. Required: session_id, question.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/open-question",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2400, 848],
      "id": "d4531356-6d09-4cc4-9d10-aac8d7655376",
      "name": "Open Question"
    },
    {
      "parameters": {
        "toolDescription": "Closes an open question. Call once you have an answer or have exhausted all avenues. Required: question_id, resolution (resolved / unresolved_flagged / abandoned). Optional: resolution_notes, actions_taken (list).",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/resolve-question",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1968, 1024],
      "id": "6e5f8f43-09f9-43e5-9fef-414cc240a84a",
      "name": "Resolve Question"
    },
    {
      "parameters": {
        "toolDescription": "Marks the investigation as complete and settled. Call only when the full chain of title is verified and clean with no open questions. Required: session_id. Optional: stop_reason.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/settle-chain",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2176, 1024],
      "id": "264db196-5459-4596-bef6-0eee3f9d4618",
      "name": "Settle Chain"
    },
    {
      "parameters": {
        "toolDescription": "Marks the investigation as flagged for human review. Call when you encounter something you cannot resolve — missing deeds, conflicting ownership, probate without a deed of distribution, or any serious title defect. Required: session_id. Optional: stop_reason.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/flag-review",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2400, 1024],
      "id": "1d061162-2328-42f9-9d58-cf2ec02c9d7f",
      "name": "Flag Review"
    },
    {
      "parameters": {
        "toolDescription": "Pull a deed from the county Register of Deeds by book and page. Internally searches, downloads the PDF, and saves it to the database. The agent never handles PDF bytes. Returns capture_id, doc_id, grantor, grantee, recording_date, and doc_type.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/investigate/pull-deed",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [2128, 576],
      "id": "a7295821-4886-44b5-9658-7d53f0153baa",
      "name": "Pull Deed"
    },
    {
      "parameters": {
        "toolDescription": "Search Wake County Register of Deeds by name or document number. Use this for Phase B and C name searches — NOT for pulling a deed by book/page (use Pull Deed for that).\n\n  For name search:\n  { \"search_type\": \"name\", \"surname\": \"HAYES\", \"first_name\": \"LYDIA\", \"role\": \"grantee\" }\n  role options: grantor | grantee | both\n\n  For document number search:\n  { \"search_type\": \"document\", \"document_number\": \"004714-00624\" }\n\n  Returns a list of results with book, page, doc_type, grantor, grantee, recording_date.\n  After getting results, pass book and page to Pull Deed to download and save the deed.",
        "method": "POST",
        "url": "http://127.0.0.1:8000/county/wake/deeds",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($fromAI(\"body\")) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequestTool",
      "typeVersion": 4.4,
      "position": [1584, 320],
      "id": "75548e7a-0f57-4cbe-ad6a-ebb68c78af22",
      "name": "Wake Deeds"
    },
    {
      "parameters": {
        "jsCode": "const raw = $input.first().json.output;\n\n// Strip markdown code blocks if present\nconst cleaned = raw\n  .replace(/```json\\n?/g, '')\n  .replace(/```\\n?/g, '')\n  .trim();\n\n// Find the JSON object\nconst start = cleaned.indexOf('{');\nconst end = cleaned.lastIndexOf('}');\nconst jsonStr = cleaned.slice(start, end + 1);\n\nreturn [{ json: JSON.parse(jsonStr) }];"
      },
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [1824, 0],
      "id": "67598dfb-4b98-46c1-82f6-43fec72c2ef5",
      "name": "Code in JavaScript1"
    },
    {
      "parameters": {
        "model": {
          "__rl": true,
          "value": "gpt-4o-mini",
          "mode": "list",
          "cachedResultName": "gpt-4o-mini"
        },
        "builtInTools": {},
        "options": {}
      },
      "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
      "typeVersion": 1.3,
      "position": [1232, 704],
      "id": "7f0bebc9-1f54-451f-9bb1-468368018964",
      "name": "GPT1",
      "credentials": {
        "openAiApi": {
          "id": "EmOJQUYtxTbgAwVZ",
          "name": "OpenAI account"
        }
      }
    },
    {
      "parameters": {
        "model": {
          "__rl": true,
          "value": "gpt-4o-mini",
          "mode": "list",
          "cachedResultName": "gpt-4o-mini"
        },
        "builtInTools": {},
        "options": {}
      },
      "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
      "typeVersion": 1.3,
      "position": [80, 720],
      "id": "6bfcf6e6-adce-4d0e-8f57-7b4dfec95412",
      "name": "GPT",
      "credentials": {
        "openAiApi": {
          "id": "EmOJQUYtxTbgAwVZ",
          "name": "OpenAI account"
        }
      }
    }
  ],
  "connections": {
    "AI Agent": {
      "main": [[{"node": "Code in JavaScript", "type": "main", "index": 0}]]
    },
    "Mecklenburg Deeds": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "HeirMatrix": {
      "main": [[{"node": "AI Agent", "type": "main", "index": 0}]]
    },
    "Wake Assessor": {
      "ai_tool": [[{"node": "AI Agent", "type": "ai_tool", "index": 0}]]
    },
    "Code in JavaScript": {
      "main": [
        [
          {"node": "HTTP Request", "type": "main", "index": 0},
          {"node": "Respond to Webhook", "type": "main", "index": 0}
        ]
      ]
    },
    "AI Agent1": {
      "main": [[{"node": "Code in JavaScript1", "type": "main", "index": 0}]]
    },
    "Buncombe Deeds": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "HeirMatrix1": {
      "main": [[{"node": "AI Agent1", "type": "main", "index": 0}]]
    },
    "Load Property State": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Court Search": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Register of Actions": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Read Document": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Court Pull": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Update Appraiser Verification": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Log Incidental": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Open Question": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Resolve Question": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Settle Chain": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Flag Review": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Pull Deed": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "Wake Deeds": {
      "ai_tool": [[{"node": "AI Agent1", "type": "ai_tool", "index": 0}]]
    },
    "GPT": {
      "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
    },
    "GPT1": {
      "ai_languageModel": [[{"node": "AI Agent1", "type": "ai_languageModel", "index": 0}]]
    }
  },
  "meta": {
    "templateCredsSetupCompleted": true,
    "instanceId": "6d0b8cd805b0ccd8f9a7ce01e1e8c3ab67814ea806cdb5ce9b11b019590d82b4"
  }
}
