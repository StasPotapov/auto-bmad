import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import process_guard
import stub


class CleanupTest(unittest.TestCase):
    def test_stub_record_disappearing_does_not_abort_synchronous_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text(json.dumps({"repo": directory}))
            with patch.object(process_guard.os, "fork", side_effect=OSError("fork unavailable")), \
                    patch.object(stub, "recorded", return_value=["disappeared"]), \
                    patch.object(stub, "read", return_value=(None, None)):
                process_guard.session_cleanup(str(path))
            self.assertTrue((path.parent / "tests-closed").exists())


if __name__ == "__main__":
    unittest.main()
