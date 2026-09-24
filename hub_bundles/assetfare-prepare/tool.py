from smolagents.tools import Tool
from typing import Any, Optional
import contextlib
import json
import math
import re
import requests
import time
import urllib
import uuid

class AssetFarePrepareTool(Tool):
    name = "assetfare_prepare"
    description = "Explicit caller-approved, non-custodial one-shot POST /v2/prepare for an AssetFare route whose fresh quote reports current availability (fixed origin https://api.assetfare.dev). Before calling it, compare fresh AssetFare and competitor quotes at the actual intended amount; USD 1 is smoke-only, USD 50 is merely the lowest observed native-USDC winning bucket, and USD 1,000 is a representative example, not an approval or guarantee. It fresh re-quotes and returns a bounded FIRST unsigned action bundle for the caller to verify, sign and submit with their OWN wallet. It never signs, never submits, never receives a private key or seed, and is NEVER auto-called from a quote: you must call it deliberately with caller_approved set to the literal true, an explicit approval_v3 copied from the selected fresh quote bounds, and the route's own PUBLIC wallet addresses. caller_approved alone is not proof of human approval. Select one_shot only when continuation_v3 explicitly allows it; multi-step routes are session-only. It fails closed before any network call if caller_approved is not literally true or if any private key / seed / signed transaction appears anywhere in the input. Inputs: caller_approved (must be true), from_chain, from_token, to_chain, to_token, amount_usd (finite number, minimum 1; no business maximum), wallets (a map of the route's chains to PUBLIC addresses only), and event_signer_public (Solana-CCTP only: generate a fresh ephemeral keypair locally, send only its public key, retain its private key client-side to co-sign the returned event-account transaction). The returned 'server_signs_or_submits' is always false. This tool prepares only an UNSIGNED action; it does NOT execute, bridge, swap, sign or move funds."
    inputs = {'caller_approved': {'type': 'boolean', 'description': 'Must be the literal boolean true. It is the explicit caller approval gate; anything else is rejected before any network call.'}, 'from_chain': {'type': 'string', 'description': 'Source chain: one of solana, base, arbitrum, robinhood, polygon, optimism.'}, 'from_token': {'type': 'string', 'description': 'Source token symbol on the source chain, e.g. SOL, ETH, USDC, USDG.'}, 'to_chain': {'type': 'string', 'description': 'Destination chain: one of solana, base, arbitrum, robinhood.'}, 'to_token': {'type': 'string', 'description': 'Destination token symbol on the destination chain, e.g. ETH, USDC, USDG.'}, 'amount_usd': {'type': 'number', 'description': 'Actual intended finite USD amount, minimum 1; no business maximum. Do not substitute the USD 1,000 representative example for caller intent or fresh comparison.'}, 'wallets': {'type': 'object', 'description': "Map of the route's chains (at least the source and destination) to the caller's PUBLIC wallet addresses only. Never a private key or seed."}, 'approval_v3': {'type': 'object', 'description': 'Exact nine-field assetfare-quote-bound-approval-v3 built locally after explicit unranked selection. selected_mode must be one_shot. Never auto-generate this object.'}, 'event_signer_public': {'type': 'string', 'description': 'Solana-CCTP only: generate a fresh ephemeral Solana keypair locally, send only this public key, and retain its private key client-side to co-sign the returned unsigned event-account transaction. Omit when not applicable.', 'nullable': True}}
    output_type = "object"
    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576
    MIN_USD = 1.0
    CHAINS = {'arbitrum', 'base', 'optimism', 'polygon', 'robinhood', 'solana'}
    SOURCE_ONLY_CHAINS = {'optimism', 'polygon'}
    ENDPOINTS = {'arbitrum:ETH', 'arbitrum:USDC', 'base:ETH', 'base:USDC', 'optimism:USDC', 'polygon:USDC', 'robinhood:ETH', 'robinhood:USDG', 'solana:SOL', 'solana:USDC', 'solana:USDG'}
    FORBIDDEN_SECRET_KEYS = {'keypair', 'mnemonic', 'passphrase', 'password', 'private_key', 'privatekey', 'privkey', 'raw_transaction', 'secret', 'secret_key', 'secretkey', 'seed', 'seed_phrase', 'signature', 'signed', 'signed_transaction', 'signed_tx'}
    APPROVAL_V3_KEYS = {'direct_route_summary_sha256', 'idempotency_key', 'maximum_input_base', 'minimum_output_base', 'quote_fingerprint', 'quote_id', 'selected_mode', 'selection_status', 'version'}

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
        # Deep-scan a caller intent and reject any private-key / seed / signed material.
        # Bounded (node count and depth) so a hostile/huge input cannot hang the scan.
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
        # Machine approval gate: literal True only (reject false/missing/string/number).
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
        # Reject any private key / seed / signed material anywhere in the intent.
        self._reject_secret_material(
            {
                "wallets": wallets,
                "event_signer_public": event_signer_public,
                "from_chain": from_chain,
                "to_chain": to_chain,
            }
        )
        # Exact public wallet map: 1-6 entries, keys are known chains, values are public
        # addresses only. Never a private key or seed.
        if not isinstance(wallets, dict) or not (1 <= len(wallets) <= 6):
            raise ValueError("assetfare_wallets_invalid")
        for chain, address in wallets.items():
            if chain not in self.CHAINS:
                raise ValueError("assetfare_wallets_invalid")
            if not self._is_public_address(address):
                raise ValueError("assetfare_wallet_not_public_address")
        # The route's source and destination chains must each have a wallet.
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
        # event_signer_public is conditional (Solana-CCTP routes). If supplied it must be
        # a public address (never a private key); pass it through when present.
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

    def _validate_bundle(self, payload: Any) -> Any:
        # Validate an upstream bounded FIRST unsigned action bundle. Fail-closed on any
        # server signing/submission claim. It must carry an unsigned_action and
        # explicitly assert it is neither signed nor submitted.
        self._reject_signing_claims(payload)
        if (
            payload.get("server_signing") is not False
            or payload.get("server_submission") is not False
            or payload.get("signed") is not False
            or payload.get("submitted") is not False
        ):
            raise ValueError("assetfare_bundle_unsafe")
        if not isinstance(payload.get("unsigned_action"), dict):
            raise ValueError("assetfare_bundle_missing_action")
        return payload

    def _approval_v3(self, value: Any) -> Any:
        import re
        import uuid

        self._reject_secret_material(value)
        if not isinstance(value, dict) or set(value) != self.APPROVAL_V3_KEYS:
            raise ValueError("assetfare_approval_v3_shape_invalid")
        try:
            uuid.UUID(str(value.get("quote_id")))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("assetfare_approval_v3_quote_id_invalid") from None
        if (
            value.get("version") != "assetfare-quote-bound-approval-v3"
            or value.get("selection_status") != "selected"
            or value.get("selected_mode") != "one_shot"
            or not isinstance(value.get("quote_fingerprint"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["quote_fingerprint"]) is None
            or not isinstance(value.get("direct_route_summary_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["direct_route_summary_sha256"]) is None
            or not isinstance(value.get("maximum_input_base"), str)
            or re.fullmatch(r"[1-9][0-9]*", value["maximum_input_base"]) is None
            or not isinstance(value.get("minimum_output_base"), str)
            or re.fullmatch(r"[1-9][0-9]*", value["minimum_output_base"]) is None
            or not isinstance(value.get("idempotency_key"), str)
            or re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value["idempotency_key"]) is None
        ):
            raise ValueError("assetfare_approval_v3_invalid")
        return dict(value)

    def forward(
        self,
        caller_approved: bool,
        from_chain: str,
        from_token: str,
        to_chain: str,
        to_token: str,
        amount_usd: float,
        wallets: dict,
        approval_v3: dict,
        event_signer_public: Optional[str] = None,
    ) -> Any:
        body = self._action_intent(
            caller_approved, from_chain, from_token, to_chain, to_token, amount_usd, wallets, event_signer_public
        )
        body["approval_v3"] = self._approval_v3(approval_v3)
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request("POST", "/v2/prepare", body, budget_deadline)
        bundle = self._validate_bundle(data)
        return {
            "bundle": bundle,
            "fresh_requoted": True,
            "caller_approval_honored": True,
            "action_prepared": True,
            "transaction_signed": False,
            "transaction_submitted": False,
            "caller_must_verify_sign_and_submit": True,
            "server_signs_or_submits": False,
        }
