import pytest  # noqa: F401


def test_replicate_daily_webhook_crash():
    """
    Replicates the /daily webhook crash exactly.
    This will fail with: ImportError: cannot import name 'get_ten_god' from 'src.core.schemas.unified'
    """
    import src.interfaces.telegram.chronomancer.coordinator  # noqa: F401

def test_replicate_start_webhook_crash():
    """
    Replicates the /start webhook crash and ensures intake imports correctly without text_manager ImportError.
    """
    import src.interfaces.telegram.intake.intake  # noqa: F401


def test_replicate_stakeholder_intake_import():
    """
    Ensures stakeholder_intake imports correctly without text_manager ImportError.
    """
    import src.interfaces.telegram.stakeholder_intake  # noqa: F401
    from src.interfaces.telegram.text_manager import text_manager  # noqa: F401
