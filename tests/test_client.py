import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

from unifi_api import APIError, Config, ConfigError, UniFiClient
from unifi_api.cli import main


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = UniFiClient(Config("https://controller.local:11443", "secret-test-key"))
        self.opener = Mock()
        self.client._opener = self.opener

    def respond(self, data):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(data))
        response.__exit__ = Mock(return_value=False)
        self.opener.open.return_value = response

    def test_request_auth_query_and_body(self):
        self.respond(b'{"id":"created"}')
        self.assertEqual(self.client.request("POST", "/sites/a/networks", params={"filter": "name.eq('Guest WiFi')"}, body={"name": "Guest"}), {"id": "created"})
        req = self.opener.open.call_args[0][0]
        self.assertEqual(req.get_header("X-api-key"), "secret-test-key")
        self.assertTrue(req.full_url.startswith("https://controller.local:11443/proxy/network/integration/v1/sites/a/networks?"))
        self.assertIn("Guest+WiFi", req.full_url)
        self.assertEqual(json.loads(req.data), {"name": "Guest"})
        self.assertEqual(self.opener.open.call_args[1]["timeout"], 30)

    def test_pagination_uses_actual_page_length(self):
        self.client.request = Mock(side_effect=[
            {"data": [{"id": 1}], "totalCount": 2},
            {"data": [{"id": 2}], "totalCount": 2},
        ])
        self.assertEqual(list(self.client.sites(limit=25)), [{"id": 1}, {"id": 2}])
        self.assertEqual(self.client.request.call_args[1]["params"]["offset"], 1)

    def test_missing_total_stops_on_empty_page(self):
        self.client.request = Mock(side_effect=[{"data": [1]}, {"data": []}])
        self.assertEqual(list(self.client.sites()), [1])

    def test_errors_do_not_echo_key_or_response(self):
        self.opener.open.side_effect = HTTPError("https://controller.local", 401, "secret-test-key", {}, io.BytesIO(b"secret-test-key"))
        with self.assertRaises(APIError) as caught:
            self.client.request("GET", "sites")
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_empty_and_non_json_responses(self):
        self.respond(b"")
        self.assertIsNone(self.client.request("DELETE", "sites/a/networks/b"))
        self.respond(b"<html>UniFi OS</html>")
        with self.assertRaisesRegex(APIError, "invalid JSON"):
            self.client.request("GET", "sites")

    def test_external_paths_and_traversal_rejected(self):
        for path in ("https://evil.example/sites", "//evil.example", "../sites", "%2e%2e/sites", "sites?x=1", "sites#x"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.client.request("GET", path)
        self.opener.open.assert_not_called()

    def test_redirects_are_not_followed(self):
        from unifi_api.client import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_default_site(self):
        client = UniFiClient(Config("https://controller.local", "key", site_id="site-uuid"))
        client.request = Mock(return_value={"data": []})
        self.assertEqual(list(client.devices()), [])
        self.assertEqual(client.request.call_args[0][1], "sites/site-uuid/devices")


class ConfigTests(unittest.TestCase):
    def test_load_and_redacted_repr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"base_url": "https://controller.local", "api_key": "private-key", "ca_bundle": "controller.pem"}), encoding="utf-8")
            config = Config.load(path)
            self.assertEqual(config.api_key, "private-key")
            self.assertEqual(config.ca_bundle, str(Path(directory).resolve() / "controller.pem"))
            self.assertNotIn("private-key", repr(config))

    def test_invalid_settings(self):
        for values in ({"api_key": ""}, {"timeout": -1}, {"verify_ssl": "false"}, {"base_url": "http://controller.local"}, {"api_key": "bad\r\nheader"}):
            config = {"base_url": "https://controller.local", "api_key": "key", **values}
            with self.subTest(values=values), self.assertRaises(ConfigError):
                Config(**config)

    def test_missing_config_cli_error(self):
        from contextlib import redirect_stderr
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main(["--config", str(Path(directory) / "missing.json"), "sites"]), 1)
            self.assertIn("Cannot read config file", output.getvalue())


if __name__ == "__main__":
    unittest.main()
