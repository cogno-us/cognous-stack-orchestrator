import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Record every refusal code raised during the session so the final test can show each code of the
# closed set has a negative test (the check is order-dependent: run the whole directory).
import pytest  # noqa: E402

from orchestration.workflow_store import refusal as _refusal  # noqa: E402

SEEN_CODES = set()
_refusal.TEST_SEEN_CODES = SEEN_CODES  # shared with the final test without importing conftest
_original_init = _refusal.StoreRefusal.__init__


def _recording_init(self, code, message='', detail=None):
    _original_init(self, code, message, detail)
    SEEN_CODES.add(code)


@pytest.fixture(autouse=True, scope='session')
def _record_codes():
    _refusal.StoreRefusal.__init__ = _recording_init
    yield
    _refusal.StoreRefusal.__init__ = _original_init
