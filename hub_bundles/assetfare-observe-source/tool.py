from smolagents.tools import Tool
from typing import Any, Optional
import contextlib
import json
import re
import requests
import time
import urllib

class AssetFareObserveSourceTool(Tool):
    name = "assetfare_observe_source"
    description = "Explicit caller-approved POST /v2/session/{session_id}/observe-source for a caller-owned AssetFare session (fixed origin https://api.assetfare.dev). It observes the caller's ALREADY-submitted source transaction hashes and advances the receipt-driven workflow, returning the next state / unsigned action. It never submits a transaction, never signs, and never auto-chains. Requires the caller-owned session capability token (sent only in the X-AssetFare-Session-Token header), the session_id, an idempotency_key, and 1-8 already-submitted source transaction hashes. The returned 'server_signs_or_submits' is always false. Inputs: session_token, session_id, idempotency_key, transaction_hashes."
    inputs = {'session_token': {'type': 'string', 'description': 'Caller-owned session capability token (43-128 chars). Sent only in the X-AssetFare-Session-Token header. Not a private key.'}, 'session_id': {'type': 'string', 'description': 'The session UUID returned by assetfare_session_create.'}, 'idempotency_key': {'type': 'string', 'description': 'Caller idempotency key (8-128 chars) for this observe step.'}, 'transaction_hashes': {'type': 'array', 'description': "1-8 of the caller's ALREADY-submitted source transaction hashes (strings). These are only observed, never submitted."}}
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
