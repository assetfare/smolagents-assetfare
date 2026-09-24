from smolagents.tools import Tool
from typing import Any, Optional
import contextlib
import copy
import datetime
import decimal
import hashlib
import json
import math
import re
import requests
import struct
import time
import urllib
import uuid

class AssetFareQuoteTool(Tool):
    name = "assetfare_quote"
    description = "Read-only quote client for one cross-chain corridor via the AssetFare v2 API (fixed origin https://api.assetfare.dev). This tool's entire scope is to fetch and validate a single conversion quote and return it; it is not the AssetFare service and does not itself prepare, sign or submit. It covers 6 source chains (solana, base, arbitrum, robinhood, polygon, optimism), 11 (chain, token) source endpoints and 76 directed quote routes, for any finite USD amount of at least 1, with no business maximum. USD 1 is only a reachability/response-shape smoke test, never an economic comparison. USD 50 is the lowest observed native-USDC winning bucket/evaluation start, not a guarantee, and USD 1,000 is the primary representative economic example. Always fetch fresh AssetFare and competitor quotes at the actual intended amount; never assume AssetFare is always cheapest. Polygon and Optimism are directional native-USDC source-only origins to Base or Arbitrum USDC. Implemented paths are usable only while the live quote reports them available. It never authenticates a wallet, opens a session, prepares an unsigned action, signs or submits. Legacy action handoffs are validated but suppressed from the quote-only result; the returned 'server_signs_or_submits' is always false. It returns expected/minimum receive amounts (native and USD), the exact AssetFare service fee (1bp, not total cost), top-level expected and maximum token-path cost including provider components, live availability, eligible fee_collection_steps, and a validated ordered direct_route_summary showing every named protocol, normalized endpoint, base-unit amount, and exact 1bp fee step. route_aggregator_used=false means AssetFare did not call a market-wide aggregator API. An external_intent route uses Across, which may internally source or aggregate destination liquidity; this is provider-internal behavior, not an AssetFare aggregator call. It also returns ETA, the non-atomic risk flag, a quote id, an as_of timestamp and a ttl. Every response is validated and the call fails closed if anything claims the server will sign or submit, if the quote is stale or future-dated, if total cost is inconsistent, if the service fee is not exactly 1bp, if the upstream handoff safety assertion is missing or malformed, or if the route does not match the requested corridor. Inputs: from_chain, from_token, to_chain, to_token (a supported chain/token pair, source != destination) and amount_usd (finite number, minimum 1; no business maximum). This tool does NOT execute, bridge, swap, sign or move funds. It strictly validates the full continuation_v3 and returns only a sanitized continuation_descriptor with non-executable discovery metadata. The tool never creates approval_v3 or selects a mode; the caller must explicitly choose exactly one allowed mode. Multi-step routes are session-only. caller_approved alone is not proof of human approval and legacy handoff is advisory."
    inputs = {'from_chain': {'type': 'string', 'description': 'Source chain: one of solana, base, arbitrum, robinhood, polygon, optimism.'}, 'from_token': {'type': 'string', 'description': 'Source token symbol on the source chain, e.g. SOL, ETH, USDC, USDG.'}, 'to_chain': {'type': 'string', 'description': 'Destination chain: one of solana, base, arbitrum, robinhood.'}, 'to_token': {'type': 'string', 'description': 'Destination token symbol on the destination chain, e.g. ETH, USDC, USDG.'}, 'amount_usd': {'type': 'number', 'description': 'Actual intended finite USD amount; technical minimum 1 is smoke-only, no business maximum. USD 1,000 is a representative example, not an advantage guarantee.'}}
    output_type = "object"
    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576
    MAX_TTL_SECONDS = 60
    MAX_FUTURE_SKEW_S = 300
    MIN_USD = 1.0
    EVALUATION_GUIDANCE = {'schema_version': 1, 'route_minimum_usd': 1, 'reachability_smoke_usd': 1, 'reachability_smoke_scope': 'connectivity_only_not_economic_evaluation', 'native_usdc_economic_evaluation_start_usd': 50, 'representative_economic_evaluation_usd': 1000, 'sol_input_representative_evaluation_usd': 1000, 'sol_input_caveat': 'SOL-input routes add a source swap, so compare their full fee-inclusive route economics separately.', 'evidence_as_of': '2026-09-23', 'evidence_scope': 'Dated Solana native USDC to Base native USDC measurements at USD 50, 250, and 1000.', 'not_a_minimum': True, 'not_guaranteed_best': True, 'always_compare_fresh_at_intended_amount': True}
    PREPARE_URL = "https://api.assetfare.dev/v2/prepare"
    SESSION_URL = "https://api.assetfare.dev/v2/session"
    FEE_COLLECTION_CONST = "only_on_eligible_successful_executor_step"
    CHAINS = {'arbitrum', 'base', 'optimism', 'polygon', 'robinhood', 'solana'}
    SOURCE_ONLY_CHAINS = {'optimism', 'polygon'}
    ENDPOINTS = {'arbitrum:ETH', 'arbitrum:USDC', 'base:ETH', 'base:USDC', 'optimism:USDC', 'polygon:USDC', 'robinhood:ETH', 'robinhood:USDG', 'solana:SOL', 'solana:USDC', 'solana:USDG'}
    HANDOFF_ALLOWED_KEYS = {'assetfare_server_signing', 'assetfare_server_submission', 'automatic_prepare_call_forbidden', 'available', 'blocker', 'caller_must_verify_sign_and_submit', 'kind', 'method', 'note', 'options', 'request_fields', 'requires_explicit_caller_approval', 'requires_fresh_requote', 'requires_public_wallet_addresses', 'url'}
    DIRECT_SUMMARY_MODES = {'cctp_direct_composition', 'optimism_source_cctp', 'polygon_source_cctp', 'robinhood_across_ingress_composition', 'robinhood_paxos_egress_composition', 'same_chain_direct', 'same_chain_direct_composition'}
    DIRECT_SUMMARY_PROVIDERS = {'across_intent_bridge', 'circle_cctp', 'orca_whirlpool', 'paxos_usdg_layerzero_oft', 'raydium_clmm', 'uniswap_v3'}
    SWAP_PROVIDERS = {'orca_whirlpool', 'raydium_clmm', 'uniswap_v3'}
    BRIDGE_PROVIDERS = {'across_intent_bridge', 'circle_cctp', 'paxos_usdg_layerzero_oft'}
    DIRECT_SUMMARY_KEYS = {'assetfare_fee_bps', 'classification', 'external_intent_protocol_used', 'fee_collection_step_index', 'from', 'mode', 'provider_internal_dex_aggregation_possible', 'route', 'route_aggregator_used', 'server_signing', 'server_submission', 'step_count', 'steps', 'to', 'version'}
    DIRECT_SUMMARY_STEP_KEYS = {'action', 'aggregator_api_used', 'assetfare_fee_bps', 'direct_protocol', 'expected_input_base', 'expected_output_base', 'external_intent_protocol', 'from', 'index', 'minimum_input_base', 'minimum_output_base', 'provider', 'to'}
    CONTINUATION_VERSION = "assetfare-quote-bound-continuation-v3"
    QUOTE_PAYLOAD_SHA256_SPEC = "sha256(AssetFare typed-canonical-v1 bytes of the quote without continuation_v3 after exact base-unit substitution: n=null; t/f=boolean; d=<IEEE-754 binary64 big-endian 16 lowercase hex> for each finite JSON number; s=<UTF-8 byte length>:<Unicode scalar text with lone surrogates forbidden>; a=<count>:[items]; o=<count>:{UTF-8-byte-sorted string-key/value pairs}; every non-substituted integral JSON number must be within +/-9007199254740991; substituted paths are intent.estimated_input_base, route.input_base, route.expected_output_base, route.minimum_output_base, and every route.steps[i].expected_input_base/floor_input_base/expected_output_base/minimum_output_base from direct_route_summary exact decimal strings)"
    CONTINUATION_KEYS = {'allowed_modes', 'approval_v3_required_fields', 'automatic_selection_forbidden', 'caller_approved_boolean_is_not_human_proof', 'direct_route_summary_sha256', 'enforcement', 'event_signer_public_required', 'expires_at', 'idempotency', 'input_base_bounds', 'intent', 'issued_at', 'legacy_handoff_enforcement', 'minimum_output_base', 'quote_fingerprint', 'quote_fingerprint_claim', 'quote_fingerprint_spec', 'quote_id', 'quote_payload_sha256', 'quote_payload_sha256_spec', 'recommended_mode', 'required_wallet_chains', 'selection_status', 'server_signing', 'server_submission', 'session_header', 'step_count', 'ttl_seconds', 'version'}
    FINGERPRINT_CLAIM_KEYS = {'allowed_modes', 'direct_route_summary_sha256', 'event_signer_public_required', 'expires_at', 'input_base_bounds', 'intent', 'issued_at', 'minimum_output_base', 'quote_id', 'quote_payload_sha256', 'quote_payload_sha256_spec', 'required_wallet_chains', 'server_signing', 'server_submission', 'step_count', 'ttl_seconds', 'version'}

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        utcnow: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        # smolagents' Tool.from_hub/from_code forward Hub download kwargs
        # (revision, cache_dir, subfolder, ...) straight to the tool constructor,
        # so accept and ignore them; otherwise load_tool(..., revision=...) fails.
        import time
        from datetime import datetime, timezone
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
        # Force trust_env=False on an injected session too, so ambient proxy /
        # credential environment variables are never honoured for this client.
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))

    def _finite(self, value: Any) -> bool:
        import math

        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )

    def _is_int(self, value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def _obj(self, data: Any, key: str) -> Any:
        node = data.get(key)
        if not isinstance(node, dict):
            raise ValueError("assetfare_response_invalid")
        return node

    def _no_sign(self, node: Any) -> None:
        if node.get("server_signing") is not False or node.get("server_submission") is not False:
            raise ValueError("assetfare_safety_boundary_failed")

    def _no_sign_tree(self, value: Any) -> None:
        stack = [(value, 0)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if seen > 512 or depth > 12:
                raise ValueError("assetfare_response_invalid")
            if isinstance(node, dict):
                for key in ("server_signing", "server_submission"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                for key in ("signed", "submitted"):
                    if key in node and node[key] is not False:
                        raise ValueError("assetfare_safety_boundary_failed")
                secret_keys = {"private" + "_key", "mne" + "monic", "seed" + "_phrase"}
                if secret_keys & set(node):
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

    def _request(self, method: str, path: str, payload: Any, budget_deadline: float) -> Any:
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

        resp = None
        send_failed = False
        try:
            resp = self._session.request(
                method,
                self.base_url + path,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
                headers={"accept": "application/json", "x-assetfare-channel": "smolagents"},
                stream=True,
            )
        except Exception:
            # Any send-phase failure, not just requests.RequestException: a hostile or
            # broken injected session could raise RuntimeError/ValueError (possibly
            # carrying upstream text). Record a flag and raise the fixed error outside
            # this handler so nothing raw escapes and __context__ stays None.
            send_failed = True
        # Raise OUTSIDE the except handler: a `raise ... from None` only suppresses
        # the traceback, leaving the upstream exception object on __context__. By
        # recording a flag and raising after the handler exits (exc_info cleared),
        # the final ValueError has __context__ is None and __cause__ is None.
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

            # Collect the body. Internal budget/size failures set `stream_code` and
            # break -- they are never raised inside the loop, so a `except ... : raise`
            # can no longer confuse an internal ValueError with an external one. ANY
            # exception from iter_content (including a hostile ValueError carrying
            # upstream text) is swallowed here and replaced. The fixed error is raised
            # only AFTER this handler exits, so its __context__ is None.
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

            # Decode + JSON parse in isolation. UnicodeDecodeError and JSONDecodeError
            # are ValueError subclasses; capture as a flag and raise the fixed error
            # outside the handler so __context__ stays None.
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

    def _get_requirements(self) -> str:
        # Pinned, reproducible requirements emitted into the Hub Space's
        # requirements.txt by save()/push_to_hub -- compatibility-verified against
        # smolagents 1.26.0 (which itself requires requests>=2.32.3).
        return "smolagents==1.26.0\nrequests>=2.32.3,<3"

    def _validate_offer_fee(self, offer: Any, step_count: int) -> None:
        # Fee is EXACTLY 1bp, collected once on an eligible successful atomic
        # action. fee_collection_steps holds EXACTLY one valid in-range index.
        # Rejects 0bp, fee>1 / negative / 8bp,
        # 2-step or 0-step mismatches, out-of-range or duplicate indices. Also
        # validates fee_modeled_bps, fee_collectible_now, and the fee_collection literal.
        if offer.get("fee_collection") != self.FEE_COLLECTION_CONST:
            raise ValueError("assetfare_response_invalid")
        fee = offer.get("assetfare_fee_bps")
        if not self._is_int(fee) or fee != 1:
            raise ValueError("assetfare_response_invalid")
        modeled = offer.get("fee_modeled_bps")
        if not self._is_int(modeled) or modeled != 1:
            raise ValueError("assetfare_response_invalid")
        if not isinstance(offer.get("fee_collectible_now"), bool):
            raise ValueError("assetfare_response_invalid")
        if modeled != fee or offer.get("fee_collectible_now") is not (fee == 1):
            raise ValueError("assetfare_fee_collectibility_mismatch")
        steps = offer.get("fee_collection_steps")
        if not isinstance(steps, list):
            raise ValueError("assetfare_response_invalid")
        for s in steps:
            if not self._is_int(s):
                raise ValueError("assetfare_response_invalid")
        for s in steps:
            if s < 0 or s >= step_count:
                raise ValueError("assetfare_fee_step_out_of_range")
        if len(set(steps)) != len(steps):
            raise ValueError("assetfare_fee_step_duplicate")
        if len(steps) != 1:
            raise ValueError("assetfare_fee_step_count_mismatch")

    def _summary_amount(self, value: Any) -> str:
        if not isinstance(value, str) or not value.isdigit() or value.startswith("0"):
            raise ValueError("assetfare_direct_route_summary_invalid")
        return value

    def _add_expected_swap(self, path: Any, chain: str, source: str, destination: str) -> None:
        provider = (
            "raydium_clmm"
            if chain == "solana" and {source, destination} == {"SOL", "USDC"}
            else "orca_whirlpool"
            if chain == "solana"
            else "uniswap_v3"
        )
        path.append((provider, chain + ":" + source, chain + ":" + destination))

    def _add_expected_bridge(
        self, path: Any, provider: str, source: str, destination: str, source_asset: str, destination_asset: str
    ) -> None:
        path.append((provider, source + ":" + source_asset, destination + ":" + destination_asset))

    def _expected_direct_route(self, expected_from: str, expected_to: str) -> Any:
        from_chain, from_token = expected_from.split(":", 1)
        to_chain, to_token = expected_to.split(":", 1)
        path = []
        if from_chain in self.SOURCE_ONLY_CHAINS:
            self._add_expected_bridge(path, "circle_cctp", from_chain, to_chain, "USDC", "USDC")
            return from_chain + "_source_cctp", False, path
        if from_chain == to_chain:
            composed = from_chain == "solana" and {from_token, to_token} == {"SOL", "USDG"}
            if composed:
                self._add_expected_swap(path, "solana", from_token, "USDC")
                self._add_expected_swap(path, "solana", "USDC", to_token)
            else:
                self._add_expected_swap(path, from_chain, from_token, to_token)
            return ("same_chain_direct_composition" if composed else "same_chain_direct"), False, path
        if from_chain == "robinhood":
            if from_token == "ETH":
                self._add_expected_swap(path, "robinhood", "ETH", "USDG")
            self._add_expected_bridge(path, "paxos_usdg_layerzero_oft", "robinhood", "solana", "USDG", "USDG")
            if to_chain == "solana":
                if to_token == "USDC":
                    self._add_expected_swap(path, "solana", "USDG", "USDC")
                elif to_token == "SOL":
                    self._add_expected_swap(path, "solana", "USDG", "USDC")
                    self._add_expected_swap(path, "solana", "USDC", "SOL")
            else:
                self._add_expected_swap(path, "solana", "USDG", "USDC")
                self._add_expected_bridge(path, "circle_cctp", "solana", to_chain, "USDC", "USDC")
                if to_token == "ETH":
                    self._add_expected_swap(path, to_chain, "USDC", "ETH")
            return "robinhood_paxos_egress_composition", False, path
        if to_chain == "robinhood":
            if from_chain == "solana":
                if from_token == "SOL":
                    self._add_expected_swap(path, "solana", "SOL", "USDC")
                elif from_token == "USDG":
                    self._add_expected_swap(path, "solana", "USDG", "USDC")
                self._add_expected_bridge(path, "circle_cctp", "solana", "base", "USDC", "USDC")
                across_source = "base"
            else:
                if from_token == "ETH":
                    self._add_expected_swap(path, from_chain, "ETH", "USDC")
                across_source = from_chain
            self._add_expected_bridge(path, "across_intent_bridge", across_source, "robinhood", "USDC", "USDG")
            if to_token == "ETH":
                self._add_expected_swap(path, "robinhood", "USDG", "ETH")
            return "robinhood_across_ingress_composition", True, path
        if from_token != "USDC":
            self._add_expected_swap(path, from_chain, from_token, "USDC")
        self._add_expected_bridge(path, "circle_cctp", from_chain, to_chain, "USDC", "USDC")
        if to_token != "USDC":
            self._add_expected_swap(path, to_chain, "USDC", to_token)
        return "cctp_direct_composition", False, path

    def _raw_step_shape(self, step: Any) -> Any:
        provider = step.get("provider")
        if provider in self.SWAP_PROVIDERS and step.get("kind") == "direct_swap":
            chain = str(step.get("chain"))
            return "swap", chain + ":" + str(step.get("from")), chain + ":" + str(step.get("to"))
        if provider in self.BRIDGE_PROVIDERS and step.get("kind") == "direct_bridge":
            source_asset = step.get("from_asset") if provider == "across_intent_bridge" else step.get("asset")
            destination_asset = step.get("to_asset") if provider == "across_intent_bridge" else step.get("asset")
            source = str(step.get("from")) + ":" + str(source_asset)
            destination = str(step.get("to")) + ":" + str(destination_asset)
            return "bridge", source, destination
        raise ValueError("assetfare_direct_route_summary_invalid")

    def _validate_direct_route_summary(
        self,
        value: Any,
        expected_from: str,
        expected_to: str,
        intent: Any,
        offer: Any,
        route: Any,
        risk: Any,
    ) -> Any:
        if not isinstance(value, dict) or set(value) != self.DIRECT_SUMMARY_KEYS:
            raise ValueError("assetfare_direct_route_summary_invalid")
        expected_route = expected_from + "->" + expected_to
        expected_mode, expected_external, expected_path = self._expected_direct_route(expected_from, expected_to)
        if (
            value.get("version") != "assetfare-direct-route-summary-v1"
            or value.get("route") != expected_route
            or value.get("from") != expected_from
            or value.get("to") != expected_to
            or value.get("mode") not in self.DIRECT_SUMMARY_MODES
            or value.get("mode") != expected_mode
            or value.get("route_aggregator_used") is not False
            or value.get("assetfare_fee_bps") != 1
            or value.get("server_signing") is not False
            or value.get("server_submission") is not False
        ):
            raise ValueError("assetfare_direct_route_summary_invalid")
        summary_steps = value.get("steps")
        step_count = value.get("step_count")
        fee_index = value.get("fee_collection_step_index")
        raw_steps = route.get("steps")
        if (
            not self._is_int(step_count)
            or not 1 <= step_count <= 8
            or not isinstance(summary_steps, list)
            or len(summary_steps) != step_count
            or step_count != len(expected_path)
            or not isinstance(raw_steps, list)
            or len(raw_steps) != step_count
            or not self._is_int(fee_index)
            or not 0 <= fee_index < step_count
            or offer.get("fee_collection_steps") != [fee_index]
        ):
            raise ValueError("assetfare_direct_route_summary_invalid")

        previous_expected_output = None
        previous_minimum_output = None
        any_external = False
        fee_total = 0
        for index, step in enumerate(summary_steps):
            raw_step = raw_steps[index]
            if not isinstance(step, dict) or set(step) != self.DIRECT_SUMMARY_STEP_KEYS:
                raise ValueError("assetfare_direct_route_summary_invalid")
            if step.get("index") != index or step.get("provider") not in self.DIRECT_SUMMARY_PROVIDERS:
                raise ValueError("assetfare_direct_route_summary_invalid")
            provider = step["provider"]
            external = provider == "across_intent_bridge"
            action = "swap" if provider in self.SWAP_PROVIDERS else "bridge"
            expected_provider, expected_step_from, expected_step_to = expected_path[index]
            if (
                provider != expected_provider
                or step.get("action") != action
                or step.get("from") != expected_step_from
                or step.get("to") != expected_step_to
                or step.get("direct_protocol") is not (not external)
                or step.get("external_intent_protocol") is not external
                or step.get("aggregator_api_used") is not False
                or step.get("from") not in self.ENDPOINTS
                or step.get("to") not in self.ENDPOINTS
                or step.get("to").split(":", 1)[0] in self.SOURCE_ONLY_CHAINS
            ):
                raise ValueError("assetfare_direct_route_summary_invalid")
            expected_input = self._summary_amount(step.get("expected_input_base"))
            minimum_input = self._summary_amount(step.get("minimum_input_base"))
            expected_output = self._summary_amount(step.get("expected_output_base"))
            minimum_output = self._summary_amount(step.get("minimum_output_base"))
            if int(minimum_input) > int(expected_input) or int(minimum_output) > int(expected_output):
                raise ValueError("assetfare_direct_route_summary_invalid")
            if index == 0:
                if (
                    step.get("from") != expected_from
                    or expected_input != str(intent.get("estimated_input_base"))
                    or minimum_input != expected_input
                ):
                    raise ValueError("assetfare_direct_route_summary_invalid")
            elif (
                step.get("from") != summary_steps[index - 1].get("to")
                or expected_input != previous_expected_output
                or minimum_input != previous_minimum_output
            ):
                raise ValueError("assetfare_direct_route_summary_invalid")
            if index == step_count - 1 and step.get("to") != expected_to:
                raise ValueError("assetfare_direct_route_summary_invalid")

            raw_action, raw_from, raw_to = self._raw_step_shape(raw_step)
            raw_expected_input = raw_step.get("expected_input_base")
            raw_minimum_input = raw_step.get("floor_input_base")
            raw_expected_output = raw_step.get("expected_output_base")
            raw_minimum_output = raw_step.get("minimum_output_base")
            raw_amounts = (raw_expected_input, raw_minimum_input, raw_expected_output, raw_minimum_output)
            for raw_amount in raw_amounts:
                if not self._is_int(raw_amount) or raw_amount < 1:
                    raise ValueError("assetfare_direct_route_summary_invalid")
            if (
                raw_step.get("index") != index
                or raw_step.get("provider") != provider
                or raw_action != action
                or raw_from != step.get("from")
                or raw_to != step.get("to")
                or raw_step.get("route_fee_bps") != step.get("assetfare_fee_bps")
                or expected_input != str(raw_expected_input)
                or minimum_input != str(raw_minimum_input)
                or expected_output != str(raw_expected_output)
                or minimum_output != str(raw_minimum_output)
            ):
                raise ValueError("assetfare_direct_route_summary_invalid")
            step_fee = step.get("assetfare_fee_bps")
            if not self._is_int(step_fee) or step_fee not in (0, 1) or (step_fee == 1) is not (index == fee_index):
                raise ValueError("assetfare_direct_route_summary_invalid")
            fee_total += step_fee
            any_external = any_external or external
            previous_expected_output = expected_output
            previous_minimum_output = minimum_output

        if (
            fee_total != 1
            or any_external is not expected_external
            or value.get("classification") != ("external_intent" if any_external else "direct_protocol_only")
            or value.get("external_intent_protocol_used") is not any_external
            or value.get("provider_internal_dex_aggregation_possible") is not any_external
            or route.get("mode") != value.get("mode")
            or route.get("input_base") != intent.get("estimated_input_base")
            or str(route.get("expected_output_base")) != previous_expected_output
            or str(route.get("minimum_output_base")) != previous_minimum_output
            or route.get("aggregator_api_used") is not False
            or route.get("external_intent_protocol_used") is not any_external
            or risk.get("external_intent_protocol_used") is not any_external
            or risk.get("provider_internal_dex_aggregation_possible") is not any_external
        ):
            raise ValueError("assetfare_direct_route_summary_invalid")
        return dict(value)

    def _validate_caller_handoff(self, node: Any) -> Any:
        # FAIL-CLOSED validation of the upstream caller_action_plan_handoff. There is
        # NO local fallback: a missing / null / array / extra-field / wrong-field /
        # private-key handoff is a real contract regression and is REJECTED. Executable
        # routes must carry the dual-option handoff (POST /v2/prepare one-shot + full
        # POST /v2/session lifecycle).
        # EXACT 8-field caller-approved request contract (caller_approved first).
        request_fields = [
            "caller_approved",
            "from_chain",
            "from_token",
            "to_chain",
            "to_token",
            "amount_usd",
            "wallets",
            "event_signer_public",
        ]
        if not isinstance(node, dict):
            raise ValueError("assetfare_handoff_missing")
        if node.get("kind") != "caller_operated_rest_prepare":
            raise ValueError("assetfare_handoff_invalid")
        if node.get("method") != "POST":
            raise ValueError("assetfare_handoff_invalid")
        fields = node.get("request_fields")
        if not isinstance(fields, list) or list(fields) != request_fields:
            raise ValueError("assetfare_handoff_request_fields_invalid")
        if node.get("requires_explicit_caller_approval") is not True:
            raise ValueError("assetfare_handoff_invalid")
        if node.get("requires_public_wallet_addresses") is not True:
            raise ValueError("assetfare_handoff_invalid")
        if node.get("assetfare_server_signing") is not False or node.get("assetfare_server_submission") is not False:
            raise ValueError("assetfare_safety_boundary_failed")
        if node.get("caller_must_verify_sign_and_submit") is not True:
            raise ValueError("assetfare_handoff_invalid")
        if node.get("requires_fresh_requote") is not True:
            raise ValueError("assetfare_handoff_invalid")
        if node.get("automatic_prepare_call_forbidden") is not True:
            raise ValueError("assetfare_handoff_invalid")
        note = node.get("note")
        if not isinstance(note, str) or not note:
            raise ValueError("assetfare_handoff_invalid")
        for key in node:
            if key not in self.HANDOFF_ALLOWED_KEYS:
                raise ValueError("assetfare_handoff_extra_field")

        if node.get("available") is not True:
            raise ValueError("assetfare_handoff_invalid")
        if node.get("url") != self.PREPARE_URL:
            raise ValueError("assetfare_handoff_invalid")
        options = node.get("options")
        if not isinstance(options, list) or len(options) != 2:
            raise ValueError("assetfare_handoff_options_invalid")
        prepare_option, session_option = options
        if (
            not isinstance(prepare_option, dict)
            or prepare_option.get("kind") != "one_shot_first_unsigned_bundle"
            or prepare_option.get("method") != "POST"
            or prepare_option.get("url") != self.PREPARE_URL
            or prepare_option.get("requires_explicit_caller_approval") is not True
            or prepare_option.get("requires_public_wallet_addresses") is not True
            or prepare_option.get("assetfare_never_signs_submits_or_auto_calls") is not True
        ):
            raise ValueError("assetfare_handoff_prepare_option_invalid")
        if (
            not isinstance(session_option, dict)
            or session_option.get("kind") != "caller_approved_full_workflow_session"
            or session_option.get("method") != "POST"
            or session_option.get("url") != self.SESSION_URL
            or session_option.get("requires_explicit_caller_approval") is not True
            or session_option.get("requires_public_wallet_addresses") is not True
            or session_option.get("assetfare_never_signs_submits_or_auto_calls") is not True
        ):
            raise ValueError("assetfare_handoff_session_option_invalid")
        lifecycle = session_option.get("lifecycle_urls")
        if not isinstance(lifecycle, dict):
            raise ValueError("assetfare_handoff_session_lifecycle_invalid")
        expected_lifecycle = {
            "create": self.SESSION_URL,
            "read": self.SESSION_URL + "/{session_id}",
            "observe_source": self.SESSION_URL + "/{session_id}/observe-source",
            "observe_output": self.SESSION_URL + "/{session_id}/observe-output",
            "refresh_action": self.SESSION_URL + "/{session_id}/refresh-action",
        }
        for lname, lurl in expected_lifecycle.items():
            entry = lifecycle.get(lname)
            if not isinstance(entry, dict) or entry.get("url") != lurl:
                raise ValueError("assetfare_handoff_session_lifecycle_invalid")
        return dict(node)

    def _validate_caller_handoff_v2(self, node: Any) -> Any:
        # FAIL-CLOSED EXACT validation of the optional caller_action_plan_handoff_v2 sibling. Advisory machine contract:
        # per-kind EXACT option key sets (missing AND extra rejected), nonempty option notes, exact session lifecycle.
        request_fields = ["caller_approved", "from_chain", "from_token", "to_chain", "to_token", "amount_usd", "wallets", "event_signer_public"]
        if not isinstance(node, dict):
            raise ValueError("assetfare_handoff_v2_invalid")
        if node.get("request_fields") != request_fields:
            raise ValueError("assetfare_handoff_v2_request_fields_invalid")
        scalars = {"schema_version": 2, "kind": "caller_operated_rest_prepare", "method": "POST", "requires_explicit_caller_approval": True, "requires_public_wallet_addresses": True, "assetfare_server_signing": False, "assetfare_server_submission": False, "caller_must_verify_sign_and_submit": True, "requires_fresh_requote": True, "automatic_prepare_call_forbidden": True, "selection": "choose_exactly_one", "mutually_exclusive": True, "do_not_call_both": True, "selection_before_signing": True, "once_any_action_submitted_do_not_start_other_mode": True, "enforcement": "advisory_caller_side", "available": True, "url": self.PREPARE_URL}
        for key, val in scalars.items():
            if node.get(key) != val:
                raise ValueError("assetfare_handoff_v2_invalid")
        if not isinstance(node.get("note"), str) or not node["note"]:
            raise ValueError("assetfare_handoff_v2_invalid")
        top_required = {"kind", "url", "method", "request_fields", "assetfare_server_signing", "assetfare_server_submission", "caller_must_verify_sign_and_submit", "requires_fresh_requote", "automatic_prepare_call_forbidden", "requires_explicit_caller_approval", "requires_public_wallet_addresses", "schema_version", "selection", "mutually_exclusive", "do_not_call_both", "selection_before_signing", "once_any_action_submitted_do_not_start_other_mode", "enforcement", "options", "note", "available"}
        # v2 is ALWAYS the available=true machine contract: EXACT key set (no blocker) — reject missing AND extra.
        if set(node) != top_required:
            raise ValueError("assetfare_handoff_v2_extra_field")
        options = node.get("options")
        if not isinstance(options, list) or len(options) != 2:
            raise ValueError("assetfare_handoff_v2_options_invalid")
        prepare_option, session_option = options
        prep_keys = {"kind", "method", "url", "requires_explicit_caller_approval", "requires_public_wallet_addresses", "assetfare_never_signs_submits_or_auto_calls", "preview_or_manual_first_action_only", "not_a_session", "do_not_start_session_after_submission", "note"}
        if not isinstance(prepare_option, dict) or set(prepare_option) != prep_keys:
            raise ValueError("assetfare_handoff_v2_prepare_option_invalid")
        if (prepare_option.get("kind") != "one_shot_first_unsigned_bundle" or prepare_option.get("method") != "POST" or prepare_option.get("url") != self.PREPARE_URL or prepare_option.get("requires_explicit_caller_approval") is not True or prepare_option.get("requires_public_wallet_addresses") is not True or prepare_option.get("assetfare_never_signs_submits_or_auto_calls") is not True or prepare_option.get("preview_or_manual_first_action_only") is not True or prepare_option.get("not_a_session") is not True or prepare_option.get("do_not_start_session_after_submission") is not True or not isinstance(prepare_option.get("note"), str) or not prepare_option["note"]):
            raise ValueError("assetfare_handoff_v2_prepare_option_invalid")
        sess_keys = {"kind", "method", "url", "lifecycle_urls", "requires_explicit_caller_approval", "requires_public_wallet_addresses", "assetfare_never_signs_submits_or_auto_calls", "recommended_for_multistep", "note"}
        if not isinstance(session_option, dict) or set(session_option) != sess_keys:
            raise ValueError("assetfare_handoff_v2_session_option_invalid")
        if (session_option.get("kind") != "caller_approved_full_workflow_session" or session_option.get("method") != "POST" or session_option.get("url") != self.SESSION_URL or session_option.get("requires_explicit_caller_approval") is not True or session_option.get("requires_public_wallet_addresses") is not True or session_option.get("assetfare_never_signs_submits_or_auto_calls") is not True or session_option.get("recommended_for_multistep") is not True or not isinstance(session_option.get("note"), str) or not session_option["note"]):
            raise ValueError("assetfare_handoff_v2_session_option_invalid")
        lifecycle = session_option.get("lifecycle_urls")
        # NOTE: no nested tuple-unpack in the loop target (e.g. `for k, (a, b) in ...`) — smolagents' MethodChecker
        # flags such locals as undefined during Tool.to_dict() serialisation. Use dict values and single locals.
        expected_lifecycle = {"create": {"method": "POST", "url": self.SESSION_URL}, "read": {"method": "GET", "url": self.SESSION_URL + "/{session_id}"}, "observe_source": {"method": "POST", "url": self.SESSION_URL + "/{session_id}/observe-source"}, "observe_output": {"method": "POST", "url": self.SESSION_URL + "/{session_id}/observe-output"}, "refresh_action": {"method": "POST", "url": self.SESSION_URL + "/{session_id}/refresh-action"}}
        if not isinstance(lifecycle, dict) or set(lifecycle) != set(expected_lifecycle):
            raise ValueError("assetfare_handoff_v2_session_lifecycle_invalid")
        for lname, exp in expected_lifecycle.items():
            entry = lifecycle.get(lname)
            if not isinstance(entry, dict) or set(entry) != {"method", "url"} or entry.get("method") != exp["method"] or entry.get("url") != exp["url"]:
                raise ValueError("assetfare_handoff_v2_session_lifecycle_invalid")
        return dict(node)

    def _validate_continuation_v3(
        self, value: Any, quote: Any, intent: Any, route: Any, direct_route_summary: Any
    ) -> Any:
        import re
        from datetime import datetime, timedelta
        from decimal import Decimal, InvalidOperation

        if not isinstance(value, dict) or set(value) != self.CONTINUATION_KEYS:
            raise ValueError("assetfare_continuation_v3_invalid")
        claim = value.get("quote_fingerprint_claim")
        bounds = value.get("input_base_bounds")
        wallets = value.get("required_wallet_chains")
        modes = value.get("allowed_modes")
        step_count = direct_route_summary["step_count"]
        expected_modes = ["session"] if step_count > 1 else ["one_shot", "session"]
        expected_recommended = "session" if step_count > 1 else "one_shot_or_session"
        expected_wallets = sorted(
            {
                endpoint.split(":", 1)[0]
                for step in direct_route_summary["steps"]
                for endpoint in (step["from"], step["to"])
            }
        )
        expected_signer = any(
            step["provider"] == "circle_cctp" and step["from"].startswith("solana:")
            for step in direct_route_summary["steps"]
        )
        hash_pattern = re.compile(r"^[0-9a-f]{64}$")
        approval_fields = [
            "direct_route_summary_sha256", "idempotency_key", "maximum_input_base",
            "minimum_output_base", "quote_fingerprint", "quote_id", "selected_mode",
            "selection_status", "version",
        ]
        if (
            value.get("version") != self.CONTINUATION_VERSION
            or value.get("enforcement") != "server_enforced_quote_binding"
            or value.get("selection_status") != "unranked_candidate"
            or value.get("automatic_selection_forbidden") is not True
            or value.get("caller_approved_boolean_is_not_human_proof") is not True
            or value.get("quote_id") != quote.get("quote_id")
            or not isinstance(value.get("quote_fingerprint"), str)
            or hash_pattern.fullmatch(value["quote_fingerprint"]) is None
            or value.get("quote_fingerprint_spec")
            != "sha256(UTF-8 sorted-key compact JSON of quote_fingerprint_claim; every numeric claim is a non-exponent decimal string)"
            or value.get("quote_payload_sha256_spec") != self.QUOTE_PAYLOAD_SHA256_SPEC
            or value.get("ttl_seconds") != quote.get("ttl_seconds")
            or value.get("intent") != intent
            or not isinstance(bounds, dict)
            or set(bounds) != {"minimum", "maximum"}
            or bounds.get("minimum") != str(intent.get("estimated_input_base"))
            or bounds.get("maximum") != str(intent.get("estimated_input_base"))
            or value.get("minimum_output_base") != str(route.get("minimum_output_base"))
            or wallets != expected_wallets
            or value.get("event_signer_public_required") is not expected_signer
            or value.get("step_count") != step_count
            or modes != expected_modes
            or value.get("recommended_mode") != expected_recommended
            or value.get("approval_v3_required_fields") != approval_fields
            or value.get("legacy_handoff_enforcement") != "legacy_advisory"
            or value.get("server_signing") is not False
            or value.get("server_submission") is not False
        ):
            raise ValueError("assetfare_continuation_v3_invalid")
        session_header = value.get("session_header")
        if session_header != {
            "name": "X-AssetFare-Session-Token", "required_for": "session",
            "caller_generated": True, "minimum_entropy_bits": 256,
            "server_returns_raw_value": False,
        }:
            raise ValueError("assetfare_continuation_v3_invalid")
        if value.get("idempotency") != {
            "required": True, "field": "idempotency_key",
            "pattern": "^[A-Za-z0-9._:-]{8,128}$", "scope": "quote_and_selected_mode",
        }:
            raise ValueError("assetfare_continuation_v3_invalid")
        if not isinstance(claim, dict) or set(claim) != self.FINGERPRINT_CLAIM_KEYS:
            raise ValueError("assetfare_continuation_v3_invalid")
        try:
            amount_decimal = format(Decimal(str(intent["amount_usd"])), "f")
            if "." in amount_decimal:
                amount_decimal = amount_decimal.rstrip("0").rstrip(".")
            if amount_decimal in ("", "-0"):
                amount_decimal = "0"
        except (InvalidOperation, ValueError):
            raise ValueError("assetfare_continuation_v3_invalid") from None
        expected_claim = {
            "version": self.CONTINUATION_VERSION,
            "quote_id": value["quote_id"],
            "issued_at": value.get("issued_at"),
            "expires_at": value.get("expires_at"),
            "ttl_seconds": str(value["ttl_seconds"]),
            "intent": {
                "from": intent["from"], "to": intent["to"],
                "amount_usd_decimal": amount_decimal,
                "estimated_input_base": str(intent["estimated_input_base"]),
            },
            "direct_route_summary_sha256": value.get("direct_route_summary_sha256"),
            "quote_payload_sha256": value.get("quote_payload_sha256"),
            "quote_payload_sha256_spec": self.QUOTE_PAYLOAD_SHA256_SPEC,
            "input_base_bounds": dict(bounds),
            "minimum_output_base": value["minimum_output_base"],
            "required_wallet_chains": list(wallets),
            "event_signer_public_required": expected_signer,
            "step_count": str(step_count),
            "allowed_modes": list(expected_modes),
            "server_signing": False,
            "server_submission": False,
        }
        if (
            claim != expected_claim
            or self._canonical_sha256(claim) != value["quote_fingerprint"]
            or self._canonical_sha256(direct_route_summary) != value.get("direct_route_summary_sha256")
            or self._quote_payload_sha256(quote, direct_route_summary) != value.get("quote_payload_sha256")
        ):
            raise ValueError("assetfare_continuation_v3_invalid")
        try:
            issued = datetime.fromisoformat(str(value.get("issued_at")).replace("Z", "+00:00"))
            expires = datetime.fromisoformat(str(value.get("expires_at")).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("assetfare_continuation_v3_invalid") from None
        if (
            issued.tzinfo is None
            or expires.tzinfo is None
            or expires <= issued
            or abs((expires - issued).total_seconds() - value["ttl_seconds"]) > 0.001
            or expires <= self._utcnow()
            or issued > self._utcnow() + timedelta(seconds=self.MAX_FUTURE_SKEW_S)
        ):
            raise ValueError("assetfare_continuation_v3_invalid")
        return {
            "version": self.CONTINUATION_VERSION,
            "quote_id": value["quote_id"],
            "quote_fingerprint": value["quote_fingerprint"],
            "expires_at": value["expires_at"],
            "ttl_seconds": value["ttl_seconds"],
            "selection_status": "unranked_candidate",
            "required_wallet_chains": list(wallets),
            "event_signer_public_required": expected_signer,
            "allowed_modes": list(expected_modes),
            "recommended_mode": expected_recommended,
            "openapi_url": "https://api.assetfare.dev/v2/openapi",
            "legacy_handoff_enforcement": "legacy_advisory",
            "automatic_selection_forbidden": True,
            "caller_approved_boolean_is_not_human_proof": True,
            "wallet_collection_performed": False,
            "approval_v3_generated": False,
            "prepare_calls": 0,
            "session_calls": 0,
            "server_signing": False,
            "server_submission": False,
        }

    def _canonical_sha256(self, value: Any) -> str:
        import hashlib
        import json

        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _typed_canonical(self, value: Any) -> bytes:
        import math
        import struct

        if value is None:
            return b"n"
        if value is True:
            return b"t"
        if value is False:
            return b"f"
        if isinstance(value, int):
            if abs(value) > 9007199254740991:
                raise ValueError("assetfare_continuation_v3_invalid")
            return b"d" + struct.pack(">d", float(value)).hex().encode("ascii")
        if isinstance(value, float):
            if not math.isfinite(value) or (value.is_integer() and abs(value) > 9007199254740991):
                raise ValueError("assetfare_continuation_v3_invalid")
            return b"d" + struct.pack(">d", value).hex().encode("ascii")
        if isinstance(value, str):
            for character in value:
                if 0xD800 <= ord(character) <= 0xDFFF:
                    raise ValueError("assetfare_continuation_v3_invalid")
            encoded = value.encode("utf-8")
            return b"s" + str(len(encoded)).encode("ascii") + b":" + encoded
        if isinstance(value, list):
            encoded_items = []
            for element in value:
                encoded_items.append(self._typed_canonical(element))
            return b"a" + str(len(value)).encode("ascii") + b":[" + b"".join(encoded_items) + b"]"
        if isinstance(value, dict):
            keys = []
            for candidate in value:
                if not isinstance(candidate, str):
                    raise ValueError("assetfare_continuation_v3_invalid")
                for character in candidate:
                    if 0xD800 <= ord(character) <= 0xDFFF:
                        raise ValueError("assetfare_continuation_v3_invalid")
                keys.append(candidate)
            keys.sort()
            encoded_items = []
            for key_name in keys:
                encoded_items.append(self._typed_canonical(key_name))
                encoded_items.append(self._typed_canonical(value[key_name]))
            return b"o" + str(len(keys)).encode("ascii") + b":{" + b"".join(encoded_items) + b"}"
        raise ValueError("assetfare_continuation_v3_invalid")

    def _quote_payload_projection(self, quote: Any, direct_route_summary: Any) -> Any:
        import copy

        payload = copy.deepcopy({key: item for key, item in quote.items() if key != "continuation_v3"})
        try:
            summary_steps = direct_route_summary["steps"]
            route = payload["route"]
            raw_steps = route["steps"]
            intent = payload["intent"]
            if not isinstance(summary_steps, list) or not summary_steps or len(raw_steps) != len(summary_steps):
                raise ValueError
            intent["estimated_input_base"] = summary_steps[0]["expected_input_base"]
            route["input_base"] = summary_steps[0]["expected_input_base"]
            route["expected_output_base"] = summary_steps[-1]["expected_output_base"]
            route["minimum_output_base"] = summary_steps[-1]["minimum_output_base"]
            for raw, exact in zip(raw_steps, summary_steps):
                raw["expected_input_base"] = exact["expected_input_base"]
                raw["floor_input_base"] = exact["minimum_input_base"]
                raw["expected_output_base"] = exact["expected_output_base"]
                raw["minimum_output_base"] = exact["minimum_output_base"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("assetfare_continuation_v3_invalid") from None
        return payload

    def _quote_payload_sha256(self, quote: Any, direct_route_summary: Any) -> str:
        import hashlib

        return hashlib.sha256(
            self._typed_canonical(self._quote_payload_projection(quote, direct_route_summary))
        ).hexdigest()

    def forward(
        self,
        from_chain: str,
        from_token: str,
        to_chain: str,
        to_token: str,
        amount_usd: float,
    ) -> Any:
        import uuid
        from datetime import datetime, timedelta

        amount = self._amount(amount_usd)
        from_u = self._endpoint(from_chain, from_token, "source")
        to_u = self._endpoint(to_chain, to_token, "destination")
        if (from_chain, from_u) == (to_chain, to_u):
            raise ValueError("assetfare_identity_route_rejected")
        if to_chain in self.SOURCE_ONLY_CHAINS:
            raise ValueError("assetfare_destination_endpoint_invalid")
        source_only = from_chain in self.SOURCE_ONLY_CHAINS
        if source_only and not (
            from_u == "USDC" and to_chain in {"base", "arbitrum"} and to_u == "USDC"
        ):
            raise ValueError("assetfare_source_endpoint_invalid")
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        data = self._request(
            "POST",
            "/v2/quote",
            {
                "from_chain": from_chain,
                "from_token": from_u,
                "to_chain": to_chain,
                "to_token": to_u,
                "amount_usd": amount,
            },
            budget_deadline,
        )
        self._no_sign_tree(data)
        intent = self._obj(data, "intent")
        offer = self._obj(data, "offer")
        route = self._obj(data, "route")
        risk = self._obj(data, "risk")
        execution = self._obj(data, "execution")

        if data.get("status") != "capped_public_agent_release":
            raise ValueError("assetfare_response_invalid")
        quote_id_ok = True
        try:
            uuid.UUID(str(data.get("quote_id")))
        except (ValueError, AttributeError, TypeError):
            quote_id_ok = False
        if not quote_id_ok:
            raise ValueError("assetfare_response_invalid")
        ttl = data.get("ttl_seconds")
        if not self._is_int(ttl) or not (0 < ttl <= self.MAX_TTL_SECONDS):
            raise ValueError("assetfare_response_invalid")
        as_of = data.get("as_of")
        if not isinstance(as_of, str) or "T" not in as_of:
            raise ValueError("assetfare_response_invalid")
        # Python 3.10's datetime.fromisoformat does not accept a trailing 'Z'
        # (added in 3.11). Normalize 'Z' -> '+00:00' so RFC3339 UTC timestamps
        # validate identically on 3.10 and 3.11+. The original string is echoed
        # back unchanged in the result.
        normalized_as_of = as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
        as_of_dt = None
        as_of_parse_failed = False
        try:
            as_of_dt = datetime.fromisoformat(normalized_as_of)
        except ValueError:
            as_of_parse_failed = True
        if as_of_parse_failed:
            raise ValueError("assetfare_response_invalid")
        if as_of_dt.tzinfo is None or as_of_dt.utcoffset() is None:
            raise ValueError("assetfare_response_invalid")
        now = self._utcnow()
        if as_of_dt > now + timedelta(seconds=self.MAX_FUTURE_SKEW_S):
            raise ValueError("assetfare_response_invalid")
        if as_of_dt + timedelta(seconds=ttl) < now:
            raise ValueError("assetfare_response_invalid")

        expected_from = from_chain + ":" + from_u
        expected_to = to_chain + ":" + to_u

        if intent.get("from") != expected_from or intent.get("to") != expected_to:
            raise ValueError("assetfare_response_invalid")
        if not self._finite(intent.get("amount_usd")) or float(intent["amount_usd"]) != amount:
            raise ValueError("assetfare_response_invalid")
        if not self._is_int(intent.get("estimated_input_base")) or intent["estimated_input_base"] < 1:
            raise ValueError("assetfare_response_invalid")

        if route.get("route") != expected_from + "->" + expected_to:
            raise ValueError("assetfare_response_invalid")
        steps = route.get("steps")
        if not isinstance(steps, list) or len(steps) < 1:
            raise ValueError("assetfare_response_invalid")
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("assetfare_response_invalid")
        if not self._is_int(route.get("quote_latency_ms")) or route["quote_latency_ms"] < 0:
            raise ValueError("assetfare_response_invalid")
        self._no_sign(route)

        exp = offer.get("expected_receive_amount")
        mn = offer.get("estimated_min_receive_amount")
        exp_usd = offer.get("expected_receive_usd")
        mn_usd = offer.get("estimated_min_receive_usd")
        for v in (exp, mn, exp_usd, mn_usd):
            if not self._finite(v):
                raise ValueError("assetfare_response_invalid")
        if not (float(mn) > 0 and float(exp) >= float(mn)):
            raise ValueError("assetfare_response_invalid")
        if not (float(mn_usd) > 0 and float(exp_usd) >= float(mn_usd)):
            raise ValueError("assetfare_response_invalid")
        if offer.get("output_symbol") != to_u:
            raise ValueError("assetfare_response_invalid")
        # Fee EXACTLY 1bp + modeled/collectible + fee_collection literal.
        self._validate_offer_fee(offer, len(steps))
        fee = offer["assetfare_fee_bps"]
        fee_steps = offer["fee_collection_steps"]
        eta = offer.get("estimated_time_seconds")
        if eta is not None and (not self._is_int(eta) or eta < 0):
            raise ValueError("assetfare_response_invalid")

        cost=data.get("cost_summary")
        expected_cost=max(0.0,amount-float(exp_usd));maximum_cost=max(0.0,amount-float(mn_usd))
        if cost is None:
            small=maximum_cost/amount>=.01
            cost={"scope":"token_path_only_network_gas_excluded","input_value_usd":amount,"expected_receive_value_usd":float(exp_usd),"minimum_receive_value_usd":float(mn_usd),"expected_total_cost_usd":expected_cost,"maximum_total_cost_usd":maximum_cost,"expected_total_cost_percent":expected_cost/amount*100,"maximum_total_cost_percent":maximum_cost/amount*100,"assetfare_service_fee":{"bps":1,"estimated_usd":min(amount/10_000,5.0),"included_in_receive_amount":True,"note":"AssetFare service fee only; not the total route cost"},"provider_fee_components":[],"unpriced_costs":["provider_fee_breakdown_unavailable_legacy_core","source_chain_network_fee"],"rankable_all_in":False,"small_amount_warning":small,"warning":"Legacy-core fallback: total derived from receive value; provider detail unavailable." if small else None}
        close=lambda a,b,t=0.000001:abs(float(a)-float(b))<=t
        if not isinstance(cost,dict) or cost.get("scope")!="token_path_only_network_gas_excluded" or cost.get("rankable_all_in") is not False or not self._finite(cost.get("input_value_usd")) or not self._finite(cost.get("expected_receive_value_usd")) or not self._finite(cost.get("minimum_receive_value_usd")) or not close(cost.get("input_value_usd"),amount) or not close(cost.get("expected_receive_value_usd"),float(exp_usd)) or not close(cost.get("minimum_receive_value_usd"),float(mn_usd)):
            raise ValueError("assetfare_cost_summary_invalid")
        for key in ("expected_total_cost_usd","maximum_total_cost_usd","expected_total_cost_percent","maximum_total_cost_percent"):
            if not self._finite(cost.get(key)) or float(cost[key])<0:raise ValueError("assetfare_cost_summary_invalid")
        if not close(cost["expected_total_cost_usd"],expected_cost) or not close(cost["maximum_total_cost_usd"],maximum_cost) or not close(cost["expected_total_cost_percent"],expected_cost/amount*100,0.0001) or not close(cost["maximum_total_cost_percent"],maximum_cost/amount*100,0.0001) or float(cost["maximum_total_cost_usd"])<float(cost["expected_total_cost_usd"]):
            raise ValueError("assetfare_cost_summary_invalid")
        service=cost.get("assetfare_service_fee")
        if not isinstance(service,dict) or service.get("bps")!=1 or service.get("included_in_receive_amount") is not True or not self._finite(service.get("estimated_usd")) or not close(service["estimated_usd"],min(amount/10_000,5.0)):
            raise ValueError("assetfare_cost_summary_invalid")
        components=cost.get("provider_fee_components");unpriced=cost.get("unpriced_costs");small=cost.get("small_amount_warning")
        if not isinstance(components,list) or not isinstance(unpriced,list) or not unpriced or not isinstance(small,bool):
            raise ValueError("assetfare_cost_summary_invalid")
        component_expected=component_maximum=0.0
        for row in components:
            if not isinstance(row,dict) or not self._finite(row.get("expected_usd")) or not self._finite(row.get("maximum_usd")) or float(row["expected_usd"])<0 or float(row["maximum_usd"])<float(row["expected_usd"]):raise ValueError("assetfare_cost_summary_invalid")
            component_expected+=float(row["expected_usd"]);component_maximum+=float(row["maximum_usd"])
        if component_expected>expected_cost+0.000001 or component_maximum>maximum_cost+0.000001 or small!=(float(cost["maximum_total_cost_percent"])>=1) or (small and not isinstance(cost.get("warning"),str)) or (not small and cost.get("warning") is not None):raise ValueError("assetfare_cost_summary_invalid")
        eta_summary=data.get("eta")
        if eta_summary is not None:
            if not isinstance(eta_summary,dict) or eta_summary.get("estimated_time_seconds")!=eta or not isinstance(eta_summary.get("complete_route_estimate"),bool):raise ValueError("assetfare_eta_invalid")
            complete=eta_summary["complete_route_estimate"];eta_range=eta_summary.get("estimated_time_range_seconds")
            if complete:
                if eta is None or not isinstance(eta_range,list) or len(eta_range)!=2 or not all(self._is_int(v) and v>=0 for v in eta_range) or eta_range[0]>eta_range[1] or eta_range[1]!=eta:raise ValueError("assetfare_eta_invalid")
            elif eta is not None or eta_range is not None:raise ValueError("assetfare_eta_invalid")

        if not isinstance(risk.get("non_atomic"), bool):
            raise ValueError("assetfare_response_invalid")
        if risk.get("fresh_quote_required_each_step") is not True:
            raise ValueError("assetfare_response_invalid")
        self._no_sign(risk)
        direct_route_summary = self._validate_direct_route_summary(
            data.get("direct_route_summary"), expected_from, expected_to, intent, offer, route, risk
        )

        # The quoted route is currently available through caller-operated wallets.
        if not isinstance(execution.get("first_unsigned_action_supported"), bool):
            raise ValueError("assetfare_response_invalid")
        if execution.get("future_actions_require_verified_receipts") is not True:
            raise ValueError("assetfare_response_invalid")
        if (
            execution.get("supported") is not True
            or execution.get("first_unsigned_action_supported") is not True
            or ("blocker" in execution and execution.get("blocker") is not None)
        ):
            raise ValueError("assetfare_execution_boundary_failed")

        # FAIL-CLOSED validation of the upstream caller_action_plan_handoff. It is
        # deliberately suppressed from output; a missing/malformed handoff remains a contract regression.
        self._validate_caller_handoff(data.get("caller_action_plan_handoff"))
        # Transition-safe v2 sibling: v1 always validated; version and sibling strictly coupled (both or neither).
        has_version = "handoff_schema_version" in data
        has_sibling = "caller_action_plan_handoff_v2" in data
        if has_version != has_sibling:
            raise ValueError("assetfare_handoff_schema_version_invalid")
        if has_sibling:
            if data.get("handoff_schema_version") != 2:
                raise ValueError("assetfare_handoff_schema_version_invalid")
            self._validate_caller_handoff_v2(data.get("caller_action_plan_handoff_v2"))

        continuation_descriptor = self._validate_continuation_v3(
            data.get("continuation_v3"), data, intent, route, direct_route_summary
        )

        fee_steps_out = [int(s) for s in fee_steps]
        fee_note = "AssetFare 1bp is collected only on the eligible successful atomic action."

        return {
            "from": expected_from,
            "to": expected_to,
            "amount_usd": amount,
            "output_symbol": to_u,
            "expected_receive_amount": float(exp),
            "estimated_min_receive_amount": float(mn),
            "expected_receive_usd": float(exp_usd),
            "estimated_min_receive_usd": float(mn_usd),
            "assetfare_fee_bps": fee,
            "fee_modeled_bps": int(offer["fee_modeled_bps"]),
            "fee_collectible_now": bool(offer["fee_collectible_now"]),
            "assetfare_fee_conditional": fee > 0,
            "fee_collection_steps": fee_steps_out,
            "fee_collection": self.FEE_COLLECTION_CONST,
            "fee_note": fee_note,
            "estimated_time_seconds": eta if self._is_int(eta) else None,
            "cost_summary": cost,
            "eta": eta_summary or {"estimated_time_seconds":eta if self._is_int(eta) else None,"estimated_time_range_seconds":None,"complete_route_estimate":False,"sources":[],"note":"Legacy-core fallback; full ETA provenance unavailable"},
            "direct_route_summary": direct_route_summary,
            "continuation_descriptor": continuation_descriptor,
            "non_atomic": risk["non_atomic"],
            "quote_id": data["quote_id"],
            "as_of": as_of,
            "ttl_seconds": ttl,
            "source_only": source_only,
            "execution_supported": True,
            "execution_blocker": None,
            "evaluation_guidance": dict(self.EVALUATION_GUIDANCE),
            "server_signs_or_submits": False,
        }
