import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parents[2]))

from examples.sample_target import calculate_user_metrics


def test_calculate_user_metrics():
    metrics = calculate_user_metrics([10, 20, 30])
    assert metrics["total"] == 60
    assert metrics["count"] == 3
    assert metrics["average"] == 20.0


def test_calculate_user_metrics_empty():
    metrics = calculate_user_metrics([])
    assert metrics["total"] == 0
    assert metrics["count"] == 0
    assert metrics["average"] == 0.0
