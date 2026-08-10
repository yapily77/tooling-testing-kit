import json
from pathlib import Path
from typing import Any

import pytest
from generate_report import (
    _safe_float,
    _safe_str,
    build_error_distribution,
    compute_summary_stats,
    create_argument_parser,
    extract_test_cases,
    find_log_files,
    format_markdown_report,
    load_log_file,
    write_or_print_report,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_log_file(directory: Path, name: str, data: list[dict[str, Any]]) -> Path:
    """Write *data* as JSON to *directory*/*name* and return the path."""
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── _safe_float ──────────────────────────────────────────────────────────────

class TestSafeFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1, 1.0),
            (2.5, 2.5),
            (0, 0.0),
            ("abc", 0.0),
            (None, 0.0),
            ([], 0.0),
        ],
    )
    def test_coercion(self, value: Any, expected: float) -> None:
        assert _safe_float(value) == expected


# ── _safe_str ────────────────────────────────────────────────────────────────

class TestSafeStr:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("ok", "ok"),
            (42, "unknown"),
            (None, "unknown"),
            ([], "unknown"),
        ],
    )
    def test_coercion(self, value: Any, expected: str) -> None:
        assert _safe_str(value) == expected


# ── extract_test_cases ───────────────────────────────────────────────────────

class TestExtractTestCases:
    def test_extracts_dict_entries(self) -> None:
        data: list[dict[str, Any]] = [
            {"name": "t1", "status": "passed"},
            {"name": "t2", "status": "failed", "error_type": "TimeoutError"},
        ]
        result = extract_test_cases(data)
        assert len(result) == 2

    def test_skips_non_dict_entries(self) -> None:
        data: list[Any] = [{"ok": 1}, "bad", 42]
        result = extract_test_cases(data)
        assert len(result) == 1

    def test_empty_input(self) -> None:
        assert extract_test_cases([]) == []


# ── load_log_file ────────────────────────────────────────────────────────────

class TestLoadLogFile:
    def test_valid_json(self, tmp_path: Path) -> None:
        path = _make_log_file(tmp_path, "log.json", [{"status": "passed"}])
        result = load_log_file(path)
        assert result is not None
        assert len(result) == 1

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        assert load_log_file(path) is None

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_log_file(path) is None

    def test_non_list_json(self, tmp_path: Path) -> None:
        path = tmp_path / "obj.json"
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        assert load_log_file(path) is None


# ── compute_summary_stats ────────────────────────────────────────────────────

class TestComputeSummaryStats:
    def test_counts_passed_failed(self) -> None:
        cases: list[dict[str, Any]] = [
            {"status": "passed", "duration": 0.1},
            {"status": "failed", "duration": 0.2},
            {"status": "passed", "duration": 0.3},
        ]
        stats = compute_summary_stats(cases)
        assert stats["total"] == 3
        assert stats["passed"] == 2
        assert stats["failed"] == 1
        assert stats["average_time"] == pytest.approx(0.2, abs=0.001)

    def test_empty_cases(self) -> None:
        stats = compute_summary_stats([])
        assert stats["total"] == 0
        assert stats["passed"] == 0
        assert stats["failed"] == 0
        assert stats["average_time"] == 0.0

    def test_missing_duration_defaults_zero(self) -> None:
        cases: list[dict[str, Any]] = [{"status": "passed"}]
        stats = compute_summary_stats(cases)
        assert stats["average_time"] == 0.0


# ── build_error_distribution ─────────────────────────────────────────────────

class TestBuildErrorDistribution:
    def test_counts_error_types(self) -> None:
        cases: list[dict[str, Any]] = [
            {"status": "failed", "error_type": "TimeoutError"},
            {"status": "failed", "error_type": "TimeoutError"},
            {"status": "failed", "error_type": "AssertionError"},
            {"status": "passed"},
        ]
        dist = build_error_distribution(cases)
        assert dist == {"TimeoutError": 2, "AssertionError": 1}

    def test_no_failures(self) -> None:
        cases: list[dict[str, Any]] = [{"status": "passed"}]
        assert build_error_distribution(cases) == {}

    def test_missing_error_type_falls_back(self) -> None:
        cases: list[dict[str, Any]] = [
            {"status": "failed", "error_type": "TypeError"},
            {"status": "failed"},
        ]
        dist = build_error_distribution(cases)
        assert dist == {"TypeError": 1, "unknown": 1}


# ── format_markdown_report ───────────────────────────────────────────────────

class TestFormatMarkdownReport:
    def test_renders_summary_lines(self) -> None:
        stats: dict[str, Any] = {
            "total": 10,
            "passed": 7,
            "failed": 3,
            "average_time": 0.1234,
        }
        report = format_markdown_report(stats, {}, 2)
        assert "# Test Report Summary" in report
        assert "Log files processed**: 2" in report
        assert "Total test cases**: 10" in report

    def test_renders_error_table(self) -> None:
        stats: dict[str, Any] = {"total": 5, "passed": 3, "failed": 2, "average_time": 0.5}
        errors: dict[str, int] = {"AssertionError": 2}
        report = format_markdown_report(stats, errors, 1)
        assert "AssertionError" in report
        assert "2" in report

    def test_no_failures_message(self) -> None:
        stats: dict[str, Any] = {"total": 3, "passed": 3, "failed": 0, "average_time": 0.1}
        report = format_markdown_report(stats, {}, 1)
        assert "No failures recorded." in report


# ── create_argument_parser ─────────────────────────────────────────────────

class TestCreateArgumentParser:
    def test_required_directory_arg(self) -> None:
        parser = create_argument_parser()
        args = parser.parse_args(["/tmp"])
        assert args.directory == Path("/tmp")

    def test_optional_output(self) -> None:
        parser = create_argument_parser()
        args = parser.parse_args(["/tmp", "-o", "out.md"])
        assert args.output == Path("out.md")

    def test_default_extension(self) -> None:
        parser = create_argument_parser()
        args = parser.parse_args(["/tmp"])
        assert args.extension == ".json"


# ── find_log_files ──────────────────────────────────────────────────────────

class TestFindLogFiles:
    def test_finds_json_files(self, tmp_path: Path) -> None:
        _make_log_file(tmp_path, "a.json", [])
        _make_log_file(tmp_path, "b.json", [])
        (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")
        files = find_log_files(tmp_path, ".json")
        assert len(files) == 2

    def test_missing_directory(self, tmp_path: Path) -> None:
        bad = tmp_path / "nope"
        assert find_log_files(bad, ".json") == []

    def test_custom_extension(self, tmp_path: Path) -> None:
        _make_log_file(tmp_path, "a.log", [])
        _make_log_file(tmp_path, "b.json", [])
        files = find_log_files(tmp_path, ".log")
        assert len(files) == 1


# ── write_or_print_report ───────────────────────────────────────────────────

class TestWriteOrPrintReport:
    def test_writes_to_file(self, tmp_path: Path) -> None:
        out = tmp_path / "report.md"
        write_or_print_report("hello world", out)
        assert out.read_text(encoding="utf-8") == "hello world"

    def test_prints_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        write_or_print_report("stdout text", None)
        captured = capsys.readouterr()
        assert "stdout text" in captured.out
