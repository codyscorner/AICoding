"""Make the project modules importable from the tests (and run Qt headless)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # UI tests need no display

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
