# UniFi Network API client

A Python 3.7+ client and command line tool for the local UniFi Network REST API, including PyPy 3.7. No runtime dependencies are required. The API key is loaded from a JSON config file and sent in the `X-API-Key` header.

## Setup

From this directory in PowerShell:

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

Replace the placeholder `api_key` with a **local controller API key** created in UniFi's Integrations settings. `config.json` is ignored by Git; keep its contents private.

The supplied configuration targets `https://opus2.local:11443` and `/proxy/network/integration/v1`. The documentation URL `/unifi-api/network` is a web UI route, not the REST API base path. Authenticated read access has been checked against this controller. The local documentation returns the UniFi OS application shell; endpoint definitions were checked against the official Network reference and actual controller responses.

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
unifi> networks --site YOUR_SITE_UUID
unifi> format json
unifi> sites
unifi> format table
unifi> help request
unifi> exit
```

Use `help` to display the command table, `help COMMAND` for options, and `exit`, `quit`, or Ctrl+C to close the prompt. Ctrl+C also exits during a running command, with exit code 130. EOF closes the prompt (Ctrl+D on Ubuntu; Ctrl+Z then Enter on Windows). Command errors leave the prompt open. Quote arguments containing spaces, including Windows file paths.

Use Up/Down to navigate previously entered commands and edit them before pressing Enter. On Ubuntu, line editing and history use Python's built-in `readline` module; Windows consoles provide native input history. History is kept for the current process only and is not saved to disk.

Existing commands also work directly:

```powershell
python -m unifi_api sites
python -m unifi_api sites --json
python -m unifi_api devices --site YOUR_SITE_UUID
python -m unifi_api clients --site YOUR_SITE_UUID
python -m unifi_api networks --site YOUR_SITE_UUID
python -m unifi_api networks --site YOUR_SITE_UUID --json
python -m unifi_api --config config.json request GET sites/YOUR_SITE_UUID/networks --param limit=25 --param offset=0
```

Choose a site in the prompt with `use "Site Name"` or `use SITE_UUID`. Alternatively, copy a UUID from `sites --json` into the optional `site_id` config setting. An explicit `--site` overrides the session site, which overrides the config default. The list commands retrieve all pages; `--limit` controls the page size. `--filter` passes a UniFi filter expression where supported (WAN definitions do not support filters). API results are tables by default. Add `--json` to any API query to preserve the full JSON response for scripts. In the prompt, `format table` or `format json` changes the session default; `--json` overrides it for one command. Nested object fields appear as dotted columns; long cells wrap without truncation. Paginated responses from `request` show metadata and data in separate tables. Errors go to stderr, and failed direct commands return a nonzero exit code.

## Network utility commands

All queries work in the prompt and as direct commands, for example `python -m unifi_api status --json`. `use` applies only inside the interactive session and does not change the config file.

| Command | Purpose |
| --- | --- |
| `use NAME-OR-UUID` | Select a site for this session |
| `status` | Count devices by reported state and connected clients by type |
| `device NAME-IP-MAC-OR-UUID` | Retrieve one device's details |
| `client NAME-IP-MAC-OR-UUID` | Retrieve one connected client's details |
| `ports DEVICE` | Show port indexes, states, negotiated/max speeds, and PoE fields |
| `wifi` | List Wi-Fi broadcast settings, including enabled state, frequencies, and security type where returned |
| `wan` | List available WAN interface definitions |
| `find TEXT` | Search device and client names, IPs, MACs, and UUIDs |
| `watch COMMAND --interval SECONDS` | Re-run a read command; default interval is 5 seconds |
| `export COMMAND FILE.csv` | Export full results as UTF-8 CSV |

```text
unifi> use "Home"
unifi> status
unifi> device "Office Switch"
unifi> client 192.168.1.20
unifi> ports "Office Switch"
unifi> wifi
unifi> wan
unifi> find laptop
unifi> watch clients --interval 5
```

Lookups prefer exact matches, then accept a unique partial match. MAC addresses accept colon, dash, dot, or unseparated forms. Ambiguous lookups report an error instead of choosing a device. `find` returns all matches. Add `--site SITE_UUID` or `--json` to any query.

The ports command preserves fields actually returned by the controller. `connectedClients: null` means client-to-port associations are unavailable; it does not mean that the port has no clients. The current controller supplies an upstream device ID without a port index. Clients can be associated when a controller also returns `uplinkPortIdx`. WAN definitions currently expose names and IDs, not internet health or connection status. Device health in `status` is the controller's reported device state, not an active connectivity test. Unsupported endpoints report the API error rather than silently returning an empty result.

Watch supports the list, lookup, status, and search commands. Nested wrappers, site changes, and general `request` calls are excluded. Ctrl+C exits the utility, including from watch. Use `--count` to finish after a fixed number of refreshes and return to the prompt:

```text
unifi> watch status --interval 5 --count 3
unifi> watch clients --site SITE_UUID --json --count 2
unifi> export clients clients.csv
unifi> export devices devices.csv --site SITE_UUID
unifi> export ports ports.csv "Office Switch"
unifi> export clients clients.csv --force
```

CSV export includes all fields regardless of table column visibility, flattens nested object keys into dotted columns, and serializes lists as JSON cells. An empty result creates an empty file. Export refuses to overwrite an existing file unless `--force` is specified. For commands with a selector, place it after the output filename. Watch timestamps are written to stderr; each refresh's query output goes to stdout.

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
