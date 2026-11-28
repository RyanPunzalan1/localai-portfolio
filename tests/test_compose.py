"""docker-compose.yml keeps the chat app off the network (threat model gap 6) and keeps the published ports local.

Reads the file only; the live check (no internet from the app container) is in design/threat-model.md.
PyYAML comes with chromadb, which requirements.txt pins.
"""

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import port_relay  # noqa: E402

COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


class AppHasNoNetwork(unittest.TestCase):
    def test_app_is_only_on_the_internal_network(self):
        app = SERVICES["localai"]
        self.assertEqual(app.get("networks"), ["app_internal"])
        self.assertTrue(COMPOSE["networks"]["app_internal"].get("internal"))
        self.assertNotIn("ports", app)
        self.assertNotIn("extra_hosts", app)
        self.assertNotIn("network_mode", app)

    def test_app_reaches_ollama_only_through_the_relay(self):
        self.assertIn("OLLAMA_HOST=http://ollama.internal:11434", SERVICES["localai"]["environment"])
        # Ollama only accepts Host names it recognises; the relay answers to this one on the app's network.
        self.assertIn("ollama.internal", SERVICES["relay"]["networks"]["app_internal"]["aliases"])

    def test_relay_has_exactly_the_two_routes(self):
        relay = SERVICES["relay"]
        self.assertEqual(relay["command"][:2], ["python", "port_relay.py"])
        self.assertEqual(port_relay.parse_rules(relay["command"][2:]),
                         [(8501, "localai", 8501), (11434, "host.docker.internal", 11434)])
        self.assertEqual(set(relay["networks"]), {"app_internal", "relay_out"})

    def test_only_the_relay_shares_the_apps_network(self):
        on_internal = sorted(n for n, s in SERVICES.items() if "app_internal" in (s.get("networks") or {}))
        self.assertEqual(on_internal, ["localai", "relay"])
        self.assertNotIn("relay_out", SERVICES["dashboard"].get("networks") or [])
        self.assertNotIn("app_internal", SERVICES["relay-dashboard"].get("networks") or [])


class DashboardHasNoNetwork(unittest.TestCase):
    def test_dashboard_is_only_on_its_own_internal_network(self):
        dash = SERVICES["dashboard"]
        self.assertEqual(dash.get("networks"), ["dash_internal"])
        self.assertTrue(COMPOSE["networks"]["dash_internal"].get("internal"))
        self.assertNotIn("ports", dash)
        self.assertNotIn("extra_hosts", dash)

    def test_its_relay_has_one_route_and_never_touches_the_app(self):
        relay = SERVICES["relay-dashboard"]
        self.assertEqual(port_relay.parse_rules(relay["command"][2:]), [(8502, "dashboard", 8502)])
        self.assertEqual(set(relay["networks"]), {"dash_internal", "relay_out"})
        self.assertNotIn("extra_hosts", relay)  # no route to the host, so none to Ollama

    def test_only_its_relay_shares_the_dashboards_network(self):
        on_dash = sorted(n for n, s in SERVICES.items() if "dash_internal" in (s.get("networks") or {}))
        self.assertEqual(on_dash, ["dashboard", "relay-dashboard"])




class PublishedPortsAreLocal(unittest.TestCase):
    def test_every_published_port_is_on_127_0_0_1(self):
        for name, svc in SERVICES.items():
            for port in svc.get("ports") or []:
                with self.subTest(service=name, port=port):
                    self.assertTrue(str(port).startswith("127.0.0.1:"), port)


class Hardening(unittest.TestCase):
    def test_every_service_is_hardened(self):
        for name, svc in SERVICES.items():
            with self.subTest(service=name):
                self.assertTrue(svc.get("read_only"))
                self.assertEqual(svc.get("cap_drop"), ["ALL"])
                self.assertIn("no-new-privileges:true", svc.get("security_opt") or [])
                self.assertIn("mem_limit", svc)
                self.assertIn("pids_limit", svc)
                self.assertNotIn("privileged", svc)


class ImageIncludesTheRelay(unittest.TestCase):
    def test_dockerfile_copies_port_relay(self):
        copy_lines = [ln for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
                      if ln.startswith("COPY ")]
        self.assertTrue(any(" port_relay.py " in f" {ln} " for ln in copy_lines))


if __name__ == "__main__":
    unittest.main()
