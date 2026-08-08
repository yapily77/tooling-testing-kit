"""
Sample Target Python File for Tooling & Testing Kit Demonstrations.
Contains intentional code patterns audited by kit-hygiene scanners.
"""

import os
import sys

# Unused legacy constant (audited by find_dead_code.py)
UNUSED_LEGACY_CONFIG = {"debug": True, "timeout": 30}


def calculate_user_metrics(data: list) -> dict:
    """Calculates user engagement metrics."""
    total = sum(data)
    count = len(data)
    average = total / count if count > 0 else 0
    return {"total": total, "count": count, "average": average}


def dead_code_function():
    """Function never called elsewhere in the codebase."""
    return "This is dead code"


async def async_hazard_example():
    """Unawaited background task hazard (audited by find_async_hazards.py)."""
    import asyncio

    # Unawaited task creation
    asyncio.create_task(asyncio.sleep(1))
    return True


if __name__ == "__main__":
    metrics = calculate_user_metrics([10, 20, 30])
    print(f"Calculated metrics: {metrics}")
