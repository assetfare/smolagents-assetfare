"""AssetFare local-only session capability token generator for smolagents agents.

Self-contained smolagents ``Tool`` (Hub-loadable via ``load_tool``). It generates
ONE caller-owned session capability token purely locally: it makes NO network call,
touches no wallet, and returns a >=256-bit CSPRNG url-safe token (43-128 chars)
marked SENSITIVE. The token is a bearer capability, NOT a private key, and cannot
move funds.

The CALLER (not the server) owns the token: pass it into ``assetfare_session_create``
and every session read/observe/refresh call. It is sent to AssetFare only in the
``X-AssetFare-Session-Token`` header; the server stores only its hash and never
returns it. Because the caller holds it, a lost ``session_create`` response can be
retried with the SAME token + idempotency key to recover the SAME session. Never
log, telemetry, or persist it in plaintext.

All logic lives inside this class (imports done inside methods, no sibling-module
imports) so ``Tool.to_dict`` / ``push_to_hub`` can serialise it to a single file.
"""

from typing import Any

from smolagents import Tool


class AssetFareNewSessionCapabilityTool(Tool):
    name = "assetfare_new_session_capability"
    description = (
        "Local-only: generate ONE caller-owned high-entropy AssetFare session "
        "capability token (>=256-bit CSPRNG, url-safe, 43-128 chars). Makes NO network "
        "call, touches no wallet, and returns nothing about AssetFare's remote state. "
        "Store the returned token as a SENSITIVE bearer capability (never a private key; "
        "it cannot move funds); pass it into assetfare_session_create and every session "
        "read/observe/refresh call. It is sent to AssetFare only in the "
        "X-AssetFare-Session-Token header; the server stores only its hash and never "
        "returns it. Because the caller (not the server) owns the token, retrying a lost "
        "session_create with the same token + idempotency_key recovers the same session. "
        "Never log, telemetry, or persist it in plaintext. Takes no inputs. This tool "
        "does NOT execute, bridge, swap, sign or move funds and never generates a private key."
    )
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
