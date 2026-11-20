"""Exercise deployment generation without Docker, Freqtrade, or exchange access."""

import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BotsCliTests(unittest.TestCase):
  def test_cli_isolates_instances_reserves_ports_and_never_overwrites(self):
    with tempfile.TemporaryDirectory() as name:
      root = Path(name)
      (root / "NostalgiaForInfinityX8.py").write_text("# test snapshot\n")
      with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

      def cli(*args):
        return subprocess.run(
          [sys.executable, str(ROOT / "tools/bots.py"), *args, "--root", name], capture_output=True, text=True
        )

      created = cli("create", "--name", "okx-futures", "--mode", "futures", "--port", str(port))
      self.assertEqual(created.returncode, 0, created.stderr)
      self.assertIn("up -d bot", created.stdout)
      compose_path = root / "user_data/bots/okx-futures/compose.json"
      before = compose_path.read_bytes()
      self.assertEqual(cli("create", "--name", "okx-spot", "--port", str(port)).returncode, 2)
      self.assertEqual(cli("create", "--name", "../escape").returncode, 2)
      self.assertEqual(cli("create", "--name", "bad", "--port", "9999999999").returncode, 2)
      self.assertEqual(compose_path.read_bytes(), before)
      self.assertIn("okx-futures futures", cli("list").stdout)
      compose = json.loads(before)
      self.assertNotIn("API_SERVER__PASSWORD", str(compose))
      self.assertNotIn("AVAILABLE_CAPITAL", str(compose))


if __name__ == "__main__":
  unittest.main()
