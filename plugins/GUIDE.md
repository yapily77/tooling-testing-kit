# 🧭 kit-plugins Guide — Install, Configure & Run

> **Step-by-step guide for installing and using `clean_py`, `clean_ts`, and OpenCode wrappers.**

---

## 1. Prerequisites

| Requirement | Supported Version | Purpose |
|---|---|---|
| Python | 3.11+ (3.14 recommended) | `clean_py` runtime, Ruff, MyPy, Radon |
| Node.js | 18+ | `clean_ts` runtime, TypeScript compiler |
| `tsc` | bundled with TypeScript | Strict type-checking subprocess |
| `uv` | latest | Python dependency management (recommended) |

---

## 2. Install `clean_py`

1. Navigate to the Python plugin directory:

```bash
cd plugins/python
```

2. Install the package in editable mode:

```bash
pip install -e .
```

3. Verify the CLI is available:

```bash
clean_py --help
```

---

## 3. Configure `clean_ts`

1. Navigate to the TypeScript plugin directory:

```bash
cd plugins/typescript/clean_ts
```

2. Install Node dependencies:

```bash
npm install
```

3. Build the CLI (compiles `src/*.ts` to `dist/`):

```bash
npm run build
```

4. Verify the CLI is available:

```bash
clean_ts --help
```

### TypeScript Strict Configuration

`clean_ts` uses the bundled `tsconfig.json` with strict mode enabled by default. The enforced compiler options include:

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "noImplicitOverride": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "skipLibCheck": true,
    "outDir": "./dist",
    "rootDir": "./src"
  }
}
```

### ESLint Configuration

The `eslint.config.ts` mirrors `clean_py`'s Ruff + MyPy strict rules:

```toml
# ESLint rule mapping (eslint.config.ts)
- @typescript-eslint/no-explicit-any      # Ruff: no-explicit-any
- @typescript-eslint/no-unused-vars       # Ruff: unused variables
- import/order                            # Ruff: import ordering
- @typescript-eslint/no-unsafe-assignment # MyPy strict
- @typescript-eslint/no-unsafe-member-access
- @typescript-eslint/no-unsafe-call
- complexity: ["error", 5]                # Radon CC equivalent
- @typescript-eslint/explicit-function-return-type
```

---

## 4. Usage

### Validate a Python File

```bash
# Direct CLI usage
clean_py validate src/models/user.py

# Output (JSON on stdout)
{
  "valid": true,
  "errors": []
}
```

### Validate a TypeScript File

```bash
# Direct CLI usage
clean_ts validate src/models/user.ts

# Output (JSON on stdout)
{
  "valid": true,
  "errors": []
}
```

### OpenCode Plugin Mode

The OpenCode wrappers (`plugins/opencode/clean_python.ts` and `plugins/opencode/clean_ts.ts`) automatically:

1. Resolve the workspace root from `context.directory`
2. Write code to a secure temporary file (mode `0600`)
3. Delegate validation to `clean_py` or `clean_ts`
4. Perform an atomic `fs.rename` only if validation passes
5. Track retry attempts per target path (max 10 attempts)

---

## 5. Environment Variables

| Variable | Scope | Default | Description |
|---|---|---|---|
| `DISABLE_CLEAN_PYTHON` | `clean_python.ts` | unset | Set to `true` to bypass `clean_py` validation and write directly |
| `DISABLE_CLEAN_TS` | `clean_ts.ts` | unset | Set to `true` to bypass `clean_ts` validation and write directly |
| `VIRTUAL_ENV` | `clean_py` | auto-discover | Path to Python virtual environment (`.venv/`) |
| `PYTHONIOENCODING` | `clean_py` | `utf-8` | Ensures UTF-8 output from Python subprocess |
| `PYTHONDONTWRITEBYTECODE` | `clean_py` | `1` | Prevents `.pyc` file creation |
| `NODE_NO_WARNINGS` | `clean_ts` | `1` | Suppresses Node.js deprecation warnings |

---

## 6. CI / GitHub Actions

Add the following to your CI pipeline to enforce quality gates on push:

```bash
# Python CI gate
cd plugins/python
pip install -e .
clean_py validate src/

# TypeScript CI gate
cd plugins/typescript/clean_ts
npm ci
npm run build
clean_ts validate src/
```

### GitHub Actions Example

```yaml
- name: Install clean_py
  run: |
    cd plugins/python
    pip install -e .

- name: Validate Python files
  run: |
    find src/ -name "*.py" -exec clean_py validate {} \;

- name: Install clean_ts
  run: |
    cd plugins/typescript/clean_ts
    npm ci && npm run build

- name: Validate TypeScript files
  run: |
    find src/ --name "*.ts" --not -path "*/node_modules/*" -exec npx clean_ts validate {} \;
```

---

## Related Documentation

- **[`README.md`](./README.md)** — Plugin architecture and directory overview.
- **[`FAQ.md`](./FAQ.md)** — Frequently asked questions and troubleshooting.
