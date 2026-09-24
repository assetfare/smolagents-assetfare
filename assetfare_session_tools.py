"""AssetFare caller-approved v2 session lifecycle tools for smolagents agents.

Five self-contained smolagents ``Tool`` classes (each Hub-loadable via ``load_tool``),
one per lifecycle step of the non-custodial ``POST /v2/session`` receipt-driven
workflow:

  - ``AssetFareSessionCreateTool``   -> POST   /v2/session
  - ``AssetFareSessionGetTool``      -> GET    /v2/session/{id}
  - ``AssetFareObserveSourceTool``   -> POST   /v2/session/{id}/observe-source
  - ``AssetFareObserveOutputTool``   -> POST   /v2/session/{id}/observe-output
  - ``AssetFareRefreshActionTool``   -> POST   /v2/session/{id}/refresh-action

None of these sign, submit, receive a private key/seed, or auto-chain. Session
create requires the literal ``caller_approved`` True and a CALLER-GENERATED session
capability token (from ``assetfare_new_session_capability``) supplied as REQUIRED
input; the create tool does NOT generate the token, so a lost create response
retried with the same token + idempotency_key recovers the SAME session. The token
is sent only in the ``X-AssetFare-Session-Token`` header. observe-source /
observe-output accept only the caller's ALREADY-submitted transaction hashes; they
never submit. Every response fails closed on any server signing/submission claim.

All logic lives inside each class (imports done inside methods, no sibling-module
imports) so ``Tool.to_dict`` / ``push_to_hub`` can serialise each to a single file.
Injectable ``session`` / ``monotonic`` let the tools be unit-tested offline with mocks.
"""

from typing import Any, Optional

from smolagents import Tool


class AssetFareSessionCreateTool(Tool):
    name = "assetfare_session_create"
    description = (
        "Explicit caller-approved, non-custodial POST /v2/session create for an "
        "AssetFare route whose fresh quote reports current availability (fixed origin https://api.assetfare.dev). Before "
        "creating it, compare fresh AssetFare and competitor quotes at the actual intended amount; USD 1 is smoke-only, "
        "USD 50 is merely the lowest observed native-USDC winning bucket, and USD 1,000 is a representative example, "
        "not an approval or guarantee. It "
        "opens one idempotent receipt-driven session and returns its first workflow "
        "state / unsigned action for the caller to verify, sign and submit with their "
        "OWN wallet. It never signs, never submits, never receives a private key or seed, "
        "and never auto-chains. It requires the literal caller_approved true, the route's "
        "own PUBLIC wallet addresses, a caller-generated session capability token (from "
        "assetfare_new_session_capability) sent only in the X-AssetFare-Session-Token "
        "header, and an idempotency_key; retrying with the SAME token + idempotency_key "
        "recovers the SAME session (lost-response crash recovery). It fails closed before "
        "any network call if caller_approved is not literally true or if any private key / "
        "seed / signed transaction appears anywhere in the input. Inputs: caller_approved, "
        "from_chain, from_token, to_chain, to_token, amount_usd (finite number, minimum 1; no business maximum), wallets (public "
        "addresses only), event_signer_public (Solana-CCTP only: public key of a fresh locally generated ephemeral keypair; private key stays client-side to co-sign), "
        "session_token (the caller-owned capability), idempotency_key. The returned "
        "'server_signs_or_submits' is always false. This tool does NOT execute, bridge, "
        "swap, sign or move funds."
    )
    inputs = {
        "caller_approved": {
            "type": "boolean",
            "description": "Must be the literal boolean true. Explicit caller approval gate; anything else is rejected before any network call.",
        },
        "from_chain": {
            "type": "string",
            "description": "Source chain: one of solana, base, arbitrum, robinhood, polygon, optimism.",
        },
        "from_token": {
            "type": "string",
            "description": "Source token symbol on the source chain, e.g. SOL, ETH, USDC, USDG.",
        },
        "to_chain": {
            "type": "string",
            "description": "Destination chain: one of solana, base, arbitrum, robinhood.",
        },
        "to_token": {
            "type": "string",
            "description": "Destination token symbol on the destination chain, e.g. ETH, USDC, USDG.",
        },
        "amount_usd": {
            "type": "number",
            "description": "Actual intended finite USD amount, minimum 1; no business maximum. Do not substitute the USD 1,000 representative example for caller intent or fresh comparison.",
        },
        "wallets": {
            "type": "object",
            "description": "Map of the route's chains (at least source and destination) to the caller's PUBLIC wallet addresses only. Never a private key or seed.",
        },
        "session_token": {
            "type": "string",
            "description": "Caller-generated session capability token from assetfare_new_session_capability (>=256-bit, url-safe, 43-128 chars). Sent only in the X-AssetFare-Session-Token header. Not a private key.",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Caller idempotency key (8-128 chars). Retrying with the same token + key recovers the same session.",
        },
        "event_signer_public": {
            "type": "string",
            "description": "Solana-CCTP only: public key of a fresh ephemeral Solana keypair generated locally. Keep its private key client-side to co-sign the returned unsigned event-account transaction. Omit when not applicable.",
            "nullable": True,
        },
    }
    output_type = "object"

    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SESSION_TOKEN_HEADER = "X-AssetFare-Session-Token"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576
    MIN_USD = 1.0
    CHAINS = {"arbitrum", "base", "optimism", "polygon", "robinhood", "solana"}
    SOURCE_ONLY_CHAINS = {"optimism", "polygon"}
    ENDPOINTS = {
        "solana:SOL",
        "solana:USDC",
        "solana:USDG",
        "base:ETH",
        "base:USDC",
        "arbitrum:ETH",
        "arbitrum:USDC",
        "robinhood:ETH",
        "robinhood:USDG",
        "polygon:USDC",
        "optimism:USDC",
    }
    FORBIDDEN_SECRET_KEYS = {
        "private_key",
        "privatekey",
        "privkey",
        "secret_key",
        "secretkey",
        "seed",
        "seed_phrase",
        "mnemonic",
        "keypair",
        "secret",
        "signature",
        "signed_transaction",
        "signed_tx",
        "raw_transaction",
        "signed",
        "password",
        "passphrase",
    }

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        import time
        from urllib.parse import urlsplit

        super().__init__()
        parts = urlsplit(base_url or "")
        if (
            parts.scheme != "https"
            or parts.hostname != "api.assetfare.dev"
            or parts.username
            or parts.password
            or parts.port is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("assetfare_base_url_rejected")
        self.base_url = "https://api.assetfare.dev"
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

    def _get_requirements(self) -> str:
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def _is_public_address(self, value: Any) -> bool:
        import re

        return isinstance(value, str) and bool(
            re.match(r"^0x[0-9a-fA-F]{40}$", value) or re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", value)
        )

    def _reject_secret_material(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_secret_material_rejected")
            if isinstance(node, dict):
                for key in node:
                    if str(key).lower() in self.FORBIDDEN_SECRET_KEYS:
                        raise ValueError("assetfare_secret_material_rejected")
                for child in node.values():
                    stack.append((child, depth + 1))
            elif isinstance(node, (list, tuple)):
                for child in node:
                    stack.append((child, depth + 1))

    def _reject_signing_claims(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_safety_boundary_failed")
            if isinstance(node, dict):
                for key in ("server_signing", "server_submission"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                for child in node.values():
                    stack.append((child, depth + 1))
            elif isinstance(node, list):
                for child in node:
                    stack.append((child, depth + 1))

    def _endpoint(self, chain: Any, token: Any, field: str) -> str:
        if not isinstance(chain, str) or not isinstance(token, str):
            raise ValueError("assetfare_" + field + "_endpoint_invalid")
        token_u = token.upper()
        if (chain + ":" + token_u) not in self.ENDPOINTS:
            raise ValueError("assetfare_" + field + "_endpoint_invalid")
        return token_u

    def _amount(self, amount_usd: Any) -> float:
        import math

        if (
            isinstance(amount_usd, bool)
            or not isinstance(amount_usd, (int, float))
            or not math.isfinite(float(amount_usd))
        ):
            raise ValueError("assetfare_amount_invalid")
        amount = float(amount_usd)
        if amount < self.MIN_USD:
            raise ValueError("assetfare_amount_out_of_range")
        return amount

    def _session_token(self, session_token: Any) -> str:
        import re

        if not isinstance(session_token, str) or not re.match(r"^[A-Za-z0-9_-]{43,128}$", session_token):
            raise ValueError("assetfare_session_token_invalid")
        return session_token

    def _idempotency_key(self, idempotency_key: Any) -> str:
        import re

        if not isinstance(idempotency_key, str) or not re.match(r"^[A-Za-z0-9_.:-]{8,128}$", idempotency_key):
            raise ValueError("assetfare_idempotency_key_invalid")
        return idempotency_key

    def _action_intent(
        self,
        caller_approved: Any,
        from_chain: Any,
        from_token: Any,
        to_chain: Any,
        to_token: Any,
        amount_usd: Any,
        wallets: Any,
        event_signer_public: Any,
    ) -> Any:
        if caller_approved is not True:
            raise ValueError("assetfare_caller_approval_required")
        amount = self._amount(amount_usd)
        from_u = self._endpoint(from_chain, from_token, "source")
        to_u = self._endpoint(to_chain, to_token, "destination")
        if (from_chain, from_u) == (to_chain, to_u):
            raise ValueError("assetfare_identity_route_rejected")
        if to_chain in self.SOURCE_ONLY_CHAINS:
            raise ValueError("assetfare_destination_endpoint_invalid")
        if from_chain in self.SOURCE_ONLY_CHAINS and not (
            from_u == "USDC" and to_chain in {"base", "arbitrum"} and to_u == "USDC"
        ):
            raise ValueError("assetfare_source_endpoint_invalid")
        self._reject_secret_material(
            {
                "wallets": wallets,
                "event_signer_public": event_signer_public,
                "from_chain": from_chain,
                "to_chain": to_chain,
            }
        )
        if not isinstance(wallets, dict) or not (1 <= len(wallets) <= 6):
            raise ValueError("assetfare_wallets_invalid")
        for chain, address in wallets.items():
            if chain not in self.CHAINS:
                raise ValueError("assetfare_wallets_invalid")
            if not self._is_public_address(address):
                raise ValueError("assetfare_wallet_not_public_address")
        if from_chain not in wallets or to_chain not in wallets:
            raise ValueError("assetfare_wallets_route_mismatch")
        body = {
            "caller_approved": True,
            "from_chain": from_chain,
            "from_token": from_u,
            "to_chain": to_chain,
            "to_token": to_u,
            "amount_usd": amount,
            "wallets": dict(wallets),
        }
        if event_signer_public is not None:
            if not self._is_public_address(event_signer_public):
                raise ValueError("assetfare_event_signer_not_public_address")
            body["event_signer_public"] = event_signer_public
        return body

    def _request(self, method: str, path: str, payload: Any, budget_deadline: float, extra_headers: Any = None) -> Any:
        import contextlib
        import json

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        remaining = budget_deadline - self._monotonic()
        if remaining <= 0:
            raise ValueError("assetfare_upstream_unavailable")
        timeout = min(self.SOCKET_TIMEOUT_S, remaining)
        headers = {"accept": "application/json", "x-assetfare-channel": "smolagents"}
        if extra_headers:
            headers.update(extra_headers)

        resp = None
        send_failed = False
        try:
            resp = self._session.request(
                method,
                self.base_url + path,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                headers=headers,
                stream=True,
            )
        except Exception:
            send_failed = True
        if send_failed:
            raise ValueError("assetfare_upstream_unavailable")

        try:
            if resp.is_redirect or 300 <= resp.status_code < 400:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code == 429:
                raise ValueError("assetfare_rate_limited")
            if resp.status_code >= 500:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code >= 400:
                raise ValueError("assetfare_request_rejected")
            media = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("assetfare_response_invalid")
            declared = resp.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.MAX_BYTES:
                raise ValueError("assetfare_response_invalid")

            stream_code = None
            chunks = []
            try:
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._monotonic() >= budget_deadline:
                        stream_code = "assetfare_upstream_unavailable"
                        break
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        stream_code = "assetfare_response_invalid"
                        break
                    chunks.append(chunk)
            except Exception:
                stream_code = "assetfare_upstream_unavailable"
            if stream_code is not None:
                raise ValueError(stream_code)

            parse_failed = False
            data = None
            try:
                data = json.loads(b"".join(chunks).decode("utf-8"))
            except Exception:
                parse_failed = True
            if parse_failed:
                raise ValueError("assetfare_response_invalid")
            if not isinstance(data, dict):
                raise ValueError("assetfare_response_invalid")
            return data
        finally:
            if resp is not None:
                with contextlib.suppress(Exception):
                    resp.close()

    def _validate_session(self, payload: Any) -> Any:
        self._reject_signing_claims(payload)
        if not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
            raise ValueError("assetfare_session_invalid")
        if (
            payload.get("server_signing") is not False
            or payload.get("server_submission") is not False
            or payload.get("signed") is not False
            or payload.get("submitted") is not False
        ):
            raise ValueError("assetfare_session_unsafe")
        return payload

    def forward(
        self,
        caller_approved: bool,
        from_chain: str,
        from_token: str,
        to_chain: str,
        to_token: str,
        amount_usd: float,
        wallets: dict,
        session_token: str,
        idempotency_key: str,
        event_signer_public: Optional[str] = None,
    ) -> Any:
        body = self._action_intent(
            caller_approved, from_chain, from_token, to_chain, to_token, amount_usd, wallets, event_signer_public
        )
        token = self._session_token(session_token)
        body["idempotency_key"] = self._idempotency_key(idempotency_key)
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request(
            "POST", "/v2/session", body, budget_deadline, extra_headers={self.SESSION_TOKEN_HEADER: token}
        )
        return self._validate_session(data)


class AssetFareSessionGetTool(Tool):
    name = "assetfare_session_get"
    description = (
        "Read-only GET /v2/session/{session_id} for a caller-owned AssetFare session "
        "(fixed origin https://api.assetfare.dev). Returns the session's current "
        "workflow state and current unsigned action. Requires the caller-owned session "
        "capability token (sent only in the X-AssetFare-Session-Token header) and the "
        "session_id. It never signs, submits, or moves funds; the returned "
        "'server_signs_or_submits' is always false. Inputs: session_token, session_id."
    )
    inputs = {
        "session_token": {
            "type": "string",
            "description": "Caller-owned session capability token (43-128 chars). Sent only in the X-AssetFare-Session-Token header. Not a private key.",
        },
        "session_id": {
            "type": "string",
            "description": "The session UUID returned by assetfare_session_create.",
        },
    }
    output_type = "object"

    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SESSION_TOKEN_HEADER = "X-AssetFare-Session-Token"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        import time
        from urllib.parse import urlsplit

        super().__init__()
        parts = urlsplit(base_url or "")
        if (
            parts.scheme != "https"
            or parts.hostname != "api.assetfare.dev"
            or parts.username
            or parts.password
            or parts.port is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("assetfare_base_url_rejected")
        self.base_url = "https://api.assetfare.dev"
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

    def _get_requirements(self) -> str:
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def _reject_signing_claims(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_safety_boundary_failed")
            if isinstance(node, dict):
                for key in ("server_signing", "server_submission"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                for child in node.values():
                    stack.append((child, depth + 1))
            elif isinstance(node, list):
                for child in node:
                    stack.append((child, depth + 1))

    def _session_token(self, session_token: Any) -> str:
        import re

        if not isinstance(session_token, str) or not re.match(r"^[A-Za-z0-9_-]{43,128}$", session_token):
            raise ValueError("assetfare_session_token_invalid")
        return session_token

    def _session_id(self, session_id: Any) -> str:
        import re

        if not isinstance(session_id, str) or not re.match(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", session_id
        ):
            raise ValueError("assetfare_session_id_invalid")
        return session_id

    def _request(self, method: str, path: str, payload: Any, budget_deadline: float, extra_headers: Any = None) -> Any:
        import contextlib
        import json

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        remaining = budget_deadline - self._monotonic()
        if remaining <= 0:
            raise ValueError("assetfare_upstream_unavailable")
        timeout = min(self.SOCKET_TIMEOUT_S, remaining)
        headers = {"accept": "application/json", "x-assetfare-channel": "smolagents"}
        if extra_headers:
            headers.update(extra_headers)

        resp = None
        send_failed = False
        try:
            resp = self._session.request(
                method,
                self.base_url + path,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                headers=headers,
                stream=True,
            )
        except Exception:
            send_failed = True
        if send_failed:
            raise ValueError("assetfare_upstream_unavailable")

        try:
            if resp.is_redirect or 300 <= resp.status_code < 400:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code == 429:
                raise ValueError("assetfare_rate_limited")
            if resp.status_code >= 500:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code >= 400:
                raise ValueError("assetfare_request_rejected")
            media = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("assetfare_response_invalid")
            declared = resp.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.MAX_BYTES:
                raise ValueError("assetfare_response_invalid")

            stream_code = None
            chunks = []
            try:
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._monotonic() >= budget_deadline:
                        stream_code = "assetfare_upstream_unavailable"
                        break
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        stream_code = "assetfare_response_invalid"
                        break
                    chunks.append(chunk)
            except Exception:
                stream_code = "assetfare_upstream_unavailable"
            if stream_code is not None:
                raise ValueError(stream_code)

            parse_failed = False
            data = None
            try:
                data = json.loads(b"".join(chunks).decode("utf-8"))
            except Exception:
                parse_failed = True
            if parse_failed:
                raise ValueError("assetfare_response_invalid")
            if not isinstance(data, dict):
                raise ValueError("assetfare_response_invalid")
            return data
        finally:
            if resp is not None:
                with contextlib.suppress(Exception):
                    resp.close()

    def _validate_session(self, payload: Any) -> Any:
        self._reject_signing_claims(payload)
        if not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
            raise ValueError("assetfare_session_invalid")
        if (
            payload.get("server_signing") is not False
            or payload.get("server_submission") is not False
            or payload.get("signed") is not False
            or payload.get("submitted") is not False
        ):
            raise ValueError("assetfare_session_unsafe")
        return payload

    def forward(self, session_token: str, session_id: str) -> Any:
        token = self._session_token(session_token)
        sid = self._session_id(session_id)
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request(
            "GET", "/v2/session/" + sid, None, budget_deadline, extra_headers={self.SESSION_TOKEN_HEADER: token}
        )
        return self._validate_session(data)


class AssetFareObserveSourceTool(Tool):
    name = "assetfare_observe_source"
    description = (
        "Explicit caller-approved POST /v2/session/{session_id}/observe-source for a "
        "caller-owned AssetFare session (fixed origin https://api.assetfare.dev). It "
        "observes the caller's ALREADY-submitted source transaction hashes and advances "
        "the receipt-driven workflow, returning the next state / unsigned action. It "
        "never submits a transaction, never signs, and never auto-chains. Requires the "
        "caller-owned session capability token (sent only in the X-AssetFare-Session-Token "
        "header), the session_id, an idempotency_key, and 1-8 already-submitted source "
        "transaction hashes. The returned 'server_signs_or_submits' is always false. "
        "Inputs: session_token, session_id, idempotency_key, transaction_hashes."
    )
    inputs = {
        "session_token": {
            "type": "string",
            "description": "Caller-owned session capability token (43-128 chars). Sent only in the X-AssetFare-Session-Token header. Not a private key.",
        },
        "session_id": {
            "type": "string",
            "description": "The session UUID returned by assetfare_session_create.",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Caller idempotency key (8-128 chars) for this observe step.",
        },
        "transaction_hashes": {
            "type": "array",
            "description": "1-8 of the caller's ALREADY-submitted source transaction hashes (strings). These are only observed, never submitted.",
        },
    }
    output_type = "object"

    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SESSION_TOKEN_HEADER = "X-AssetFare-Session-Token"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        import time
        from urllib.parse import urlsplit

        super().__init__()
        parts = urlsplit(base_url or "")
        if (
            parts.scheme != "https"
            or parts.hostname != "api.assetfare.dev"
            or parts.username
            or parts.password
            or parts.port is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("assetfare_base_url_rejected")
        self.base_url = "https://api.assetfare.dev"
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

    def _get_requirements(self) -> str:
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def _reject_signing_claims(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_safety_boundary_failed")
            if isinstance(node, dict):
                for key in ("server_signing", "server_submission"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                for child in node.values():
                    stack.append((child, depth + 1))
            elif isinstance(node, list):
                for child in node:
                    stack.append((child, depth + 1))

    def _session_token(self, session_token: Any) -> str:
        import re

        if not isinstance(session_token, str) or not re.match(r"^[A-Za-z0-9_-]{43,128}$", session_token):
            raise ValueError("assetfare_session_token_invalid")
        return session_token

    def _session_id(self, session_id: Any) -> str:
        import re

        if not isinstance(session_id, str) or not re.match(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", session_id
        ):
            raise ValueError("assetfare_session_id_invalid")
        return session_id

    def _idempotency_key(self, idempotency_key: Any) -> str:
        import re

        if not isinstance(idempotency_key, str) or not re.match(r"^[A-Za-z0-9_.:-]{8,128}$", idempotency_key):
            raise ValueError("assetfare_idempotency_key_invalid")
        return idempotency_key

    def _tx_hashes(self, transaction_hashes: Any) -> list:
        import re

        if not isinstance(transaction_hashes, list) or not (1 <= len(transaction_hashes) <= 8):
            raise ValueError("assetfare_transaction_hashes_invalid")
        for h in transaction_hashes:
            if not isinstance(h, str) or not re.match(r"^[0-9A-Za-z:_-]{16,128}$", h):
                raise ValueError("assetfare_transaction_hashes_invalid")
        return list(transaction_hashes)

    def _request(self, method: str, path: str, payload: Any, budget_deadline: float, extra_headers: Any = None) -> Any:
        import contextlib
        import json

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        remaining = budget_deadline - self._monotonic()
        if remaining <= 0:
            raise ValueError("assetfare_upstream_unavailable")
        timeout = min(self.SOCKET_TIMEOUT_S, remaining)
        headers = {"accept": "application/json", "x-assetfare-channel": "smolagents"}
        if extra_headers:
            headers.update(extra_headers)

        resp = None
        send_failed = False
        try:
            resp = self._session.request(
                method,
                self.base_url + path,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                headers=headers,
                stream=True,
            )
        except Exception:
            send_failed = True
        if send_failed:
            raise ValueError("assetfare_upstream_unavailable")

        try:
            if resp.is_redirect or 300 <= resp.status_code < 400:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code == 429:
                raise ValueError("assetfare_rate_limited")
            if resp.status_code >= 500:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code >= 400:
                raise ValueError("assetfare_request_rejected")
            media = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("assetfare_response_invalid")
            declared = resp.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.MAX_BYTES:
                raise ValueError("assetfare_response_invalid")

            stream_code = None
            chunks = []
            try:
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._monotonic() >= budget_deadline:
                        stream_code = "assetfare_upstream_unavailable"
                        break
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        stream_code = "assetfare_response_invalid"
                        break
                    chunks.append(chunk)
            except Exception:
                stream_code = "assetfare_upstream_unavailable"
            if stream_code is not None:
                raise ValueError(stream_code)

            parse_failed = False
            data = None
            try:
                data = json.loads(b"".join(chunks).decode("utf-8"))
            except Exception:
                parse_failed = True
            if parse_failed:
                raise ValueError("assetfare_response_invalid")
            if not isinstance(data, dict):
                raise ValueError("assetfare_response_invalid")
            return data
        finally:
            if resp is not None:
                with contextlib.suppress(Exception):
                    resp.close()

    def _validate_session(self, payload: Any) -> Any:
        self._reject_signing_claims(payload)
        if not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
            raise ValueError("assetfare_session_invalid")
        if (
            payload.get("server_signing") is not False
            or payload.get("server_submission") is not False
            or payload.get("signed") is not False
            or payload.get("submitted") is not False
        ):
            raise ValueError("assetfare_session_unsafe")
        return payload

    def forward(self, session_token: str, session_id: str, idempotency_key: str, transaction_hashes: list) -> Any:
        token = self._session_token(session_token)
        sid = self._session_id(session_id)
        key = self._idempotency_key(idempotency_key)
        hashes = self._tx_hashes(transaction_hashes)
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request(
            "POST",
            "/v2/session/" + sid + "/observe-source",
            {"idempotency_key": key, "transaction_hashes": hashes},
            budget_deadline,
            extra_headers={self.SESSION_TOKEN_HEADER: token},
        )
        return self._validate_session(data)


class AssetFareObserveOutputTool(Tool):
    name = "assetfare_observe_output"
    description = (
        "Explicit caller-approved POST /v2/session/{session_id}/observe-output for a "
        "caller-owned AssetFare session (fixed origin https://api.assetfare.dev). It "
        "observes the caller's ALREADY-produced destination / bridge output and advances "
        "the receipt-driven workflow. It never submits a transaction, never signs, and "
        "never auto-chains. Requires the caller-owned session capability token (sent only "
        "in the X-AssetFare-Session-Token header), the session_id and an idempotency_key; "
        "transaction_hash is optional (the caller's already-produced output hash). The "
        "returned 'server_signs_or_submits' is always false. Inputs: session_token, "
        "session_id, idempotency_key, transaction_hash (optional)."
    )
    inputs = {
        "session_token": {
            "type": "string",
            "description": "Caller-owned session capability token (43-128 chars). Sent only in the X-AssetFare-Session-Token header. Not a private key.",
        },
        "session_id": {
            "type": "string",
            "description": "The session UUID returned by assetfare_session_create.",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Caller idempotency key (8-128 chars) for this observe step.",
        },
        "transaction_hash": {
            "type": "string",
            "description": "Optional: the caller's ALREADY-produced destination/bridge output transaction hash. Only observed, never submitted.",
            "nullable": True,
        },
    }
    output_type = "object"

    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SESSION_TOKEN_HEADER = "X-AssetFare-Session-Token"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        import time
        from urllib.parse import urlsplit

        super().__init__()
        parts = urlsplit(base_url or "")
        if (
            parts.scheme != "https"
            or parts.hostname != "api.assetfare.dev"
            or parts.username
            or parts.password
            or parts.port is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("assetfare_base_url_rejected")
        self.base_url = "https://api.assetfare.dev"
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

    def _get_requirements(self) -> str:
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def _reject_signing_claims(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_safety_boundary_failed")
            if isinstance(node, dict):
                for key in ("server_signing", "server_submission"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                for child in node.values():
                    stack.append((child, depth + 1))
            elif isinstance(node, list):
                for child in node:
                    stack.append((child, depth + 1))

    def _session_token(self, session_token: Any) -> str:
        import re

        if not isinstance(session_token, str) or not re.match(r"^[A-Za-z0-9_-]{43,128}$", session_token):
            raise ValueError("assetfare_session_token_invalid")
        return session_token

    def _session_id(self, session_id: Any) -> str:
        import re

        if not isinstance(session_id, str) or not re.match(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", session_id
        ):
            raise ValueError("assetfare_session_id_invalid")
        return session_id

    def _idempotency_key(self, idempotency_key: Any) -> str:
        import re

        if not isinstance(idempotency_key, str) or not re.match(r"^[A-Za-z0-9_.:-]{8,128}$", idempotency_key):
            raise ValueError("assetfare_idempotency_key_invalid")
        return idempotency_key

    def _request(self, method: str, path: str, payload: Any, budget_deadline: float, extra_headers: Any = None) -> Any:
        import contextlib
        import json

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        remaining = budget_deadline - self._monotonic()
        if remaining <= 0:
            raise ValueError("assetfare_upstream_unavailable")
        timeout = min(self.SOCKET_TIMEOUT_S, remaining)
        headers = {"accept": "application/json", "x-assetfare-channel": "smolagents"}
        if extra_headers:
            headers.update(extra_headers)

        resp = None
        send_failed = False
        try:
            resp = self._session.request(
                method,
                self.base_url + path,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                headers=headers,
                stream=True,
            )
        except Exception:
            send_failed = True
        if send_failed:
            raise ValueError("assetfare_upstream_unavailable")

        try:
            if resp.is_redirect or 300 <= resp.status_code < 400:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code == 429:
                raise ValueError("assetfare_rate_limited")
            if resp.status_code >= 500:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code >= 400:
                raise ValueError("assetfare_request_rejected")
            media = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("assetfare_response_invalid")
            declared = resp.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.MAX_BYTES:
                raise ValueError("assetfare_response_invalid")

            stream_code = None
            chunks = []
            try:
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._monotonic() >= budget_deadline:
                        stream_code = "assetfare_upstream_unavailable"
                        break
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        stream_code = "assetfare_response_invalid"
                        break
                    chunks.append(chunk)
            except Exception:
                stream_code = "assetfare_upstream_unavailable"
            if stream_code is not None:
                raise ValueError(stream_code)

            parse_failed = False
            data = None
            try:
                data = json.loads(b"".join(chunks).decode("utf-8"))
            except Exception:
                parse_failed = True
            if parse_failed:
                raise ValueError("assetfare_response_invalid")
            if not isinstance(data, dict):
                raise ValueError("assetfare_response_invalid")
            return data
        finally:
            if resp is not None:
                with contextlib.suppress(Exception):
                    resp.close()

    def _validate_session(self, payload: Any) -> Any:
        self._reject_signing_claims(payload)
        if not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
            raise ValueError("assetfare_session_invalid")
        if (
            payload.get("server_signing") is not False
            or payload.get("server_submission") is not False
            or payload.get("signed") is not False
            or payload.get("submitted") is not False
        ):
            raise ValueError("assetfare_session_unsafe")
        return payload

    def forward(self, session_token: str, session_id: str, idempotency_key: str, transaction_hash: Optional[str] = None) -> Any:
        import re

        token = self._session_token(session_token)
        sid = self._session_id(session_id)
        key = self._idempotency_key(idempotency_key)
        body = {"idempotency_key": key}
        if transaction_hash is not None:
            if not isinstance(transaction_hash, str) or not re.match(r"^[0-9A-Za-z:_-]{16,128}$", transaction_hash):
                raise ValueError("assetfare_transaction_hash_invalid")
            body["transaction_hash"] = transaction_hash
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request(
            "POST",
            "/v2/session/" + sid + "/observe-output",
            body,
            budget_deadline,
            extra_headers={self.SESSION_TOKEN_HEADER: token},
        )
        return self._validate_session(data)


class AssetFareRefreshActionTool(Tool):
    name = "assetfare_refresh_action"
    description = (
        "Explicit caller-approved POST /v2/session/{session_id}/refresh-action for a "
        "caller-owned AssetFare session (fixed origin https://api.assetfare.dev). It "
        "replaces an expired, UNSUBMITTED session action with a fresh quote-bound "
        "unsigned action for the caller to verify, sign and submit. It never signs, "
        "never submits, and never auto-chains. Requires the caller-owned session "
        "capability token (sent only in the X-AssetFare-Session-Token header), the "
        "session_id and an idempotency_key. The returned 'server_signs_or_submits' is "
        "always false. Inputs: session_token, session_id, idempotency_key."
    )
    inputs = {
        "session_token": {
            "type": "string",
            "description": "Caller-owned session capability token (43-128 chars). Sent only in the X-AssetFare-Session-Token header. Not a private key.",
        },
        "session_id": {
            "type": "string",
            "description": "The session UUID returned by assetfare_session_create.",
        },
        "idempotency_key": {
            "type": "string",
            "description": "Caller idempotency key (8-128 chars) for this refresh step.",
        },
    }
    output_type = "object"

    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SESSION_TOKEN_HEADER = "X-AssetFare-Session-Token"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        import time
        from urllib.parse import urlsplit

        super().__init__()
        parts = urlsplit(base_url or "")
        if (
            parts.scheme != "https"
            or parts.hostname != "api.assetfare.dev"
            or parts.username
            or parts.password
            or parts.port is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("assetfare_base_url_rejected")
        self.base_url = "https://api.assetfare.dev"
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

    def _get_requirements(self) -> str:
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def _reject_signing_claims(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_safety_boundary_failed")
            if isinstance(node, dict):
                for key in ("server_signing", "server_submission"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                for child in node.values():
                    stack.append((child, depth + 1))
            elif isinstance(node, list):
                for child in node:
                    stack.append((child, depth + 1))

    def _session_token(self, session_token: Any) -> str:
        import re

        if not isinstance(session_token, str) or not re.match(r"^[A-Za-z0-9_-]{43,128}$", session_token):
            raise ValueError("assetfare_session_token_invalid")
        return session_token

    def _session_id(self, session_id: Any) -> str:
        import re

        if not isinstance(session_id, str) or not re.match(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", session_id
        ):
            raise ValueError("assetfare_session_id_invalid")
        return session_id

    def _idempotency_key(self, idempotency_key: Any) -> str:
        import re

        if not isinstance(idempotency_key, str) or not re.match(r"^[A-Za-z0-9_.:-]{8,128}$", idempotency_key):
            raise ValueError("assetfare_idempotency_key_invalid")
        return idempotency_key

    def _request(self, method: str, path: str, payload: Any, budget_deadline: float, extra_headers: Any = None) -> Any:
        import contextlib
        import json

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        remaining = budget_deadline - self._monotonic()
        if remaining <= 0:
            raise ValueError("assetfare_upstream_unavailable")
        timeout = min(self.SOCKET_TIMEOUT_S, remaining)
        headers = {"accept": "application/json", "x-assetfare-channel": "smolagents"}
        if extra_headers:
            headers.update(extra_headers)

        resp = None
        send_failed = False
        try:
            resp = self._session.request(
                method,
                self.base_url + path,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                headers=headers,
                stream=True,
            )
        except Exception:
            send_failed = True
        if send_failed:
            raise ValueError("assetfare_upstream_unavailable")

        try:
            if resp.is_redirect or 300 <= resp.status_code < 400:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code == 429:
                raise ValueError("assetfare_rate_limited")
            if resp.status_code >= 500:
                raise ValueError("assetfare_upstream_unavailable")
            if resp.status_code >= 400:
                raise ValueError("assetfare_request_rejected")
            media = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("assetfare_response_invalid")
            declared = resp.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.MAX_BYTES:
                raise ValueError("assetfare_response_invalid")

            stream_code = None
            chunks = []
            try:
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._monotonic() >= budget_deadline:
                        stream_code = "assetfare_upstream_unavailable"
                        break
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        stream_code = "assetfare_response_invalid"
                        break
                    chunks.append(chunk)
            except Exception:
                stream_code = "assetfare_upstream_unavailable"
            if stream_code is not None:
                raise ValueError(stream_code)

            parse_failed = False
            data = None
            try:
                data = json.loads(b"".join(chunks).decode("utf-8"))
            except Exception:
                parse_failed = True
            if parse_failed:
                raise ValueError("assetfare_response_invalid")
            if not isinstance(data, dict):
                raise ValueError("assetfare_response_invalid")
            return data
        finally:
            if resp is not None:
                with contextlib.suppress(Exception):
                    resp.close()

    def _validate_session(self, payload: Any) -> Any:
        self._reject_signing_claims(payload)
        if not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
            raise ValueError("assetfare_session_invalid")
        if (
            payload.get("server_signing") is not False
            or payload.get("server_submission") is not False
            or payload.get("signed") is not False
            or payload.get("submitted") is not False
        ):
            raise ValueError("assetfare_session_unsafe")
        return payload

    def forward(self, session_token: str, session_id: str, idempotency_key: str) -> Any:
        token = self._session_token(session_token)
        sid = self._session_id(session_id)
        key = self._idempotency_key(idempotency_key)
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request(
            "POST",
            "/v2/session/" + sid + "/refresh-action",
            {"idempotency_key": key},
            budget_deadline,
            extra_headers={self.SESSION_TOKEN_HEADER: token},
        )
        return self._validate_session(data)
