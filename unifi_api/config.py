"""Load credentials and connection settings from a JSON file."""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str = field(repr=False)
    api_path: str = "/proxy/network/integration/v1"
    verify_ssl: bool = True
    timeout: float = 30
    site_id: Optional[str] = None
    ca_bundle: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.base_url, str):
            raise ConfigError("base_url must be an HTTPS URL")
        try:
            url = urlsplit(self.base_url)
            port = url.port
        except ValueError:
            raise ConfigError("base_url is invalid") from None
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ("", "/")):
            raise ConfigError("base_url must be an HTTPS origin, e.g. https://opus2.local:11443")
        if (not isinstance(self.api_key, str) or not self.api_key.strip()
                or self.api_key == "REPLACE_WITH_YOUR_LOCAL_API_KEY"
                or any(ord(c) < 32 or ord(c) > 126 for c in self.api_key)):
            raise ConfigError("Set api_key to your local UniFi API key in the config file")
        if (not isinstance(self.api_path, str) or not self.api_path.startswith("/")
                or self.api_path.startswith("//") or any(c in self.api_path for c in "?#\\")
                or any(p in (".", "..") for p in self.api_path.split("/"))):
            raise ConfigError("api_path must be an absolute URL path")
        if not isinstance(self.verify_ssl, bool):
            raise ConfigError("verify_ssl must be true or false")
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout) or self.timeout <= 0):
            raise ConfigError("timeout must be a positive number of seconds")
        for name in ("site_id", "ca_bundle"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ConfigError(f"{name} must be a nonempty string or null")

    @classmethod
    def load(cls, path="config.json"):
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except OSError:
            raise ConfigError(f"Cannot read config file: {path}. Copy config.example.json to config.json first.") from None
        except (ValueError, UnicodeError):
            raise ConfigError(f"Invalid JSON in config file: {path}") from None
        if not isinstance(data, dict):
            raise ConfigError("Config must be a JSON object")
        allowed = set(cls.__dataclass_fields__)
        if set(data) - allowed:
            raise ConfigError("Config contains unknown settings")
        if not {"base_url", "api_key"} <= data.keys():
            raise ConfigError("Config requires base_url and api_key")
        if isinstance(data.get("ca_bundle"), str) and data["ca_bundle"]:
            data["ca_bundle"] = str((path.resolve().parent / data["ca_bundle"]).resolve())
        return cls(**data)
