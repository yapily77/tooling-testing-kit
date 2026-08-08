# Contributing to Tooling & Testing Kit

Thank you for your interest in contributing! This toolkit is designed to provide high-assurance, portable static analysis, AST refactoring, and harness testing utilities for Python workflows.

---

## 🛠️ Development Setup

### 1. Prerequisites
- Python 3.10+
- Git

### 2. Quickstart
```bash
# Clone the repository
git clone https://github.com/acivardigital/tooling-testing-kit.git
cd tooling-testing-kit

# Install editable package with all optional dependencies
pip install -e ".[all]"
```

---

## 🧪 Running Tests & Scanners

Before submitting a pull request, ensure all tests and hygiene scanners pass:

```bash
# 1. Run all codebase hygiene scanners
python hygiene/scanners/run_all.py --scripts

# 2. Run tools unit test suite
python tools/test/run_all.py

# 3. Run pytest suite
pytest tests/examples/
```

---

## 📐 Code Style & Conventions

- Follow **PEP 8** guidelines.
- Keep tool CLI scripts self-contained and environment-aware (`KIT_TARGET_ROOT`).
- Ensure all AST modification tools emit structured JSON responses (`{"success": true, "message": "...", "data": ...}`).
- Use typed function signatures (`pydantic` or standard typing hints).

---

## 📬 Pull Request Checklist

1. [ ] Code follows project structure and style guidelines.
2. [ ] All unit tests pass (`python tools/test/run_all.py`).
3. [ ] All hygiene scanners pass (`python hygiene/scanners/run_all.py --scripts`).
4. [ ] Relevant documentation updated (`README.md`, `GUIDE.md`).

---

## 📄 License
By contributing, you agree that your contributions will be licensed under the project's **MIT License**.
