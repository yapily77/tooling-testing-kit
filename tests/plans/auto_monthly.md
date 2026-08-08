# 📋 Execution Plan: Automated Engine Pipeline Validation

## Objective
Validate the end-to-end automated calculation flow from raw structured inputs to narrative report generation.

## Test Setup & Data
- **Input Parameters:** Automated timestamp/metadata payload
- **Target Seam:** System input adapter converting raw payload to validated schema

## Scope & Constraints
- **Anti-Corruption Seam:** Ensure the generated data profile merges with tailoring context and converts to a valid schema.
- **Engine Core:** The internal engine must receive fully typed structures and serialize them properly for the LLM.
- **Egress:** Ensure tailoring context is physically present in the final prompt payload.

## Test Execution Steps
1. **Payload Construction & Intake:** Construct test payload and call engine ingress handler.
2. **Core Engine Validation:** Verify data schema remains valid and correctly typed across processing stages.
3. **Report & Output Generation:** Invoke the report generation pipeline and verify narrative output format.

*   **Validation:**
    *   Intercept or verify the prompt built in `src.engine.prompt_maker.make_month` contains the `tailoring_context` string.
    *   Confirm the pipeline outputs `.yaml` files showing the live LLM prompt execution.

## Autonomous Execution Strategy (Subagent Delegation)
The background subagent will execute `tests/01_gold_snapshots/02_auto/`. The script will output intermediate files demonstrating the engine's behavior. The agent will read these artifacts to confirm success.
