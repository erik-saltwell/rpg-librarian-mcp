from __future__ import annotations

import os
import tempfile

import msal

from ..errors import UsageError
from .config import Config


def token(config: Config, *, interactive: bool = False) -> str:
    cache = msal.SerializableTokenCache()
    if config.cache.exists():
        cache.deserialize(config.cache.read_text())
    client = msal.PublicClientApplication(
        config.client, authority=config.authority, token_cache=cache
    )
    accounts = client.get_accounts()
    result = (
        client.acquire_token_silent(config.scopes, account=accounts[0])
        if accounts
        else None
    )
    if not result and interactive:
        flow = client.initiate_device_flow(scopes=config.scopes)
        if "user_code" not in flow:
            raise UsageError("Could not start Microsoft device authorization.")
        print(
            f"Open {flow['verification_uri']} and enter {flow['user_code']}.",
            flush=True,
        )
        result = client.acquire_token_by_device_flow(flow)
    if cache.has_state_changed:
        config.cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=config.cache.parent, prefix=".msal-")
        try:
            with os.fdopen(fd, "w") as output:
                output.write(cache.serialize())
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, config.cache)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    if not result or "access_token" not in result:
        raise UsageError(
            "Microsoft sign-in is required. Run `import-source auth brendan`."
        )
    return result["access_token"]
