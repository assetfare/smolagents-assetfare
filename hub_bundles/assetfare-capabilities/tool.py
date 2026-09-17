from typing import Any, Optional
from smolagents.tools import Tool
import urllib
import contextlib
import time
import json
import requests

class AssetFareCapabilitiesTool(Tool):
    name = "assetfare_capabilities"
    description = "Read-only capabilities probe for the AssetFare v2 API (fixed origin https://api.assetfare.dev). This tool's entire scope is to fetch and validate the public capability/status surface and return it; it is not the AssetFare service and exposes none of its other endpoints. It reports the supported chains (solana, base, arbitrum, robinhood), the 9 (chain, token) asset endpoints, the count of directed conversion routes (72) and unsigned route plans ready, and the USD amount bounds (1 to 1000). It validates that the surface it reads is a quote-only, non-custodial public agent release whose server never signs or submits for these endpoints, failing closed otherwise; this is a property of what this tool exercises, not a blanket claim about all of AssetFare. Takes no inputs. Use it to check which cross-chain corridors can be quoted before requesting a quote. This tool does NOT execute, bridge, swap, sign or move funds."
    inputs = {}
    output_type = "object"
    ALLOWED_ORIGIN = "https://api.assetfare.dev"
    SOCKET_TIMEOUT_S = 45.0
    STALE_BUDGET_S = 45.0
    MAX_BYTES = 1048576
    EXPECTED_ROUTES = 72
    MIN_USD = 1.0
    MAX_USD = 1000.0
    CHAINS = {'arbitrum', 'solana', 'base', 'robinhood'}
    ENDPOINTS = {'base:USDC', 'arbitrum:ETH', 'solana:USDC', 'robinhood:USDG', 'arbitrum:USDC', 'solana:SOL', 'robinhood:ETH', 'solana:USDG', 'base:ETH'}

    def __init__(
        self,
        base_url: str = "https://api.assetfare.dev",
        session: Optional[Any] = None,
        monotonic: Optional[Any] = None,
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
        # Force trust_env=False on an injected session too, so ambient proxy /
        # credential environment variables are never honoured for this client.
        if session is not None:
            session.trust_env = False
        self._session = session
        self._monotonic = monotonic or time.monotonic

    def _no_sign(self, node: Any) -> None:
        if node.get("server_signing") is not False or node.get("server_submission") is not False:
            raise ValueError("assetfare_safety_boundary_failed")

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
        if caps.get("status") != "capped_public_agent_release" or caps.get("public_api_enabled") is not True:
            raise ValueError("assetfare_safety_boundary_failed")
        if (
            caps.get("directed_conversion_routes") != self.EXPECTED_ROUTES
            or caps.get("unsigned_route_plans_ready") != self.EXPECTED_ROUTES
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
        return {
            "status": caps["status"],
            "chains": sorted(self.CHAINS),
            "asset_endpoints": sorted(self.ENDPOINTS),
            "directed_conversion_routes": self.EXPECTED_ROUTES,
            "unsigned_route_plans_ready": self.EXPECTED_ROUTES,
            "amount_usd_min": self.MIN_USD,
            "amount_usd_max": self.MAX_USD,
            # Scoped to what this tool exercises, not a claim about all of AssetFare.
            "tool_scope_quote_only": True,
            "server_signs_or_submits": False,
        }
