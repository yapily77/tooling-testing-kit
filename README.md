# Enterprise Quality Engineering & Sanitizer Toolkit

> **Prepared for Accenture Technical Demonstration & Open-Source Community Reuse**

An enterprise-grade, portable Quality Engineering framework designed to demonstrate **clean code architecture, test automation, static hygiene gates, path scrubbing, and dynamic environment configuration (`.env`)**.

---

## 🎯 Purpose & Key Capabilities

1. **Zero Hardcoded Paths**:
   - Automatically scrubs machine-specific local paths (`/Users/...`, `/home/...`, `C:\Users\...`) and legacy repository identifiers into configurable environment variables and relative path resolvers (`path.resolve()`).
2. **Dynamic Environment Engine (`.env`)**:
   - Centralized configuration module (`src/config/index.ts`) providing environment fallbacks, path resolution, and zero-leak credential management.
3. **Multi-Tier Quality Architecture (`tests/`)**:
   - **01_gold_snapshots**: Output regression locks preventing unwanted drift.
   - **02_unit_bedrock**: Isolated unit tests for path resolvers and config parsing.
   - **03_regression_locks**: Critical path invariant protection.
   - **05_integration_e2e**: End-to-end integration workflows.
   - **08_static_gates**: Static linting and security quality gates.
   - **09_tech_debt_audit**: Automated code complexity and coverage density audit.
   - **10_harness_suite**: Test execution lifecycle management.
4. **Automated Hygiene Scanners (`hygiene/`)**:
   - Static analysis scanners (`hygiene/scanners/path_scrub_check.ts`) that enforce zero unscrubbed strings before commit or build.
5. **Community Tooling Suite (`tools/`)**:
   - `tools/codebase/analyzer.ts`: Code metrics & debt rating generator.
   - `tools/scrub_paths.py`: Portable Python sanitizer CLI.
   - `tools/bootstrap.sh`: 1-command open-source setup script.

---

## 🚀 Quick Start Guide (For Community & Evaluators)

### 1. Clone & Bootstrap Environment
```bash
git clone https://github.com/your-username/my-repo.git
cd my-repo

# Run 1-click bootstrapper
bash tools/bootstrap.sh
```

### 2. Execute Quality Test Suite
```bash
# Run all unit, integration, and snapshot tests
npm test

# Run daily hygiene & static path checks
npm run scrub-check
npm run hygiene

# Run codebase metric analysis
npm run analyze
```

### 3. Launch Interactive Web Dashboard
```bash
npm run dev
```

---

## 📂 Repository Structural Layout

```
├── .env.example                       # Configurable environment template
├── src/
│   ├── config/index.ts                # Centralized portable config engine
│   └── utils/scrubber.ts              # Core path & token sanitizer utility
├── tools/
│   ├── codebase/analyzer.ts           # Code metrics & complexity analyzer
│   ├── rag/doc_search.ts              # Local architectural search helper
│   ├── test/runner.ts                 # Test harness orchestrator
│   ├── scrub_paths.py                 # Python bulk path sanitizer CLI
│   └── bootstrap.sh                   # 1-click open source onboarding script
├── hygiene/
│   ├── daily/preflight.ts             # Pre-flight environment & structure check
│   └── scanners/path_scrub_check.ts   # Static path & secret leakage scanner
├── tests/
│   ├── 01_gold_snapshots/             # Snapshot regression test locks
│   ├── 02_unit_bedrock/               # Core engine unit tests
│   ├── 03_regression_locks/           # Invariant regression checks
│   ├── 05_integration_e2e/            # End-to-end workflow tests
│   ├── 08_static_gates/               # Security & quality static gates
│   ├── 09_tech_debt_audit/            # Quality scorecard & coverage audit
│   └── 10_harness_suite/              # Lifecycle test harness
└── README.md                          # Master project documentation
```

---

## ⚙️ Environment Configuration (.env)

All system directories and legacy replacement tokens are driven via `.env`:

```env
APP_NAME=my-repo
APP_ENV=development
APP_PORT=3000

# Portable Relative Workspace Paths
REPO_ROOT=.
DATA_DIR=./src/data
OUTPUT_DIR=./dist
LOG_DIR=./tests/reports/logs

# Sanitizer Replacement Target
TARGET_LEGACY_NAME=legacy_project_name
TARGET_CLEAN_NAME=my-repo
```

---

*Built with precision, test-driven rigor, and clean engineering standards.*
