"""AssetFare read-only quote tool for smolagents agents.

Self-contained smolagents ``Tool`` (Hub-loadable via ``load_tool``). It fetches
one quote and returns a validated, FAIL-CLOSED passthrough of the upstream
caller-approved, non-custodial v2 action-plan handoff; it never authenticates a
wallet, opens a session, prepares an unsigned action, signs, or submits. It fails
closed on anything that claims the server will sign or submit.

The caller_action_plan_handoff is passed through verbatim (validated) with NO
local fallback: a missing/null/array/extra/wrong-field/private-key handoff is a
real contract regression and is REJECTED, not synthesized. Executable routes
carry the dual-option handoff (POST /v2/prepare one-shot + full POST /v2/session
lifecycle). Polygon and Optimism are directional native-USDC source-only origins
(to Base/Arbitrum USDC) and use the same executable caller-approved handoff.

All logic lives inside this class (imports done inside methods, no sibling-module
imports) so ``Tool.to_dict`` / ``push_to_hub`` can serialise it to a single file.
Injectable ``session`` / ``monotonic`` / ``utcnow`` (defaulting to real ones) let
the tool be unit-tested offline with mocks.
"""

from typing import Any, Optional

from smolagents import Tool


class AssetFareQuoteTool(Tool):
    name = "assetfare_quote"
    description = (
        "Read-only quote client for one cross-chain corridor via the AssetFare v2 "
        "API (fixed origin https://api.assetfare.dev). This tool's entire scope is "
        "to fetch and validate a single conversion quote and return it; it is not "
        "the AssetFare service and does not itself prepare, sign or submit. It "
        "covers 6 source chains (solana, base, arbitrum, robinhood, polygon, "
        "optimism), 11 (chain, token) source endpoints and 76 directed quote routes, "
        "for a USD amount of 1 to 1000. All 76 routes are execution-ready; Polygon "
        "and Optimism are directional native-USDC source-only origins to Base or "
        "Arbitrum USDC and each uses an audited 1bp executor. It never authenticates "
        "a wallet, opens a session, prepares an "
        "unsigned action, signs or submits. For an execution-ready route its result "
        "passes through (validated) the caller_action_plan_handoff, which names the "
        "separate caller-operated POST /v2/prepare (one-shot) and POST /v2/session "
        "(full lifecycle) steps; the returned 'server_signs_or_submits' is always "
        "false. It returns expected/minimum receive amounts (native and USD), the "
        "exact assetfare_fee_bps (0 or 1) with modeled/collectible flags and the "
        "eligible fee_collection_steps, ETA, the non-atomic risk flag, a quote id, an "
        "as_of timestamp and a ttl. Every response is validated and the call fails "
        "closed if anything claims the server will sign or submit, if the quote is "
        "stale or future-dated, if the fee is out of the exact {0,1} contract, if the "
        "handoff is missing or deviates from the caller-approved 8-field contract, or "
        "if the route does not match the requested corridor. Inputs: from_chain, "
        "from_token, to_chain, to_token (a supported chain/token pair, source != "
        "destination) and amount_usd (1-1000). This tool does NOT execute, bridge, "
        "swap, sign or move funds; acting on a quote is a separate caller wallet "
        "action taken outside this tool after explicit approval."
    )
    inputs = {
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
            "description": "Notional amount in USD to convert, from 1 to 1000 inclusive.",
        },
    }
    output_type = "object"

    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576
    MAX_TTL_SECONDS = 86400
    MAX_FUTURE_SKEW_S = 300
    MIN_USD = 1.0
    MAX_USD = 1000.0
    PREPARE_URL = "https://api.assetfare.dev/v2/prepare"
    SESSION_URL = "https://api.assetfare.dev/v2/session"
    FEE_COLLECTION_CONST = "only_on_eligible_successful_executor_step"
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
    HANDOFF_ALLOWED_KEYS = {
        "kind",
        "url",
        "method",
        "requires_explicit_caller_approval",
        "requires_public_wallet_addresses",
        "request_fields",
        "assetfare_server_signing",
        "assetfare_server_submission",
        "caller_must_verify_sign_and_submit",
        "requires_fresh_requote",
        "automatic_prepare_call_forbidden",
        "options",
        "note",
        "available",
        "blocker",
    }

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
        if not (self.MIN_USD <= amount <= self.MAX_USD):
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
        # Fee is EXACTLY {0,1}bp, collected at most once on an eligible successful
        # executor step. fee=1 => fee_collection_steps holds EXACTLY one valid,
        # in-range, non-duplicate index; fee=0 => []. Rejects fee>1 / negative / 8bp,
        # 2-step or 0-step mismatches, out-of-range or duplicate indices. Also
        # validates fee_modeled_bps, fee_collectible_now, and the fee_collection literal.
        if offer.get("fee_collection") != self.FEE_COLLECTION_CONST:
            raise ValueError("assetfare_response_invalid")
        fee = offer.get("assetfare_fee_bps")
        if not self._is_int(fee) or fee not in (0, 1):
            raise ValueError("assetfare_response_invalid")
        modeled = offer.get("fee_modeled_bps")
        if not self._is_int(modeled) or modeled not in (0, 1):
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
        if fee == 1 and len(steps) != 1:
            raise ValueError("assetfare_fee_step_count_mismatch")
        if fee == 0 and steps != []:
            raise ValueError("assetfare_fee_step_count_mismatch")

    def _validate_caller_handoff(self, node: Any) -> Any:
        # FAIL-CLOSED passthrough of the upstream caller_action_plan_handoff. There is
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
        # Fee EXACTLY {0,1}bp + modeled/collectible + fee_collection literal.
        self._validate_offer_fee(offer, len(steps))
        fee = offer["assetfare_fee_bps"]
        fee_steps = offer["fee_collection_steps"]
        eta = offer.get("estimated_time_seconds")
        if eta is not None and (not self._is_int(eta) or eta < 0):
            raise ValueError("assetfare_response_invalid")

        if not isinstance(risk.get("non_atomic"), bool):
            raise ValueError("assetfare_response_invalid")
        if risk.get("fresh_quote_required_each_step") is not True:
            raise ValueError("assetfare_response_invalid")
        self._no_sign(risk)

        # Every supported route is execution-ready through caller-operated wallets.
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

        # FAIL-CLOSED passthrough of the upstream caller_action_plan_handoff. No local
        # fallback: a missing/malformed handoff is a real contract regression.
        caller_action_plan_handoff = self._validate_caller_handoff(data.get("caller_action_plan_handoff"))

        fee_steps_out = [int(s) for s in fee_steps]
        if fee > 0:
            fee_note = (
                "AssetFare " + str(fee) + "bp is collected only on an eligible successful executor "
                "step (conditional, not an unconditional flat fee)."
            )
        else:
            fee_note = "No AssetFare fee is collected on this route (0bp)."

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
            "non_atomic": risk["non_atomic"],
            "quote_id": data["quote_id"],
            "as_of": as_of,
            "ttl_seconds": ttl,
            "source_only": source_only,
            "execution_supported": True,
            "execution_blocker": None,
            "server_signs_or_submits": False,
            "caller_action_plan_handoff": caller_action_plan_handoff,
        }
