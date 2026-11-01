import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

from unifi_api import APIError
from unifi_api.cli import main
from unifi_api.output import render


class OutputTests(unittest.TestCase):
    def test_table_contains_union_of_fields_and_nested_values(self):
        output = render([{"id": "a", "name": "Office", "access": {"type": "GUEST"}},
                         {"id": "b", "ipAddress": "10.0.0.2"}])
        for value in ("id", "Office", "access.type", "GUEST", "ipAddress", "10.0.0.2"):
            self.assertIn(value, output)
        self.assertTrue(output.startswith("+"))

    def test_page_metadata_and_rows(self):
        output = render({"totalCount": 1, "data": [{"name": "Office"}]})
        self.assertIn("totalCount", output)
        self.assertIn("Office", output)

    def test_empty_scalar_and_long_values(self):
        self.assertEqual(render([]), "No results.")
        self.assertIn("no response body", render(None))
        self.assertIn("true", render(True))
        self.assertIn("empty object", render({}))
        self.assertIn("|", render({"": ""}))
        self.assertIn("x" * 40, render({"name": "x" * 90}))

    def test_control_characters_are_visible(self):
        output = render([{"name": "Office\n\x1b[31m"}])
        self.assertIn(r"Office\n\x1b[31m", output)
        self.assertNotIn("\x1b", output)

    def test_json_preserves_original_result(self):
        result = {"totalCount": 1, "data": [{"nested": {"value": "\n"}}]}
        self.assertEqual(json.loads(render(result, "json")), result)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.config.verify_ssl = True
        self.client.sites.return_value = [{"id": "site-1", "name": "Office",
                                           "uplinkDeviceId": "uplink-1", "access": {"type": "GUEST"}}]
        self.client.devices.return_value = [{"name": "Switch"}]

    def run_cli(self, args, commands=None):
        with patch("unifi_api.cli.UniFiClient.from_config", return_value=self.client), \
                patch("builtins.input", side_effect=commands or []), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_one_shot_table_and_json_before_or_after_command(self):
        code, output, _ = self.run_cli(["sites"])
        self.assertEqual(code, 0)
        self.assertIn("| name", output)
        for column in ("id", "uplinkDeviceId", "access.type"):
            self.assertNotIn(column, output)
        for args in (["sites", "--json"], ["--json", "sites"]):
            code, output, _ = self.run_cli(args)
            self.assertEqual(json.loads(output), self.client.sites.return_value)

    def test_shell_defaults_and_reuses_client(self):
        code, output, _ = self.run_cli([], ["sites", "devices --site site-1", "exit"])
        self.assertEqual(code, 0)
        self.assertIn("Command", output)
        self.assertIn("Office", output)
        self.assertIn("Switch", output)
        self.client.devices.assert_called_once_with(site_id="site-1", limit=25, filter=None)

    def test_shell_recovers_from_errors_help_and_interrupts(self):
        self.client.sites.side_effect = [APIError("Unavailable"), [{"name": "Recovered"}]]
        code, output, errors = self.run_cli(["shell"], ["", "unknown", "help sites", "sites", KeyboardInterrupt(), "sites", EOFError()])
        self.assertEqual(code, 0)
        self.assertIn("invalid choice", errors)
        self.assertIn("Unavailable", errors)
        self.assertIn("--filter", output)
        self.assertIn("Recovered", output)
        self.assertIn("Command cancelled", output)

    def test_shell_json_and_persistent_format(self):
        code, output, _ = self.run_cli(["shell"], ["sites --json", "format json", "sites", "format table", "sites", "quit"])
        self.assertEqual(code, 0)
        self.assertEqual(output.count('"id": "site-1"'), 2)
        self.assertIn("| Office", output)
        self.assertNotIn("| site-1", output)

    def test_shell_quotes_and_windows_paths(self):
        self.client.request.return_value = None
        with patch("pathlib.Path.read_text", return_value='{"name":"Guest"}') as read:
            code, _, errors = self.run_cli(["shell"], [
                'sites --filter "name.eq(\'Guest WiFi\')"',
                'request POST sites/site-1/networks --body "C:\\My Files\\body.json"',
                "quit",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.client.sites.assert_called_once_with(limit=25, filter="name.eq('Guest WiFi')")
        read.assert_called_once()
        self.client.request.assert_called_once_with("POST", "sites/site-1/networks", params=[], body={"name": "Guest"})


if __name__ == "__main__":
    unittest.main()
