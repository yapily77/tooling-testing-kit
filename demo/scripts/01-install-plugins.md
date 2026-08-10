# 🛠️ Install Demo Plugins

This guide walks through installing the three demo plugins into your project's `.opencode/plugins/` directory and registering them in your `opencode.json` configuration.

## Prerequisites

- A project with a `.opencode/` directory at its root (or create one).
- The OpenCode plugin SDK must be available in your project's `node_modules`.
- The plugin source files are located in the [`demo/opencode/`](./demo/opencode/) folder of this kit.

## Step 1 — Copy Plugin Files to `.opencode/plugins/`

Copy the required plugin TypeScript files from the kit's `demo/opencode` directory into your project's `.opencode/plugins/` folder. The kit ships the following plugins and a planned future plugin:

1. **`remind-workflow.ts`** — Injects mandatory workflow reminders into every OpenCode chat system prompt (beads task tracking, clean_python/clean_ts usage rules).
2. **`clean_python.ts`** — OpenCode plugin that delegates Python file quality checks to the `clean_py` pip package, enforcing Ruff, MyPy strict, Radon CC < 6, and AST anti-slop rules before atomic write.
3. **`clean_ts.ts`** *(planned for future release)* — Mirror plugin that delegates TypeScript file quality checks to the `clean_ts` Node CLI, enforcing tsc `--strict`, ESLint-equivalent rules, and cyclomatic complexity < 6.

```bash
# Ensure the plugins directory exists in your project
mkdir -p .opencode/plugins

# Copy the available plugins (clean_ts.ts is planned — copy when available)
cp demo/opencode/remind-workflow.ts .opencode/plugins/
cp demo/opencode/clean_python.ts .opencode/plugins/

# Planned — run when clean_ts.ts ships:
# cp demo/opencode/clean_ts.ts .opencode/plugins/
```

## Step 2 — Register Plugins in `opencode.json`

Open your project's `opencode.json` (or `.opencode/opencode.jsonc`) and add the plugin paths. If the file doesn't exist, create it with the following structure:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "./.opencode/plugins/remind-workflow.ts",
    "./.opencode/plugins/clean_python.ts",
    "./.opencode/plugins/clean_ts.ts"
  ]
}
```

> **Note:** The `clean_ts.ts` entry can be added now as a placeholder if the file is planned but not yet copied. OpenCode will emit a warning until the file exists, or you can comment it out:
> ```json
> "plugin": [
>   "./.opencode/plugins/remind-workflow.ts",
>   "./.opencode/plugins/clean_python.ts"
>   // "./.opencode/plugins/clean_ts.ts"
> ]
> ```

## Step 3 — Verify Installation

Restart your OpenCode session and check the startup log for confirmation:

```bash
opencode --version
opencode --doctor
```

You should see log lines like:

```
[Plugin] RemindWorkflowPlugin loaded for: <your-project-name>
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot find module '@opencode-ai/plugin'` | Run `npm install` in your project root. |
| Plugin not loaded at startup | Ensure the path in `opencode.json` matches the actual file location relative to the project root. |
| `clean_python.ts` references `clean_py` which is not installed | Install the pip package: `pip install clean_py` (or equivalent). |
| `clean_ts.ts` references `clean_ts` which is not installed | Install the Node CLI: `npm install clean_ts` (or equivalent, when released). |

## What's Next

After installing the plugins, see the example scripts in this directory:

- [`example-clean-script.py`](./example-clean-script.py) — A Python script that passes all quality gates (CC < 6, typed, no swallowed errors).
- [`example-clean-script.ts`](./example-clean-script.ts) — A TypeScript mirror that passes strict tsc + ESLint checks.
