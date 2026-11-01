# UniFi Network API client

A Python 3.7+ client and command line tool for the local UniFi Network REST API, including PyPy 3.7. No runtime dependencies are required. The API key is loaded from a JSON config file and sent in the `X-API-Key` header.

## Setup

From this directory in PowerShell:

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

Replace the placeholder `api_key` with a **local controller API key** created in UniFi's Integrations settings. `config.json` is ignored by Git; keep its contents private.

The supplied configuration targets `https://opus2.local:11443` and `/proxy/network/integration/v1`. The documentation URL `/unifi-api/network` is a web UI route, not the REST API base path. The proxy route returned HTTP 401 without credentials during setup; authenticated requests still need to be verified with your key. The local documentation returned the UniFi OS application shell, so controller-specific endpoint/version coverage has not been verified.

## Usage

Run directly from the project directory:

```powershell
python -m unifi_api
```

This opens the interactive `unifi>` command prompt and displays the available commands in a table. You can also start it explicitly with `python -m unifi_api shell`. It loads the config once and reuses the connection settings throughout the session.

```text
unifi> sites
unifi> devices --site YOUR_SITE_UUID
unifi> clients --site YOUR_SITE_UUID --json
unifi> format json
unifi> sites
unifi> format table
unifi> help request
unifi> exit
```

Use `help` to display the command table, `help COMMAND` for options, and `exit` or `quit` to close the prompt. Ctrl+C cancels the current command; EOF closes the prompt (Ctrl+Z then Enter on Windows). Command errors leave the prompt open. Quote arguments containing spaces, including Windows file paths.

Existing commands also work directly:

```powershell
python -m unifi_api sites
python -m unifi_api sites --json
python -m unifi_api devices --site YOUR_SITE_UUID
python -m unifi_api clients --site YOUR_SITE_UUID
python -m unifi_api --config config.json request GET sites/YOUR_SITE_UUID/networks --param limit=25 --param offset=0
```

Copy a site UUID from `sites` into the optional `site_id` config setting to omit `--site`. The list commands retrieve all pages; `--limit` controls the page size. `--filter` passes a UniFi filter expression where supported. API results are tables by default. Add `--json` to any API command to preserve the full JSON response for scripts. In the prompt, `format table` or `format json` changes the session default; `--json` overrides it for one command. Nested object fields appear as dotted columns; long cells wrap without truncation. Paginated responses from `request` show metadata and data in separate tables. Errors go to stderr, and failed direct commands return a nonzero exit code.

The general `request` command accepts GET, POST, PUT, PATCH, and DELETE. Paths are relative to `api_path`; pass query parameters using repeated `--param KEY=VALUE`. For a write request, pass a JSON file with `--body payload.json`. Writes execute immediately, so use the documented endpoint and review the payload first. Endpoint availability and payload schemas depend on your installed Network version.

Optionally install the command in a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\unifi sites
```

## Configuration

| Setting | Meaning |
| --- | --- |
| `base_url` | HTTPS controller origin, including port |
| `api_key` | Required local API key |
| `api_path` | Defaults to `/proxy/network/integration/v1`; standalone Network deployments may use `/integration/v1` |
| `site_id` | Optional default site UUID |
| `timeout` | Positive request timeout in seconds; default 30 |
| `verify_ssl` | Verify TLS certificates; default `true` |
| `ca_bundle` | Optional PEM CA bundle path, resolved relative to the config file |

For a private certificate authority, add `"ca_bundle": "controller-ca.pem"` and supply its trusted CA certificate. For local development with a self-signed certificate, `"verify_ssl": false` is available; it disables certificate validation and prints a CLI warning. Verification remains enabled by default.

Connections go directly to the controller without environment proxy settings. Redirects are rejected to avoid forwarding the API key. Requests are not automatically retried, including write requests.

## Python usage

```python
from unifi_api import UniFiClient

client = UniFiClient.from_config("config.json")
for site in client.sites():
    print(site["id"], site["name"])

devices = list(client.devices("YOUR_SITE_UUID"))
page = client.request("GET", "sites/YOUR_SITE_UUID/networks", params={"limit": 25})
```

## Validation

```powershell
python -m unittest discover -s tests -v
```

Tests use a mocked transport and do not modify the controller. Run `python -m unifi_api sites` after supplying the key to check real authentication and TLS trust.

References: [local API documentation](https://opus2.local:11443/unifi-api/network), [official UniFi API getting started](https://help.ui.com/hc/en-us/articles/30076656117655-Getting-Started-with-the-Official-UniFi-API), and [Network API reference](https://developer.ui.com/network).
