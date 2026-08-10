# Case Specification: Generate New TS Script Test (`demo/opencode/typescript/case_generate.md`)

## Goal
Test whether the subagent autonomously adheres to `clean_ts` quality rules (AST anti-slop, ESLint strict, TSC strict typing, and ts/complexity < 6) when given a **minimal, natural user prompt** to write a brand-new script from scratch.

---

## Candidate Prompt to Send to Subagent

```text
Write a TypeScript script `generate_report.ts` that reads JSON test logs from a directory, calculates statistics (total tests, pass/fail counts, average execution time, and error distribution), and outputs a formatted Markdown summary report. Make sure it includes robust error handling and CLI argument parsing.
```

---

## Expected Autonomous Behavior

1. **Tool Usage**:
   - The subagent must use the `clean_ts` tool (`verify_and_commit_code`) to create `generate_report.ts`.
   - Must NOT use standard `write` or `edit` tools for `.ts` files.


2. **Quality Enforcement**:
   - **ts/complexity**: All functions must have Cyclomatic Complexity < 6 (eslint `[[2, 5]]`).
   - **TSC Strict**: `tsc --strict` + `@typescript-eslint` parser strict — full type annotations (`Record<string, unknown>`, `string[]`, `number`, explicit return types).
   - **AST Anti-Slop**: No `try { ... } catch (e) { /* nothing */ }` or swallowed `catch` blocks (eslint `no-empty`, `no-useless-catch`).
   - **ESLint**: `eslint:recommended` + `@typescript-eslint/recommended` strict (explicit-function-return-type, no-explicit-any, no-unused-vars, etc.).

---

## Instructions for User

Please review this proposed test case. If approved, reply to deploy the subagent to execute this prompt!

---

## Rationale: Why This Use Case Demonstrates Plugin & Tool Effectiveness

### 1. The Monolithic Function Trap (High Cyclomatic Complexity)
When asked to build a utility script handling CLI parsing, directory scanning, JSON parsing, statistics aggregation, and Markdown formatting, **an LLM's natural instinct is to write a single monolithic function** (`main()`).

Without CC enforcement, standard LLMs generate nested loops + conditionals + inline formatting in one block, resulting in Cyclomatic Complexity **CC = 8–14**.

### 2. "Slop" Error Handling (Swallowed try/catch)
When prompted for "robust error handling", standard LLMs fall back on bad habits:
- Swallowing exceptions: `try { ... } catch (e) {}` with no handling or logging.
- Catch-all wrappers that hide underlying structure.

AST anti-slop policies strictly forbid swallowing broad exceptions without handling or logging.

### 3. Missing or Loose Type Annotations (TSC Strict Failure)
Parsing dynamic JSON data into statistics requires handling nested objects and optional fields.
- **Standard LLM approach**: Omits type annotations or uses unhelpful types like `function processFile(data: Record<any, any>)`.
- **Strict TSC requirement**: Requires explicit parameter types (`Record<string, unknown>`), explicit return types, guard checks (`if (typeof x !== "number")`), and non-null handling. Most models skip this extra effort unless forced.

### 4. How `remind-workflow` & `clean_ts` Prevent Slop
- **Continuous Prompt Injection**: The `remind-workflow` plugin keeps the `clean_ts` requirement in active memory on every turn, preventing tool drift.
- **Correct-by-Construction Gating**: `clean_ts` intercepts write payloads before they reach disk. If the LLM attempts to generate a monolithic function (CC >= 6) or loose types, `clean_ts` rejects the file and returns exact diagnostic errors, forcing the model to modularize the code into clean helper functions on the first try.

---

## Generate: find_bad_style.ts
