# Enterprise Quality & Sanitizer Toolkit

> **Prepared for Accenture Technical Demonstration & Open-Source Community**

A production-grade quality engineering showcase designed to demonstrate **clean code architecture, portable scripting, environment configuration (.env), and automated path scrubbing**.

---

## 🌟 Key Highlights for Technical Evaluation

1. **Zero Hardcoded Paths**: Automatically scrubs legacy names (e.g. `baziforecaster` -> `my-repo`) and absolute machine paths.
2. **Environment Configuration**: Dynamic `.env` driven settings with `.env.example` templates.
3. **Multi-Tier Quality Harness**: Integrated snapshot locks, unit bedrock, property fuzzing, static analysis gates, and tech debt auditing.
4. **1-Click Community Bootstrap**: Includes `tools/bootstrap.sh` and `tools/scrub_paths.py` for immediate open-source execution.

---

## 🚀 Quick Start Guide

```bash
# 1. Clone the repository
git clone https://github.com/your-username/my-repo.git
cd my-repo

# 2. Run automated bootstrap & path scrubbing
bash tools/bootstrap.sh

# 3. Launch interactive web dashboard
npm run dev
```

---

## 📂 Repository Architecture

- `/.env.example` — Public configuration template
- `/tools/scrub_paths.py` — Python string/path sanitizer utility
- `/tools/bootstrap.sh` — 1-click environment initializer
- `/hygiene/scanners/` — Static analysis and debt scanners
- `/tests/` — 10-tier quality and snapshot testing suite
- `/src/` — Interactive React dashboard and UI suite

---

## ⚡ Automated Path Scrubbing

To scrub custom strings across the repository:
```bash
python3 tools/scrub_paths.py "legacy_string" "new_string"
```

---

*Engineered with quality, portability, and clean code principles.*
