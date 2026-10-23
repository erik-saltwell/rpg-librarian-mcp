from __future__ import annotations

import os
import tempfile
import time

import msal

from ..errors import UsageError
from .config import Config


class TokenProvider:
    """Reuse MSAL and silently renew before expiry; never log token material."""

    def __init__(self, config: Config):
        self.config = config
        self.cache = msal.SerializableTokenCache()
        if config.cache.exists():
            self.cache.deserialize(config.cache.read_text())
        self.client = msal.PublicClientApplication(
            config.client, authority=config.authority, token_cache=self.cache
        )
        self.expires_at = 0.0
        self.access_token: str | None = None

    def get(self, *, interactive: bool = False, force_refresh: bool = False) -> str:
        if (
            self.access_token
            and time.time() < self.expires_at - 120
            and not force_refresh
        ):
            return self.access_token
        accounts = self.client.get_accounts()
        result = (
            self.client.acquire_token_silent(
                self.config.scopes, account=accounts[0], force_refresh=force_refresh
            )
            if accounts
            else None
        )
        if (not result or "access_token" not in result) and interactive:
            flow = self.client.initiate_device_flow(scopes=self.config.scopes)
            if "user_code" not in flow:
                raise UsageError("Could not start Microsoft device authorization.")
            print(
                f"Open {flow['verification_uri']} and enter {flow['user_code']}.",
                flush=True,
            )
            result = self.client.acquire_token_by_device_flow(flow)
        self.save()
        if not result or "access_token" not in result:
            raise UsageError(
                "Microsoft sign-in is required. Run `sync-source auth <source-name>`."
            )
        self.access_token = result["access_token"]
        self.expires_at = float(
            result.get("expires_on")
            or time.time() + float(result.get("expires_in", 300))
        )
        return self.access_token

    def save(self) -> None:
        if not self.cache.has_state_changed:
            return
        self.config.cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.config.cache.parent, prefix=".msal-")
        try:
            with os.fdopen(fd, "w") as output:
                output.write(self.cache.serialize())
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.config.cache)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def token(
    config: Config, *, interactive: bool = False, force_refresh: bool = False
) -> str:
    return TokenProvider(config).get(
        interactive=interactive, force_refresh=force_refresh
    )
