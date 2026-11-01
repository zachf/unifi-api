"""HTTP transport for the local Network integration API (no third-party dependencies)."""

import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .config import Config


class APIError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the API key through redirects.
        return None


class UniFiClient:
    def __init__(self, config: Config):
        self.config = config
        context = ssl.create_default_context(cafile=config.ca_bundle)
        if not config.verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        # Local controllers should be reached directly, independent of proxy env vars.
        self._opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _NoRedirect())

    @classmethod
    def from_config(cls, path="config.json"):
        return cls(Config.load(path))

    def request(self, method, path, *, params=None, body=None):
        """Call a path relative to api_path. Returns decoded JSON, or None for an empty body."""
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported HTTP method")
        parsed = urlsplit(path)
        decoded = unquote(path)
        if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                or decoded.startswith("//") or "\\" in decoded
                or any(p in (".", "..") for p in decoded.split("/"))):
            raise ValueError("Use a relative API path without a query or traversal; pass query values as params")
        url = self.config.base_url.rstrip("/") + self.config.api_path.rstrip("/") + "/" + path.lstrip("/")
        if params:
            url += "?" + urlencode(params, doseq=True)
        headers = {"X-API-Key": self.config.api_key, "Accept": "application/json"}
        payload = None
        if body is not None:
            payload = json.dumps(body, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self.config.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            hints = {401: "Check the local API key", 403: "Check API key permissions",
                     404: "Check api_path and endpoint support on your Network version",
                     429: "Rate limited; try again later"}
            # Do not echo response bodies, which may contain credentials or private data.
            raise APIError(f"HTTP {exc.code}. {hints.get(exc.code, 'Request failed')}", exc.code) from None
        except (URLError, OSError):
            raise APIError("Connection failed. Check base_url, connectivity, timeout, and TLS trust (ca_bundle).") from None
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise APIError("Server returned invalid JSON. Check api_path; the URL may point to the UniFi web UI.") from None

    def iter_items(self, path, *, limit=25, offset=0, filter=None):
        """Iterate a paginated UniFi collection without loading it all into memory."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        while True:
            params = {"offset": offset, "limit": limit}
            if filter is not None:
                params["filter"] = filter
            page = self.request("GET", path, params=params)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise APIError("Expected a paginated response containing a data array")
            items = page["data"]
            if not items:
                return
            yield from items
            offset += len(items)
            total = page.get("totalCount")
            if isinstance(total, int) and offset >= total:
                return

    def sites(self, **kwargs):
        return self.iter_items("sites", **kwargs)

    def _site_path(self, site_id, collection):
        site_id = site_id or self.config.site_id
        if not site_id:
            raise ValueError("Provide --site or set site_id in the config file")
        return f"sites/{quote(site_id, safe='')}/{collection}"

    def devices(self, site_id=None, **kwargs):
        return self.iter_items(self._site_path(site_id, "devices"), **kwargs)

    def clients(self, site_id=None, **kwargs):
        return self.iter_items(self._site_path(site_id, "clients"), **kwargs)
