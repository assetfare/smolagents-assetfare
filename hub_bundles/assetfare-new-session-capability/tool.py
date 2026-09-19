from smolagents.tools import Tool
from typing import Any, Optional
import re
import secrets

class AssetFareNewSessionCapabilityTool(Tool):
    name = "assetfare_new_session_capability"
    description = "Local-only: generate ONE caller-owned high-entropy AssetFare session capability token (>=256-bit CSPRNG, url-safe, 43-128 chars). Makes NO network call, touches no wallet, and returns nothing about AssetFare's remote state. Store the returned token as a SENSITIVE bearer capability (never a private key; it cannot move funds); pass it into assetfare_session_create and every session read/observe/refresh call. It is sent to AssetFare only in the X-AssetFare-Session-Token header; the server stores only its hash and never returns it. Because the caller (not the server) owns the token, retrying a lost session_create with the same token + idempotency_key recovers the same session. Never log, telemetry, or persist it in plaintext. Takes no inputs. This tool does NOT execute, bridge, swap, sign or move funds and never generates a private key."
    inputs = {}
    output_type = "object"

    def __init__(self, **_hub_kwargs: Any) -> None:
        # smolagents' Tool.from_hub/from_code forward Hub download kwargs
        # (revision, cache_dir, subfolder, ...) straight to the tool constructor,
        # so accept and ignore them; otherwise load_tool(..., revision=...) fails.
        super().__init__()

    def _get_requirements(self) -> str:
        # This tool makes no network call, but pin the same reproducible runtime deps
        # the loading agent's env uses for the sibling AssetFare tools.
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def forward(self) -> Any:
        import re
        import secrets

        token = secrets.token_urlsafe(32)  # 32 bytes = 256 bits -> 43 url-safe chars
        if not re.match(r"^[A-Za-z0-9_-]{43,128}$", token):
            raise ValueError("assetfare_session_token_generation_failed")
        return {
            "session_token": token,
            "token_bits": 256,
            "token_length": len(token),
            "sensitivity": "sensitive_capability",
            "is_private_key": False,
            "network_calls": 0,
            "usage": (
                "Pass this token as session_token to assetfare_session_create and to every "
                "session get/observe/refresh call. It is sent to AssetFare only in the "
                "X-AssetFare-Session-Token header; the server stores only its hash and never "
                "returns it. Treat it like a bearer credential: never log, share, or persist it "
                "in plaintext. It is NOT a private key and cannot move funds. Retrying a lost "
                "session_create with the same token + idempotency_key recovers the same session."
            ),
            "server_signing": False,
            "server_submission": False,
        }
