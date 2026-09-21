model: "datarobot/anthropic/claude-sonnet-4-6"
llm_deployment_id: ""

system_prompt: |
  You are the Clinical Data Integrity Agent. Your job is to review encounters that a
  Snowflake Cortex detection process has flagged because the diagnosis code on file does
  not appear to match the clinical documentation, and to draft a correction for a human
  coder to review.

  You operate as a governed, human-in-the-loop workflow. You NEVER write a correction back
  to the system of record on your own. A qualified human coder must explicitly approve,
  override, or reject every suggestion before anything is written. This human approval gate
  is the entire point of the workflow — treat it as non-negotiable.

  For each flagged encounter, follow this process:
  1. Read the on-file diagnosis code, its description, and the clinical note excerpt.
  2. Use the terminology lookup tool to resolve the correct code. The tool tells you whether
     the fix REPLACES the on-file code with the correct one, or ADDS a missing secondary code
     that the documentation supports.
  3. Explain, in plain language a non-technical reviewer can follow, WHY the on-file code and
     the clinical documentation disagree — quote or paraphrase the specific wording in the note
     that drives the correction. Make the mismatch concrete, not abstract.
  4. State the suggested code, its description, and a confidence level, and be explicit about
     whether this is a replacement or an added secondary code.
  5. Hand the suggestion to the human coder for review. Stop there. Do not write anything back.

  Your rationale text will be read aloud to a mixed clinical and business audience, so it must
  be clear, specific, and free of jargon while remaining clinically accurate. Prefer concrete
  statements grounded in the note text over generic phrasing.

  Note for transparency: the terminology lookup in this workflow is a stand-in for a live
  licensed clinical terminology service. Do not present it as a live production terminology
  system.

tools:
  - function_name: get_flagged_encounters
    inputs: []
    out:
      - arg_name: flagged_encounters
        type: list
        object_schema: "list of encounter dicts: patient_id, encounter_id, encounter_date, diagnosis_code, diagnosis_description, clinical_note_excerpt, flag_reason, status"
    auth_spec:
      service_name: "Snowflake (Snowflake-Labs MCP, streamable_http transport)"
      auth_method: bearer_token

  - function_name: lookup_correct_code
    inputs:
      - arg_name: diagnosis_code
        type: str
      - arg_name: clinical_note_excerpt
        type: str
    out:
      - arg_name: suggestion
        type: dict
        object_schema: "action (replace | add_secondary), suggested_code, suggested_description, rationale, confidence"

  - function_name: write_back_correction
    inputs:
      - arg_name: encounter_id
        type: str
      - arg_name: approved_code
        type: str
      - arg_name: approver
        type: str
      - arg_name: rationale
        type: str
    out:
      - arg_name: result
        type: dict
        object_schema: "status, audit_log_entry (id, encounter_id, approved_code, approved_by, approved_at, rationale)"
    auth_spec:
      service_name: "Snowflake (Snowflake-Labs MCP, streamable_http transport)"
      auth_method: bearer_token

examples:
  - "Show me the flagged encounters that need review."
  - "For encounter ENC-1004, what does the documentation say and what code do you suggest?"
  - "Why does the diagnosis code on file not match the clinical note for this encounter?"
  - "I approve the suggested correction for ENC-1004 — write it back and log who approved it."

frontend:
  type: "multi-page"
  pages:
    - "Flagged Encounters (list) - sortable/filterable table of flagged encounters with patient_id, encounter_id, on-file code, flag_reason, and status"
    - "Encounter Review (detail) - shows current code + description, clinical note excerpt, agent's suggested code + rationale + confidence, and Approve / Override with manual code / Flag for further review actions"
    - "Audit Trail - shows the audit_log entries created by write-backs (who approved what, when, and why)"
  requirements: |
    Streamlit-based DataRobot Custom Application, aiming for a mental model similar to
    Streamlit-in-Snowflake for a familiar audience.

    The Approve action triggers write_back_correction and must visibly surface the audit_log
    entry that was just created (who approved what, when, why) — this "you can see exactly what
    happened and who approved it" moment is the core of the governance story and must not be
    buried. Override lets the coder supply a manual code before approving; Flag for further
    review records the encounter as needing more attention without writing a code correction.

# ---------------------------------------------------------------------------
# Architecture & build notes (not part of the runtime schema; captured here so
# the coding phase honors the brief's decisions)
# ---------------------------------------------------------------------------
architecture:
  framework: langgraph
  graph_shape: "fetch -> lookup -> draft rationale/confidence -> human-approval interrupt (pause) -> write-back"
  approval_gate: "explicit LangGraph interrupt/pause node; agent never writes back without human approval"
  snowflake:
    mcp_server: "Snowflake-Labs/mcp (self-hosted alongside the agent)"
    mcp_bridge: "langchain-mcp-adapters MultiServerMCPClient loads MCP tools into LangGraph"
    transport: "streamable_http (preferred over stdio for a deployed Custom Application)"
    account_identifier: "hyjszhg-ex34549"
    account_url: "https://hyjszhg-ex34549.snowflakecomputing.com"
    warehouse: "DEMO_WH"
    database_schema: "CSE_DEMO.WORKSHOP"
    objects: "encounters table, audit_log table, flagged_encounters view"
    not_using: "Snowflake native/managed MCP (CREATE MCP SERVER) and Cortex Agent — plain SQL read/write only"
    setup_sql: "snowflake_free_trial_setup.sql (creates warehouse, schema, tables, view, loads 22 encounters)"
  jsl_lookup:
    kind: "stand-in for licensed JSL terminology server"
    read_path: "SELECT * FROM jsl_stand_in_lookup (Snowflake, system of record); keyword-match clinical_note_excerpt against match_keywords in Python"
    local_fallback: "jsl_stand_in_lookup.json, opt-in via USE_LOCAL_SQLITE (same toggle as data_layer) — not the default read path"
    returns: "action/suggested_code/suggested_description/rationale/confidence"
  write_back:
    method: "UPDATE encounters (status, approved_code, approved_by, approved_at) + INSERT INTO audit_log; MERGE acceptable"
    note: "the write-back is the demo's hinge — rehearse it explicitly and repeatedly"

credentials:
  snowflake_pat:
    env_var: "SNOWFLAKE_PAT"
    handling: "credential-type runtime parameter via DataRobot Shared Secure Configuration"
    infra: "register in infra/infra/agent.py following DATAROBOT_KEY pattern; add key to _RUNTIME_PARAM_KEYS in custom.py"
    credential_dict_variants: "handle apiToken / api_token / password / value — do not assume a single key"
    local_dev: "run via 1Password: op run --env-file=.env -- <command>; no plaintext PAT in .env"

build_prerequisites:
  data_files_to_stage:
    - "encounters.csv (22 synthetic encounters: 16 clean + 6 flagged)"
    - "jsl_stand_in_lookup.json (6 keyword-matching rules, one per flagged encounter)"
    - "demo.db (SQLite scratch copy for local iteration; NOT the system of record)"
    - "generate_demo_data.py (regeneration helper)"
    - "snowflake_free_trial_setup.sql (Snowflake object + data setup)"
  note: "User will stage these into the project root before coding."

pre_build_confirmations:
  - "Confirm agentic capabilities are enabled in the demo tenant (premium feature — do not assume)."
  - "Smoke-test Snowflake-Labs/mcp against the trial account with one SQL tool call, end to end, before building the graph."

non_goals:
  - "No live JSL API call."
  - "No production security hardening (demo tenant only)."
  - "No RCM / prior-auth extension."
  - "No live Cortex ML/LLM detection — flags are pre-computed from the synthetic dataset."
  - "No deploy-time claims."
