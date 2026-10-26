"""Cross-host resolution: run with `python -m unittest discover -s tests`."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scout_crew import hosts  # noqa: E402

CLEAN = {k: "" for k in (
    "SCOUT_MESH_HUB_ADDRESS", "SCOUT_MESH_CIDR", "SCOUT_PEER_MESH_IP", "SCOUT_PEER_OLLAMA_PORT",
    "SCOUT_PEER_OLLAMA_HOST", "SCOUT_PEER_OLLAMA_OPENAI", "SCOUT_BLACKBOARD_URL",
    "SCOUT_MAP_BASE_URL", "SCOUT_BACKEND_URL", "SCOUT_DATA_ROOT", "SCOUT_STATE_DIR",
    "SCOUT_ALLOWED_LLM_HOSTS", "SCOUT_OUTPUT_DIR", "XDG_STATE_HOME")}


class HostsTest(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, CLEAN)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_hub_defaults(self):
        self.assertEqual(hosts.mesh_hub(), "10.66.0.1")
        self.assertEqual(hosts.blackboard_url(), "http://10.66.0.1:8765")
        self.assertEqual(hosts.map_server_url(), "http://10.66.0.1:18080")

    def test_overrides(self):
        os.environ["SCOUT_MESH_HUB_ADDRESS"] = "10.66.9.9"
        os.environ["SCOUT_MAP_BASE_URL"] = "https://10.66.0.1:8443/"
        self.assertEqual(hosts.blackboard_url(), "http://10.66.9.9:8765")
        self.assertEqual(hosts.map_server_url(), "https://10.66.0.1:8443")

    def test_peer_ollama(self):
        self.assertEqual(hosts.peer_ollama_url(), "")
        os.environ["SCOUT_PEER_MESH_IP"] = "10.66.2.4"
        self.assertEqual(hosts.peer_ollama_url(), "http://10.66.2.4:11434")
        os.environ["SCOUT_PEER_OLLAMA_PORT"] = "11435"
        self.assertEqual(hosts.peer_ollama_url(), "http://10.66.2.4:11435")
        os.environ["SCOUT_PEER_OLLAMA_OPENAI"] = "http://10.66.2.4:11435/v1"
        self.assertEqual(hosts.peer_ollama_url(), "http://10.66.2.4:11435")

    def test_paths_are_overridable(self):
        os.environ["SCOUT_DATA_ROOT"] = "/srv/scout-data"
        os.environ["SCOUT_STATE_DIR"] = "/var/lib/scout/state"
        self.assertEqual(hosts.data_root(), Path("/srv/scout-data"))
        self.assertEqual(hosts.state_dir(), Path("/var/lib/scout/state"))

    def test_output_dir(self):
        self.assertEqual(hosts.output_dir(), hosts.project_root() / "output")
        self.assertTrue((hosts.project_root() / "pyproject.toml").exists())
        os.environ["SCOUT_OUTPUT_DIR"] = "/var/lib/scout/out"
        self.assertEqual(hosts.output_dir(), Path("/var/lib/scout/out"))

    def test_local_or_mesh_guard(self):
        ok = ["http://127.0.0.1:11434/v1", "http://localhost:8000", "http://10.66.2.4:11435/v1",
              "http://10.66.0.1:8000/v1", "http://[::1]:11434"]
        bad = ["https://api.openai.com/v1", "http://8.8.8.8:11434", "http://192.168.12.188:11434", ""]
        for u in ok:
            self.assertTrue(hosts.is_local_or_mesh(u), u)
        for u in bad:
            self.assertFalse(hosts.is_local_or_mesh(u), u)
        os.environ["SCOUT_ALLOWED_LLM_HOSTS"] = "192.168.12.188"
        self.assertTrue(hosts.is_local_or_mesh("http://192.168.12.188:11434"))


if __name__ == "__main__":
    unittest.main()
