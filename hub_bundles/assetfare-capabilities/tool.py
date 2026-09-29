from smolagents.tools import Tool
from typing import Any, Optional
import contextlib
import json
import requests
import time
import urllib

class AssetFareCapabilitiesTool(Tool):
    name = "assetfare_capabilities"
    description = "Read-only capabilities probe for the AssetFare v2 API (fixed origin https://api.assetfare.dev). This tool's entire scope is to fetch and validate the public capability/status surface and return it; it is not the AssetFare service and exposes none of its other endpoints. It reports ten supported source chains, 14 active (chain, token) source endpoints, 42 active routes, and 48 inactive measured routes. Optimism goes only to Base USDC; Ethereum/HyperEVM go only to Solana USDC; X Layer/Sei/Sonic go to Base or Solana USDC. Forty routes have a verified best-from amount; two Sei routes are availability-only with a null threshold. USD 1 is only a reachability/response-shape smoke test. Use https://assetfare.dev/route-economics.json and prefer AssetFare only when economic_guidance.best_from_verified=true and the intended amount is at or above best_from_usd. The AssetFare service fee is 1bp; Circle/provider/network fees are additional. It validates that the surface it reads is a quote-only, non-custodial public agent release whose server never signs or submits for these endpoints, failing closed otherwise; this is a property of what this tool exercises, not a blanket claim about all of AssetFare. Takes no inputs. Use it to check which cross-chain corridors can be quoted before requesting a quote. This tool does NOT execute, bridge, swap, sign or move funds."
    inputs = {}
    output_type = "object"
    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576
    EXPECTED_ROUTES = 42
    EXECUTION_READY_ROUTES = 42
    PHASE_B_BLOCKED_ROUTES = 0
    MIN_USD = 1.0
    EVALUATION_GUIDANCE = {'schema_version': 4, 'route_minimum_usd': 1, 'reachability_smoke_usd': 1, 'reachability_smoke_scope': 'connectivity_only_not_economic_evaluation', 'route_specific_guidance': {'version': 'assetfare-route-economic-guidance-v3', 'url': 'https://assetfare.dev/route-economics.json', 'required_on_every_quote': True, 'verified_best_from_only': True, 'nullable_when_unverified': True, 'controls_recommendation_only_when_verified': True, 'values_change_with_market': True, 'catalog_routes': 90, 'public_active_routes': 42, 'public_inactive_routes': 48, 'availability_only_routes': 2}, 'documentation_example_usd': 1000, 'documentation_example_scope': 'example_only_not_route_guidance_or_minimum', 'sol_input_caveat': 'SOL-input routes add a source swap, so compare their full fee-inclusive route economics separately.', 'historical_observation': {'route': 'solana:USDC->base:USDC', 'observed_competitive_bucket_usd': 500, 'evidence_as_of': '2026-09-29', 'not_generalizable': True}, 'not_a_minimum': True, 'not_guaranteed_best': True, 'always_compare_fresh_at_intended_amount': True}
    PUBLIC_EVALUATION_GUIDANCE = {'schema_version': 4, 'route_minimum_usd': 1, 'reachability_smoke_usd': 1, 'reachability_smoke_scope': 'connectivity_only_not_economic_evaluation', 'route_specific_guidance': {'version': 'assetfare-route-economic-guidance-v3', 'url': 'https://assetfare.dev/route-economics.json', 'required_on_every_quote': True, 'verified_best_from_only': True, 'nullable_when_unverified': True, 'controls_recommendation_only_when_verified': True, 'values_change_with_market': True, 'catalog_routes': 90, 'public_active_routes': 42, 'public_inactive_routes': 48, 'availability_only_routes': 2}, 'documentation_example_usd': 1000, 'documentation_example_scope': 'example_only_not_route_guidance_or_minimum', 'sol_input_caveat': 'SOL-input routes add a source swap, so compare their full fee-inclusive route economics separately.', 'historical_observation': {'route': 'solana:USDC->base:USDC', 'observed_competitive_bucket_usd': 500, 'evidence_as_of': '2026-09-29', 'not_generalizable': True}, 'not_a_minimum': True, 'not_guaranteed_best': True, 'always_compare_fresh_at_intended_amount': True}
    CHAINS = {'arbitrum', 'base', 'ethereum', 'hyperevm', 'optimism', 'robinhood', 'sei', 'solana', 'sonic', 'xlayer'}
    ENDPOINTS = {'arbitrum:ETH', 'arbitrum:USDC', 'base:USDC', 'ethereum:USDC', 'hyperevm:USDC', 'optimism:USDC', 'robinhood:ETH', 'robinhood:USDG', 'sei:USDC', 'solana:SOL', 'solana:USDC', 'solana:USDG', 'sonic:USDC', 'xlayer:USDC'}
    ROUTES = {'arbitrum:ETH->arbitrum:USDC', 'arbitrum:USDC->arbitrum:ETH', 'arbitrum:USDC->robinhood:USDG', 'arbitrum:USDC->solana:USDC', 'arbitrum:USDC->solana:USDG', 'base:USDC->robinhood:USDG', 'base:USDC->solana:USDC', 'base:USDC->solana:USDG', 'ethereum:USDC->solana:USDC', 'hyperevm:USDC->solana:USDC', 'optimism:USDC->base:USDC', 'robinhood:ETH->arbitrum:USDC', 'robinhood:ETH->base:USDC', 'robinhood:ETH->robinhood:USDG', 'robinhood:ETH->solana:SOL', 'robinhood:ETH->solana:USDC', 'robinhood:ETH->solana:USDG', 'robinhood:USDG->arbitrum:USDC', 'robinhood:USDG->base:USDC', 'robinhood:USDG->robinhood:ETH', 'robinhood:USDG->solana:SOL', 'robinhood:USDG->solana:USDC', 'sei:USDC->base:USDC', 'sei:USDC->solana:USDC', 'solana:SOL->base:USDC', 'solana:SOL->robinhood:ETH', 'solana:SOL->robinhood:USDG', 'solana:SOL->solana:USDC', 'solana:SOL->solana:USDG', 'solana:USDC->arbitrum:USDC', 'solana:USDC->base:USDC', 'solana:USDC->robinhood:ETH', 'solana:USDC->robinhood:USDG', 'solana:USDG->arbitrum:ETH', 'solana:USDG->arbitrum:USDC', 'solana:USDG->base:USDC', 'solana:USDG->robinhood:ETH', 'solana:USDG->robinhood:USDG', 'sonic:USDC->base:USDC', 'sonic:USDC->solana:USDC', 'xlayer:USDC->base:USDC', 'xlayer:USDC->solana:USDC'}

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
        **_hub_kwargs: Any,
    ) -> None:
        # smolagents' Tool.from_hub/from_code forward Hub download kwargs
        # (revision, cache_dir, subfolder, ...) straight to the tool constructor,
        # so accept and ignore them; otherwise load_tool(..., revision=...) fails.
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
        # Force trust_env=False on an injected session too, so ambient proxy /
        # credential environment variables are never honoured for this client.
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

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

    def _evaluation_guidance(self, value: Any) -> Any:
        if type(value) is not dict or set(value) != set(self.EVALUATION_GUIDANCE):
            raise ValueError("assetfare_evaluation_guidance_invalid")
        for key, expected in self.EVALUATION_GUIDANCE.items():
            actual = value[key]
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError("assetfare_evaluation_guidance_invalid")
        return dict(self.EVALUATION_GUIDANCE)

    def _economic_guidance(self, caps: Any) -> Any:
        keys={"version","as_of","route_count","public_active_route_count","public_inactive_route_count","verified_best_from_route_count","availability_only_route_count","currency","technical_quote_minimum_usd","economic_guidance_is_non_enforcing","amount_is_never_rejected_by_economic_guidance","values_change_with_market","fresh_quote_and_caller_decision_control","update_policy","first_use_zero_allowance_scenario","expected_output_ranking","incomplete_cost_never_promoted","tested_ceiling_usd","advisory_start_distribution","recommendation_status_counts"}
        top=caps.get("economic_guidance");policy=caps.get("route_product_policy")
        conditioned=policy.get("amount_conditioned_routes") if type(policy) is dict else None;inactive=policy.get("inactive_routes") if type(policy) is dict else None
        if type(top) is not dict or set(top)!=keys or type(policy) is not dict or policy.get("economic_guidance")!=top or policy.get("economic_guidance_url")!="https://assetfare.dev/route-economics.json":raise ValueError("assetfare_economic_guidance_invalid")
        counts=top.get("recommendation_status_counts");distribution=top.get("advisory_start_distribution")
        invalid_conditioned=False
        if isinstance(conditioned,dict):
            for threshold in conditioned.values():
                if threshold not in {50,100,250,500,1000,2500,5000,10000}:invalid_conditioned=True
        if (top.get("version")!="assetfare-route-economic-guidance-v3" or not isinstance(top.get("as_of"),str) or len(top["as_of"])!=10 or top.get("route_count")!=90 or top.get("public_active_route_count")!=42 or top.get("public_inactive_route_count")!=48 or top.get("verified_best_from_route_count")!=40 or top.get("availability_only_route_count")!=2 or top.get("currency")!="USD" or top.get("technical_quote_minimum_usd")!=1 or top.get("economic_guidance_is_non_enforcing") is not True or top.get("amount_is_never_rejected_by_economic_guidance") is not True or top.get("values_change_with_market") is not True or top.get("fresh_quote_and_caller_decision_control") is not True or top.get("update_policy")!="daily_measurement_with_three_day_activation_hysteresis" or top.get("first_use_zero_allowance_scenario") is not True or top.get("expected_output_ranking") is not True or top.get("incomplete_cost_never_promoted") is not True or top.get("tested_ceiling_usd")!=10000 or counts!={"active_price_verified":40,"active_unique_availability":2,"inactive_economics":48} or type(distribution) is not dict or sum(distribution.values())!=40 or type(conditioned) is not dict or len(conditioned)!=40 or not set(conditioned).issubset(self.ROUTES) or invalid_conditioned or policy.get("primary_direct_route_count")!=42 or policy.get("external_coverage_only_route_count")!=0 or policy.get("active_route_count")!=42 or policy.get("inactive_route_count")!=48 or not isinstance(inactive,list) or len(inactive)!=48 or len(set(inactive))!=48 or not self.ROUTES.isdisjoint(inactive) or policy.get("automatic_external_fallback_forbidden") is not True):raise ValueError("assetfare_economic_guidance_invalid")
        return dict(top)

    def _request(self, method: str, path: str, budget_deadline: float) -> Any:
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

    def forward(self) -> Any:
        budget_deadline = self._monotonic() + self.STALE_BUDGET_S
        caps = self._request("GET", "/v2/capabilities", budget_deadline)
        status = self._request("GET", "/v2/status", budget_deadline)
        self._no_sign_tree(caps)
        self._no_sign_tree(status)
        if caps.get("status") != "capped_public_agent_release" or caps.get("public_api_enabled") is not True:
            raise ValueError("assetfare_safety_boundary_failed")
        # Exactly the 42 economically active routes are execution-ready.
        if (
            caps.get("directed_conversion_routes") != self.EXPECTED_ROUTES
            or caps.get("unsigned_route_plans_ready") != self.EXPECTED_ROUTES
            or caps.get("execution_ready_routes") != self.EXECUTION_READY_ROUTES
            or caps.get("phase_b_blocked_routes") != self.PHASE_B_BLOCKED_ROUTES
        ):
            raise ValueError("assetfare_safety_boundary_failed")
        self._no_sign(caps)
        if status.get("status") != "capped_public_agent_release":
            raise ValueError("assetfare_safety_boundary_failed")
        self._no_sign(status)
        chains = caps.get("chains")
        if not isinstance(chains, list) or len(chains) != len(self.CHAINS) or set(chains) != self.CHAINS:
            raise ValueError("assetfare_safety_boundary_failed")
        endpoints = caps.get("asset_endpoints")
        if not isinstance(endpoints, list) or len(endpoints) != len(self.ENDPOINTS):
            raise ValueError("assetfare_safety_boundary_failed")
        got = set()
        for ep in endpoints:
            if not isinstance(ep, dict) or "chain" not in ep or "token" not in ep:
                raise ValueError("assetfare_safety_boundary_failed")
            got.add(str(ep["chain"]) + ":" + str(ep["token"]).upper())
        if len(got) != len(self.ENDPOINTS) or got != self.ENDPOINTS:
            raise ValueError("assetfare_safety_boundary_failed")
        source_only_eps = caps.get("source_only_asset_endpoints")
        if not isinstance(source_only_eps, list) or len(source_only_eps) != 6:
            raise ValueError("assetfare_safety_boundary_failed")
        got_source_only = set()
        for ep in source_only_eps:
            if not isinstance(ep, dict) or "chain" not in ep or "token" not in ep:
                raise ValueError("assetfare_safety_boundary_failed")
            got_source_only.add(str(ep["chain"]) + ":" + str(ep["token"]).upper())
        expected_source_only_eps = {"ethereum:USDC", "hyperevm:USDC", "optimism:USDC", "xlayer:USDC", "sei:USDC", "sonic:USDC"}
        if got_source_only != expected_source_only_eps:
            raise ValueError("assetfare_safety_boundary_failed")
        source_only_routes = caps.get("source_only_routes")
        expected_source_only_routes = {
            "optimism:USDC->base:USDC",
            "ethereum:USDC->solana:USDC",
            "hyperevm:USDC->solana:USDC",
            "xlayer:USDC->base:USDC", "xlayer:USDC->solana:USDC",
            "sei:USDC->base:USDC", "sei:USDC->solana:USDC",
            "sonic:USDC->base:USDC", "sonic:USDC->solana:USDC",
        }
        if not isinstance(source_only_routes, list) or len(source_only_routes) != 9 or set(source_only_routes) != expected_source_only_routes:
            raise ValueError("assetfare_safety_boundary_failed")
        blocked_source_only_routes = caps.get("blocked_source_only_routes")
        if not isinstance(blocked_source_only_routes, list) or blocked_source_only_routes:
            raise ValueError("assetfare_safety_boundary_failed")
        amount_policy = caps.get("amount_usd")
        minimum = amount_policy.get("minimum") if isinstance(amount_policy, dict) else None
        if (
            not isinstance(amount_policy, dict)
            or isinstance(minimum, bool)
            or not isinstance(minimum, (int, float))
            or float(minimum) != self.MIN_USD
            or amount_policy.get("maximum") is not None
            or amount_policy.get("policy") != "no_business_maximum"
        ):
            raise ValueError("assetfare_amount_policy_invalid")
        self._evaluation_guidance(caps.get("evaluation_guidance"))
        economic_guidance = self._economic_guidance(caps)
        availability_keys={"execution_implemented_routes","currently_prepare_ready_routes","temporarily_unavailable_routes","temporarily_unavailable_route_count","execution_availability"}
        present=availability_keys & set(caps)
        if present and present!=availability_keys:
            raise ValueError("assetfare_current_availability_invalid")
        current_ready=None;temporary=[];availability=None
        if present:
            current_ready=caps.get("currently_prepare_ready_routes");temporary=caps.get("temporarily_unavailable_routes");availability=caps.get("execution_availability")
            unknown_route=False
            for item in temporary:
                if item not in self.ROUTES:unknown_route=True
            if (caps.get("execution_implemented_routes")!=self.EXPECTED_ROUTES or isinstance(current_ready,bool) or not isinstance(current_ready,int) or not 0<=current_ready<=self.EXPECTED_ROUTES or not isinstance(temporary,list) or len(set(temporary))!=len(temporary) or unknown_route or caps.get("temporarily_unavailable_route_count")!=len(temporary) or current_ready!=self.EXPECTED_ROUTES-len(temporary) or not isinstance(availability,dict) or availability.get("provider")!="circle_iris" or availability.get("status") not in {"available","degraded","unknown"} or (len(temporary)==0)!=(availability.get("status")=="available") or availability.get("guarantees_future_availability") is not False):
                raise ValueError("assetfare_current_availability_invalid")
        destinations = caps.get("destination_chains")
        if not isinstance(destinations, list) or len(destinations) != 4 or set(destinations) != {"arbitrum", "base", "robinhood", "solana"}:
            raise ValueError("assetfare_safety_boundary_failed")
        return {
            "status": caps["status"],
            "chains": sorted(self.CHAINS),
            "asset_endpoints": sorted(self.ENDPOINTS),
            "directed_conversion_routes": self.EXPECTED_ROUTES,
            "unsigned_route_plans_ready": self.EXPECTED_ROUTES,
            "execution_ready_routes": self.EXECUTION_READY_ROUTES,
            "execution_implemented_routes": self.EXECUTION_READY_ROUTES,
            "currently_prepare_ready_routes": current_ready,
            "temporarily_unavailable_routes": temporary,
            "execution_availability": availability,
            "phase_b_blocked_routes": self.PHASE_B_BLOCKED_ROUTES,
            "source_only_asset_endpoints": sorted(expected_source_only_eps),
            "source_only_routes": sorted(expected_source_only_routes),
            "blocked_source_only_routes": [],
            "destination_chains": sorted(destinations),
            "amount_usd": {
                "minimum": self.MIN_USD,
                "maximum": None,
                "policy": "no_business_maximum",
            },
            "evaluation_guidance": dict(self.PUBLIC_EVALUATION_GUIDANCE),
            "economic_guidance": economic_guidance,
            "economic_guidance_url": "https://assetfare.dev/route-economics.json",
            # Scoped to what this tool exercises, not a claim about all of AssetFare.
            "tool_scope_quote_only": True,
            "server_signs_or_submits": False,
        }
