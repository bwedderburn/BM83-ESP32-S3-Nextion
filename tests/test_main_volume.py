import sys
from unittest import mock

# Mock CircuitPython modules for CI/testing
sys.modules['board'] = mock.MagicMock()
sys.modules['busio'] = mock.MagicMock()

import main  # noqa: E402


def test_main_imports():
    """Test that main module can be imported with mocked CircuitPython modules."""
    # Verify that main module has expected attributes
    assert hasattr(main, 'main')
    assert callable(main.main)
    assert hasattr(main, 'BLE_ENABLED')
    assert hasattr(main, 'BLE_NAME')
