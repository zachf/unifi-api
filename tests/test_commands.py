import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from unifi_api import APIError, Config, UniFiClient
from unifi_api.cli import main


class CommandsTests(unittest.TestCase):
    def setUp(self):
        self.client = UniFiClient(Config("https://controller.local", "test-key", site_id="site-a"))
        self.devices = [
            {"id": "switch-a", "name": "Office Switch", "macAddress": "aa:bb:cc:dd:ee:ff", "state": "ONLINE"},
            {"id": "switch-b", "name": "Office Switch 2", "state": "OFFLINE"},
        ]
        self.clients = [
            {"id": "laptop", "name": "Laptop", "ipAddress": "10.0.0.5", "macAddress": "11:22:33:44:55:66",
             "type": "WIRED", "uplinkDeviceId": "switch-a", "access": {"type": "DEFAULT"}},
        ]
        self.request = Mock(side_effect=self.route)
        self.client.request = self.request

    def route(self, method, path, **kwargs):
        self.assertEqual(method, "GET")
        if path == "sites":
            return {"data": [{"id": "site-a", "name": "Home"}, {"id": "site-b", "name": "Office"}], "totalCount": 2}
        if path == "info":
            return {"applicationVersion": "9.4.19"}
        collection = path.split("/", 2)[2]
        collections = {"devices": self.devices, "clients": self.clients,
                       "networks": [{"id": "net-a", "name": "Office LAN", "vlanId": 10, "enabled": True}],
                       "wifi/broadcasts": [{"id": "wifi-a", "name": "Office WiFi", "enabled": True}],
                       "wans": [{"id": "wan-a", "name": "WAN1"}]}
        if collection in collections:
            return {"data": collections[collection], "totalCount": len(collections[collection])}
        if collection == "devices/switch-a":
            return {"id": "switch-a", "interfaces": {"ports": [
                {"idx": 1, "state": "UP", "speedMbps": 1000, "poe": {"enabled": True}},
                {"idx": 2, "state": "DOWN", "maxSpeedMbps": 1000},
            ]}}
        if collection == "devices/switch-a/statistics/latest":
            return {"uptimeSec": 3600, "cpuUtilizationPct": 12.5, "memoryUtilizationPct": 40.1}
        if collection == "clients/laptop":
            return {"id": "laptop", "connectedAt": "2026-11-01T10:00:00Z"}
        self.fail("Unexpected API path: " + path)

    def run_cli(self, args, commands=()):
        with patch("unifi_api.cli.UniFiClient.from_config", return_value=self.client), \
                patch("builtins.input", side_effect=commands), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_use_site_and_explicit_override(self):
        code, out, err = self.run_cli(["shell"], ["use Office", "devices", "clients --site site-a", "status", "exit"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Office", out)
        paths = [call[0][1] for call in self.request.call_args_list]
        self.assertEqual(paths, ["sites", "sites/site-b/devices", "sites/site-a/clients", "sites/site-a/devices", "sites",
                                 "sites/site-b/devices", "sites/site-b/clients", "sites/site-b/networks",
                                 "sites/site-b/wifi/broadcasts", "sites/site-b/wans"])
        self.assertEqual(self.client.config.site_id, "site-a")

    def test_status_counts_preserve_device_states(self):
        code, out, err = self.run_cli(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["deviceStates"], {"ONLINE": 1, "OFFLINE": 1})
        self.assertEqual(result["connectedClients"], 1)
        self.assertEqual(result["clientTypes"], {"WIRED": 1})
        self.assertEqual(result["deviceDetails"][0]["clients"], 1)
        self.assertEqual(result["networks"][0]["vlanId"], 10)

    def test_status_screen_sections_and_firmware_attention(self):
        self.devices[0]["firmwareUpdatable"] = True
        code, out, err = self.run_cli(["status"])
        self.assertEqual((code, err), (0, ""))
        for value in ("UNIFI NETWORK STATUS", "Site: Home", "Connected clients", "Office Switch",
                      "Office LAN", "Office WiFi", "WAN1", "Needs review", "OFFLINE", "Firmware updates"):
            self.assertIn(value, out)
        self.assertNotIn("switch-a", out)

    def test_status_optional_failures_are_unavailable_not_zero(self):
        def route(method, path, **kwargs):
            if path.endswith("/wans"):
                raise APIError("HTTP 404. Unsupported endpoint", 404)
            return self.route(method, path, **kwargs)
        self.request.side_effect = route
        code, out, err = self.run_cli(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        summary = json.loads(out)
        self.assertIsNone(summary["wan"])
        self.assertIn("404", summary["warnings"][0])
        code, out, err = self.run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Unavailable", out)
        self.assertIn("Collection warnings", out)

    def test_status_core_failure_does_not_show_a_healthy_empty_site(self):
        def route(method, path, **kwargs):
            if path.endswith("/devices"):
                raise APIError("HTTP 401. Check key", 401)
            return self.route(method, path, **kwargs)
        self.request.side_effect = route
        code, out, err = self.run_cli(["status"])
        self.assertEqual(code, 1)
        self.assertIn("401", err)
        self.assertNotIn("UNIFI NETWORK STATUS", out)

    def test_status_single_site_autoselection_and_empty_collections(self):
        self.client.config = Config("https://controller.local", "test-key")
        self.request.side_effect = lambda method, path, **kwargs: {
            "data": [{"id": "only-site", "name": "Only site"}] if path == "sites" else [], "totalCount": 1 if path == "sites" else 0}
        code, out, err = self.run_cli(["status", "--json"])
        self.assertEqual((code, err), (0, ""))
        summary = json.loads(out)
        self.assertEqual(summary["site_id"], "only-site")
        self.assertEqual(summary["connectedClients"], 0)
        self.assertEqual(summary["wifi"], [])
        self.assertEqual(summary["warnings"], [])

    def test_device_lookup_normalizes_mac_and_prioritizes_exact_name(self):
        for selector in ("Office Switch", "AA-BB-CC-DD-EE-FF", "switch-a"):
            code, out, err = self.run_cli(["device", selector, "--json"])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(out)["name"], "Office Switch")
            self.assertEqual(self.request.call_args[0][1], "sites/site-a/devices/switch-a")

    def test_ambiguous_or_missing_lookup_does_not_select_arbitrarily(self):
        for selector in ("Office", "missing"):
            self.request.reset_mock()
            code, out, err = self.run_cli(["device", selector])
            self.assertEqual(code, 1)
            self.assertIn("matching device", err)
            self.assertEqual(self.request.call_count, 1)

    def test_client_lookup_fetches_details_and_keeps_overview_fields(self):
        code, out, err = self.run_cli(["client", "10.0.0.5", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["name"], "Laptop")
        self.assertIn("connectedAt", json.loads(out))

    def test_stats_selects_device_and_merges_latest_statistics(self):
        code, out, err = self.run_cli(["stats", "aa:bb:cc:dd:ee:ff", "--json"])
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["name"], "Office Switch")
        self.assertEqual(result["cpuUtilizationPct"], 12.5)
        self.assertEqual(self.request.call_args[0][1], "sites/site-a/devices/switch-a/statistics/latest")

    def test_info_does_not_require_a_site(self):
        self.client.config = Config("https://controller.local", "test-key")
        code, out, err = self.run_cli(["info", "--json"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["applicationVersion"], "9.4.19")

    def test_clients_include_uplink_device_name_and_connection_duration(self):
        self.clients[0]["connectedAt"] = "2026-11-01T10:00:00Z"
        self.clients.append({"id": "phone", "name": "Phone", "type": "WIRELESS"})
        code, out, err = self.run_cli(["clients", "--json"])
        self.assertEqual((code, err), (0, ""))
        rows = json.loads(out)
        self.assertEqual(rows[0]["uplinkDevice"], "Office Switch")
        self.assertRegex(rows[0]["connectedFor"], r"\d+h \d+m$")
        self.assertNotIn("uplinkDevice", rows[1])

    def test_duration_formatting(self):
        from datetime import datetime, timezone
        from unifi_api.commands import _duration
        now = datetime(2026, 11, 3, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(_duration("2026-11-01T10:00:00Z", now), "2d 2h 30m")
        self.assertEqual(_duration("2026-11-03T12:00:00+00:00", now), "0h 30m")
        self.assertIsNone(_duration("not a date", now))
        self.assertIsNone(_duration("2026-11-04T00:00:00Z", now))

    def test_find_searches_both_collections(self):
        for selector, expected in (("Office", "device"), ("10.0.0", "client"), ("1122.3344.5566", "client")):
            code, out, err = self.run_cli(["find", selector, "--json"])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(out)[0]["kind"], expected)

    def test_ports_preserve_poe_and_do_not_guess_client_associations(self):
        code, out, err = self.run_cli(["ports", "Office Switch", "--json"])
        self.assertEqual((code, err), (0, ""))
        rows = json.loads(out)
        self.assertEqual(rows[0]["speedMbps"], 1000)
        self.assertTrue(rows[0]["poe"]["enabled"])
        self.assertIsNone(rows[0]["connectedClients"])
        self.clients[0]["uplinkPortIdx"] = 1
        _, out, _ = self.run_cli(["ports", "Office Switch", "--json"])
        self.assertEqual(json.loads(out)[0]["connectedClients"], ["Laptop"])
        self.assertEqual(json.loads(out)[1]["connectedClients"], [])

    def test_wifi_and_wan_routes_and_site_options(self):
        for command, path in (("wifi", "wifi/broadcasts"), ("wan", "wans")):
            code, out, err = self.run_cli([command, "--site", "site-b", "--json"])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(len(json.loads(out)), 1)
            self.assertEqual(self.request.call_args[0][1], "sites/site-b/" + path)

    def test_watch_refresh_count_and_interval(self):
        with patch("unifi_api.cli.time.sleep") as sleep:
            code, out, err = self.run_cli(["watch", "clients", "--interval", "0.5", "--count", "2", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(out.count('"name": "Laptop"'), 2)
        self.assertEqual(err.count("Updated"), 2)
        sleep.assert_called_once_with(0.5)

    def test_watch_ctrl_c_exits_shell(self):
        with patch("unifi_api.cli.time.sleep", side_effect=KeyboardInterrupt()):
            code, _, _ = self.run_cli(["shell"], ["watch clients", "clients"])
        self.assertEqual(code, 130)
        # One refresh: the client list plus uplink device names; the second command never runs.
        self.assertEqual(self.request.call_count, 2)

    def test_watch_rejects_writes_and_nested_wrappers(self):
        for target in ("request", "use", "watch", "export"):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                self.run_cli(["watch", target])
        self.request.assert_not_called()

    def test_export_full_fields_unicode_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "clients.csv"
            self.clients[0]["name"] = "Café, Laptop"
            code, _, err = self.run_cli(["export", "clients", str(filename)])
            self.assertEqual((code, err), (0, ""))
            with filename.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(rows[0]["name"], "Café, Laptop")
            self.assertEqual(rows[0]["id"], "laptop")
            self.assertEqual(rows[0]["access.type"], "DEFAULT")
            previous = filename.read_bytes()
            self.request.reset_mock()
            code, _, err = self.run_cli(["export", "clients", str(filename)])
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
            self.assertEqual(filename.read_bytes(), previous)
            self.request.assert_not_called()
            code, _, err = self.run_cli(["export", "clients", str(filename), "--force"])
            self.assertEqual((code, err), (0, ""))

    def test_nested_help_and_bad_args_keep_shell_running(self):
        code, out, err = self.run_cli(["shell"], ["watch clients --bad", "help watch", "status", "exit"])
        self.assertEqual(code, 0)
        self.assertIn("unrecognized arguments", err)
        self.assertIn("--interval", out)
        self.assertIn("Connected clients", out)


if __name__ == "__main__":
    unittest.main()
