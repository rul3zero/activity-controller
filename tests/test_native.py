"""Exercise the actual macOS event loop and graceful process shutdown."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import monotonic, sleep
import unittest
from urllib.request import Request, urlopen


class NativeAppTests(unittest.TestCase):
    def test_menu_bar_app_quits_and_releases_localhost(self):
        root = Path(__file__).resolve().parents[1]
        executable = os.environ.get("PAPER_TEST_EXECUTABLE")
        command = [executable] if executable else [sys.executable, str(root / "main.py")]
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PAPER_DATA_DIR=directory)
            process = subprocess.Popen(command + ["--dry-run", "--port", "0"], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                info = Path(directory) / "instance.json"
                deadline = monotonic() + 20
                url = None
                while monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(process.communicate()[0])
                    try:
                        url = json.loads(info.read_text())["url"]
                        break
                    except (FileNotFoundError, ValueError, KeyError):
                        sleep(.05)
                self.assertIsNotNone(url, "App did not start its server")
                with urlopen(url, timeout=3) as response:
                    html = response.read().decode()
                token = re.search(r"const token = '([^']+)'", html).group(1)
                # Allow the AppKit loop to launch before asking it to stop.
                sleep(.5)
                request = Request(url + "api/quit", data=b"{}", headers={
                    "Content-Type": "application/json", "X-Paper-Token": token,
                })
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                output, _ = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 0, output)
                with self.assertRaises(OSError):
                    urlopen(url, timeout=1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
