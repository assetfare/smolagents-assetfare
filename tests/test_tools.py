"""Offline mock tests for the AssetFare smolagents tools.

No network. A fake session returns queued fake responses; injected clocks make
the freshness and stale-budget checks deterministic. Also asserts that both
tools pass smolagents' own ``validate_tool_attributes`` (via ``to_dict``) and
round-trip through ``from_code`` -- i.e. they are Hub-pushable and Hub-loadable.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assetfare_capabilities_tool import AssetFareCapabilitiesTool
from assetfare_quote_tool import AssetFareQuoteTool

UTC = timezone.utc
FIXED_NOW = datetime(2026, 9, 17, 0, 0, 10, tzinfo=UTC)
AS_OF = "2026-09-17T00:00:05Z"  # 5s before FIXED_NOW

EVALUATION_GUIDANCE = {
    "schema_version": 1,
    "route_minimum_usd": 1,
    "reachability_smoke_usd": 1,
    "reachability_smoke_scope": "connectivity_only_not_economic_evaluation",
    "native_usdc_economic_evaluation_start_usd": 50,
    "representative_economic_evaluation_usd": 1000,
    "sol_input_representative_evaluation_usd": 1000,
    "sol_input_caveat": (
        "SOL-input routes add a source swap, so compare their full fee-inclusive route economics separately."
    ),
    "evidence_as_of": "2026-09-23",
    "evidence_scope": "Dated Solana native USDC to Base native USDC measurements at USD 50, 250, and 1000.",
    "not_a_minimum": True,
    "not_guaranteed_best": True,
    "always_compare_fresh_at_intended_amount": True,
}


def fixed_now() -> datetime:
    return FIXED_NOW


class _Clock:
    """Monotonic clock returning a preset sequence, last value repeating."""

    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def __call__(self) -> float:
        v = self._values[min(self._i, len(self._values) - 1)]
        self._i += 1
        return v


class _Resp:
    def __init__(self, payload, status=200, content_type="application/json", headers=None, chunks=None, iter_exc=None):
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self._chunks = chunks if chunks is not None else [body]
        self._iter_exc = iter_exc  # raised during iteration to simulate a hostile stream
        self.headers = {"content-type": content_type}
        if headers:
            self.headers.update(headers)
        self.closed = False

    def iter_content(self, chunk_size=65536):
        if self._iter_exc is not None:
            raise self._iter_exc
        for c in self._chunks:
            yield c

    def close(self):
        self.closed = True


class _Session:
    """Fake requests.Session yielding queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.trust_env = True
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ---- fixtures -------------------------------------------------------------

def caps_payload():
    return {
        "status": "capped_public_agent_release",
        "public_api_enabled": True,
        "directed_conversion_routes": 76,
        "unsigned_route_plans_ready": 76,
        "execution_ready_routes": 76,
        "execution_implemented_routes": 76,
        "currently_prepare_ready_routes": 76,
        "temporarily_unavailable_routes": [],
        "temporarily_unavailable_route_count": 0,
        "execution_availability": {"status":"available","provider":"circle_iris","provider_dependent_routes":50,"recent_fee_snapshot_usable":True,"guarantees_future_availability":False},
        "phase_b_blocked_routes": 0,
        "blocked_source_only_routes": [],
        "server_signing": False,
        "server_submission": False,
        "chains": ["solana", "base", "arbitrum", "robinhood", "polygon", "optimism"],
        "asset_endpoints": [
            {"chain": "solana", "token": "SOL"},
            {"chain": "solana", "token": "USDC"},
            {"chain": "solana", "token": "USDG"},
            {"chain": "base", "token": "ETH"},
            {"chain": "base", "token": "USDC"},
            {"chain": "arbitrum", "token": "ETH"},
            {"chain": "arbitrum", "token": "USDC"},
            {"chain": "robinhood", "token": "ETH"},
            {"chain": "robinhood", "token": "USDG"},
            {"chain": "polygon", "token": "USDC"},
            {"chain": "optimism", "token": "USDC"},
        ],
        "source_only_asset_endpoints": [
            {"chain": "polygon", "token": "USDC"},
            {"chain": "optimism", "token": "USDC"},
        ],
        "source_only_routes": [
            "polygon:USDC->base:USDC",
            "polygon:USDC->arbitrum:USDC",
            "optimism:USDC->base:USDC",
            "optimism:USDC->arbitrum:USDC",
        ],
        "destination_chains": ["arbitrum", "base", "robinhood", "solana"],
        "amount_usd": {"minimum": 1, "maximum": None, "policy": "no_business_maximum"},
        "evaluation_guidance": dict(EVALUATION_GUIDANCE),
    }


def status_payload():
    return {
        "status": "capped_public_agent_release",
        "server_signing": False,
        "server_submission": False,
    }


def quote_payload():
    return {
        "status": "capped_public_agent_release",
        "quote_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        "ttl_seconds": 60,
        "as_of": AS_OF,
        "intent": {
            "from": "solana:SOL",
            "to": "base:ETH",
            "amount_usd": 250.0,
            "estimated_input_base": 1500000000,
        },
        "route": {
            "route": "solana:SOL->base:ETH",
            "steps": [{"kind": "swap"}, {"kind": "bridge"}],
            "quote_latency_ms": 42,
            "server_signing": False,
            "server_submission": False,
        },
        "offer": {
            "expected_receive_amount": 0.0721,
            "estimated_min_receive_amount": 0.0715,
            "expected_receive_usd": 249.1,
            "estimated_min_receive_usd": 247.0,
            "output_symbol": "ETH",
            "assetfare_fee_bps": 1,
            "fee_modeled_bps": 1,
            "fee_collectible_now": True,
            "fee_collection_steps": [1],
            "fee_collection": "only_on_eligible_successful_executor_step",
            "estimated_time_seconds": 45,
        },
        "risk": {
            "non_atomic": True,
            "fresh_quote_required_each_step": True,
            "server_signing": False,
            "server_submission": False,
        },
        "execution": {
            "supported": True,
            "first_unsigned_action_supported": True,
            "future_actions_require_verified_receipts": True,
        },
        "caller_action_plan_handoff": executable_handoff(),
        "caller_action_plan_handoff_v2": executable_handoff_v2(),
        "handoff_schema_version": 2,
    }


def with_cost_summary(quote):
    amount=float(quote["intent"]["amount_usd"]);expected=float(quote["offer"]["expected_receive_usd"]);minimum=float(quote["offer"]["estimated_min_receive_usd"])
    ec=max(0.0,amount-expected);mc=max(0.0,amount-minimum)
    small=mc/amount>=.01
    quote["cost_summary"]={"scope":"token_path_only_network_gas_excluded","input_value_usd":amount,"expected_receive_value_usd":expected,"minimum_receive_value_usd":minimum,"expected_total_cost_usd":ec,"maximum_total_cost_usd":mc,"expected_total_cost_percent":ec/amount*100,"maximum_total_cost_percent":mc/amount*100,"assetfare_service_fee":{"bps":1,"estimated_usd":min(amount/10_000,5.0),"included_in_receive_amount":True,"note":"service fee only"},"provider_fee_components":[],"unpriced_costs":["source_chain_network_fee"],"rankable_all_in":False,"small_amount_warning":small,"warning":"fixed cost" if small else None}
    quote["eta"]={"estimated_time_seconds":quote["offer"]["estimated_time_seconds"],"estimated_time_range_seconds":[8,45],"complete_route_estimate":True,"sources":[],"note":"estimate"}
    return quote


def executable_handoff():
    return {
        "kind": "caller_operated_rest_prepare",
        "url": "https://api.assetfare.dev/v2/prepare",
        "method": "POST",
        "available": True,
        "requires_explicit_caller_approval": True,
        "requires_public_wallet_addresses": True,
        "request_fields": [
            "caller_approved", "from_chain", "from_token", "to_chain", "to_token",
            "amount_usd", "wallets", "event_signer_public",
        ],
        "assetfare_server_signing": False,
        "assetfare_server_submission": False,
        "caller_must_verify_sign_and_submit": True,
        "requires_fresh_requote": True,
        "automatic_prepare_call_forbidden": True,
        "options": [
            {
                "kind": "one_shot_first_unsigned_bundle",
                "method": "POST",
                "url": "https://api.assetfare.dev/v2/prepare",
                "requires_explicit_caller_approval": True,
                "requires_public_wallet_addresses": True,
                "assetfare_never_signs_submits_or_auto_calls": True,
            },
            {
                "kind": "caller_approved_full_workflow_session",
                "method": "POST",
                "url": "https://api.assetfare.dev/v2/session",
                "requires_explicit_caller_approval": True,
                "requires_public_wallet_addresses": True,
                "assetfare_never_signs_submits_or_auto_calls": True,
                "lifecycle_urls": {
                    "create": {"url": "https://api.assetfare.dev/v2/session"},
                    "read": {"url": "https://api.assetfare.dev/v2/session/{session_id}"},
                    "observe_source": {"url": "https://api.assetfare.dev/v2/session/{session_id}/observe-source"},
                    "observe_output": {"url": "https://api.assetfare.dev/v2/session/{session_id}/observe-output"},
                    "refresh_action": {"url": "https://api.assetfare.dev/v2/session/{session_id}/refresh-action"},
                },
            },
        ],
        "note": "Upstream guidance: caller-operated; AssetFare never signs or submits.",
    }


PREPARE_URL = "https://api.assetfare.dev/v2/prepare"
SESSION_URL = "https://api.assetfare.dev/v2/session"


def executable_handoff_v2():
    return {
        "kind": "caller_operated_rest_prepare", "url": PREPARE_URL, "method": "POST",
        "requires_explicit_caller_approval": True, "requires_public_wallet_addresses": True,
        "request_fields": ["caller_approved", "from_chain", "from_token", "to_chain", "to_token", "amount_usd", "wallets", "event_signer_public"],
        "assetfare_server_signing": False, "assetfare_server_submission": False, "caller_must_verify_sign_and_submit": True,
        "requires_fresh_requote": True, "automatic_prepare_call_forbidden": True,
        "schema_version": 2, "selection": "choose_exactly_one", "mutually_exclusive": True, "do_not_call_both": True,
        "selection_before_signing": True, "once_any_action_submitted_do_not_start_other_mode": True, "enforcement": "advisory_caller_side",
        "options": [
            {"kind": "one_shot_first_unsigned_bundle", "method": "POST", "url": PREPARE_URL, "requires_explicit_caller_approval": True, "requires_public_wallet_addresses": True, "assetfare_never_signs_submits_or_auto_calls": True, "preview_or_manual_first_action_only": True, "not_a_session": True, "do_not_start_session_after_submission": True, "note": "one-shot"},
            {"kind": "caller_approved_full_workflow_session", "method": "POST", "url": SESSION_URL, "requires_explicit_caller_approval": True, "requires_public_wallet_addresses": True, "assetfare_never_signs_submits_or_auto_calls": True, "recommended_for_multistep": True, "note": "session", "lifecycle_urls": {
                "create": {"method": "POST", "url": SESSION_URL},
                "read": {"method": "GET", "url": SESSION_URL + "/{session_id}"},
                "observe_source": {"method": "POST", "url": SESSION_URL + "/{session_id}/observe-source"},
                "observe_output": {"method": "POST", "url": SESSION_URL + "/{session_id}/observe-output"},
                "refresh_action": {"method": "POST", "url": SESSION_URL + "/{session_id}/refresh-action"},
            }},
        ],
        "note": "Machine-readable v2.", "available": True,
    }


def source_only_quote_payload(from_ep, to_ep, route, fee_bps, fee_modeled, steps):
    p = quote_payload()
    p["intent"].update(**{"from": from_ep_str(from_ep), "to": from_ep_str(to_ep), "amount_usd": 10.0})
    p["route"]["route"] = route
    p["offer"]["output_symbol"] = to_ep[1]
    p["offer"]["assetfare_fee_bps"] = fee_bps
    p["offer"]["fee_modeled_bps"] = fee_modeled
    p["offer"]["fee_collectible_now"] = fee_bps == 1
    p["offer"]["fee_collection_steps"] = steps
    p["execution"] = {
        "supported": True,
        "first_unsigned_action_supported": True,
        "future_actions_require_verified_receipts": True,
        "blocker": None,
    }
    p["caller_action_plan_handoff"] = executable_handoff()
    return p


def from_ep_str(ep):
    return ep[0] + ":" + ep[1]


def caps_tool(session, monotonic=None):
    return AssetFareCapabilitiesTool(session=session, monotonic=monotonic or _Clock([0.0]))


def quote_tool(session, monotonic=None, utcnow=fixed_now):
    return AssetFareQuoteTool(session=session, monotonic=monotonic or _Clock([0.0]), utcnow=utcnow)


def quote_session(payload=None):
    return _Session([_Resp(payload if payload is not None else quote_payload())])


# ---- Hub-contract (validate/serialise/round-trip) -------------------------

@pytest.mark.parametrize("Cls", [AssetFareCapabilitiesTool, AssetFareQuoteTool])
def test_tool_validates_and_serialises(Cls):
    d = Cls().to_dict()
    assert d["name"] in ("assetfare_capabilities", "assetfare_quote")
    assert "requests" in d["requirements"] and "smolagents" in d["requirements"]
    rebuilt = Cls.from_code(d["code"])
    assert type(rebuilt).__name__ == Cls.__name__


@pytest.mark.parametrize("Cls", [AssetFareCapabilitiesTool, AssetFareQuoteTool])
def test_output_type_object(Cls):
    assert Cls.output_type == "object"


def test_session_trust_env_disabled_on_lazy_create():
    t = AssetFareCapabilitiesTool()
    # lazily created only on first request; force it via a fake by leaving None
    assert t._session is None


# ---- origin -------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "http://api.assetfare.dev",
        "https://api.assetfare.dev.evil.com",
        "https://api.assetfare.dev:8443",
        "https://user:pw@api.assetfare.dev",
        "https://api.assetfare.dev/v2",
        "https://api.assetfare.dev/?x=1",
        "https://evil.com",
        "",
    ],
)
def test_origin_rejected(bad):
    with pytest.raises(ValueError, match="assetfare_base_url_rejected"):
        AssetFareQuoteTool(base_url=bad)
    with pytest.raises(ValueError, match="assetfare_base_url_rejected"):
        AssetFareCapabilitiesTool(base_url=bad)


def test_origin_accepts_canonical_and_trailing_slash():
    assert AssetFareQuoteTool(base_url="https://api.assetfare.dev").base_url == "https://api.assetfare.dev"
    assert AssetFareQuoteTool(base_url="https://api.assetfare.dev/").base_url == "https://api.assetfare.dev"


# ---- capabilities -------------------------------------------------------

def test_capabilities_happy():
    s = _Session([_Resp(caps_payload()), _Resp(status_payload())])
    out = caps_tool(s).forward()
    assert out["directed_conversion_routes"] == 76
    assert out["unsigned_route_plans_ready"] == 76
    assert out["execution_ready_routes"] == 76
    assert out["currently_prepare_ready_routes"] == 76
    assert out["phase_b_blocked_routes"] == 0
    assert out["blocked_source_only_routes"] == []
    assert out["chains"] == ["arbitrum", "base", "optimism", "polygon", "robinhood", "solana"]
    assert len(out["asset_endpoints"]) == 11
    assert out["source_only_asset_endpoints"] == ["optimism:USDC", "polygon:USDC"]
    assert sorted(out["source_only_routes"]) == [
        "optimism:USDC->arbitrum:USDC",
        "optimism:USDC->base:USDC",
        "polygon:USDC->arbitrum:USDC",
        "polygon:USDC->base:USDC",
    ]
    assert out["destination_chains"] == ["arbitrum", "base", "robinhood", "solana"]
    assert out["tool_scope_quote_only"] is True
    assert out["server_signs_or_submits"] is False
    assert out["amount_usd"] == {
        "minimum": 1.0,
        "maximum": None,
        "policy": "no_business_maximum",
    }
    assert out["evaluation_guidance"] == EVALUATION_GUIDANCE
    assert s.calls[0][1] == "https://api.assetfare.dev/v2/capabilities"
    assert s.calls[1][1] == "https://api.assetfare.dev/v2/status"


@pytest.mark.parametrize(
    "amount_policy",
    [
        None,
        {"minimum": 0, "maximum": None, "policy": "no_business_maximum"},
        {"minimum": 1, "maximum": 1000, "policy": "no_business_maximum"},
        {"minimum": 1, "maximum": None, "policy": "capped"},
    ],
)
def test_capabilities_rejects_invalid_amount_policy(amount_policy):
    payload = caps_payload()
    payload["amount_usd"] = amount_policy
    with pytest.raises(ValueError, match="assetfare_amount_policy_invalid"):
        caps_tool(_Session([_Resp(payload), _Resp(status_payload())])).forward()


@pytest.mark.parametrize(
    "mut",
    [
        lambda c: c.pop("evaluation_guidance"),
        lambda c: c["evaluation_guidance"].update(route_minimum_usd=True),
        lambda c: c["evaluation_guidance"].update(evidence_as_of="2026-09-24"),
        lambda c: c["evaluation_guidance"].update(extra=True),
    ],
)
def test_capabilities_evaluation_guidance_must_match_core_exactly(mut):
    payload = caps_payload()
    mut(payload)
    with pytest.raises(ValueError, match="assetfare_evaluation_guidance_invalid"):
        caps_tool(_Session([_Resp(payload), _Resp(status_payload())])).forward()


def test_capabilities_rejects_public_api_disabled():
    p = caps_payload()
    p["public_api_enabled"] = False
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


def test_capabilities_rejects_partial_current_availability():
    p=caps_payload();p.pop("execution_availability")
    with pytest.raises(ValueError,match="assetfare_current_availability_invalid"):
        caps_tool(_Session([_Resp(p),_Resp(status_payload())])).forward()


@pytest.mark.parametrize("mut",[
    lambda c:c.update(currently_prepare_ready_routes=75,temporarily_unavailable_routes=["evil:USDC->base:USDC"],temporarily_unavailable_route_count=1,execution_availability={"status":"degraded","provider":"circle_iris","guarantees_future_availability":False}),
    lambda c:c.update(execution_availability={"status":"degraded","provider":"circle_iris","guarantees_future_availability":False}),
])
def test_capabilities_live_availability_semantics_fail_closed(mut):
    p=caps_payload();mut(p)
    with pytest.raises(ValueError):caps_tool(_Session([_Resp(p),_Resp(status_payload())])).forward()


def test_capabilities_rejects_server_signing_true():
    p = caps_payload()
    p["server_signing"] = True
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


def test_capabilities_rejects_wrong_route_count():
    p = caps_payload()
    p["directed_conversion_routes"] = 71
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


def test_capabilities_rejects_unsigned_mismatch():
    p = caps_payload()
    p["unsigned_route_plans_ready"] = 70
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


def test_capabilities_rejects_chain_substitution():
    p = caps_payload()
    p["chains"] = ["solana", "base", "arbitrum", "polygon"]
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


def test_capabilities_rejects_duplicate_chain_padding():
    p = caps_payload()
    p["chains"] = ["solana", "base", "arbitrum", "arbitrum"]
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


def test_capabilities_rejects_endpoint_substitution():
    p = caps_payload()
    p["asset_endpoints"][0] = {"chain": "solana", "token": "BONK"}
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


@pytest.mark.parametrize(
    "mut",
    [
        lambda c: c.update(source_only_asset_endpoints=[]),
        lambda c: c.update(source_only_asset_endpoints=[{"chain": "polygon", "token": "ETH"}, {"chain": "optimism", "token": "USDC"}]),
        lambda c: c.update(source_only_asset_endpoints=[{"chain": "arbitrum", "token": "USDC"}, {"chain": "optimism", "token": "USDC"}]),
        lambda c: c.update(source_only_routes=["polygon:USDC->base:ETH", "polygon:USDC->arbitrum:USDC", "optimism:USDC->base:USDC", "optimism:USDC->arbitrum:USDC"]),
        lambda c: c.update(source_only_routes=["polygon:USDC->base:USDC", "polygon:USDC->arbitrum:USDC"]),
        lambda c: c.update(destination_chains=["arbitrum", "base", "polygon", "solana"]),
    ],
)
def test_capabilities_rejects_source_only_semantic_mismatch(mut):
    p = caps_payload()
    mut(p)
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(_Session([_Resp(p), _Resp(status_payload())])).forward()


@pytest.mark.parametrize("key", ["server_signing", "server_submission"])
def test_capabilities_rejects_nested_sign_or_submit_claim(key):
    p = caps_payload()
    p["asset_endpoints"][0][key] = True
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(_Session([_Resp(p), _Resp(status_payload())])).forward()


def test_capabilities_rejects_status_wrong():
    p = caps_payload()
    p["status"] = "open_public"
    s = _Session([_Resp(p), _Resp(status_payload())])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        caps_tool(s).forward()


# ---- quote happy --------------------------------------------------------

def test_quote_happy():
    out = quote_tool(quote_session(with_cost_summary(quote_payload()))).forward("solana", "sol", "base", "eth", 250)
    assert out["from"] == "solana:SOL"
    assert out["to"] == "base:ETH"
    assert out["output_symbol"] == "ETH"
    assert out["amount_usd"] == 250.0
    assert out["assetfare_fee_bps"] == 1
    assert out["fee_modeled_bps"] == 1
    assert out["fee_collectible_now"] is True
    assert out["non_atomic"] is True
    assert out["execution_supported"] is True
    assert out["source_only"] is False
    assert out["evaluation_guidance"] == EVALUATION_GUIDANCE
    assert out["server_signs_or_submits"] is False
    assert out["cost_summary"]["maximum_total_cost_usd"] == pytest.approx(3.0)
    assert out["eta"]["estimated_time_seconds"] == 45
    handoff = out["caller_action_plan_handoff"]
    assert handoff["url"] == "https://api.assetfare.dev/v2/prepare"
    assert handoff["available"] is True
    assert handoff["requires_explicit_caller_approval"] is True
    assert handoff["requires_fresh_requote"] is True
    assert handoff["automatic_prepare_call_forbidden"] is True
    assert len(handoff["options"]) == 2
    assert handoff["assetfare_server_signing"] is False
    assert handoff["assetfare_server_submission"] is False


@pytest.mark.parametrize("mut",[
    lambda q:q["cost_summary"].__setitem__("maximum_total_cost_usd",99),
    lambda q:q["cost_summary"]["assetfare_service_fee"].__setitem__("estimated_usd",1),
    lambda q:q["cost_summary"].__setitem__("rankable_all_in",True),
    lambda q:q["eta"].__setitem__("estimated_time_seconds",99),
    lambda q:q["cost_summary"].__setitem__("provider_fee_components",[{"expected_usd":1,"maximum_usd":1}]),
    lambda q:q["cost_summary"].__setitem__("provider_fee_components",[{"expected_usd":.02,"maximum_usd":.01}]),
    lambda q:q["cost_summary"].__setitem__("unpriced_costs",[]),
    lambda q:(q["cost_summary"].__setitem__("small_amount_warning",False),q["cost_summary"].__setitem__("warning",None)),
    lambda q:q["eta"].__setitem__("estimated_time_range_seconds",[50,45]),
    lambda q:q["eta"].__setitem__("complete_route_estimate",False),
    lambda q:q.__setitem__("ttl_seconds",61),
])
def test_quote_cost_and_eta_binding_hostiles(mut):
    payload=with_cost_summary(quote_payload());mut(payload)
    with pytest.raises(ValueError):quote_tool(quote_session(payload)).forward("solana","SOL","base","ETH",250)


def test_rollback_core_without_cost_derives_honest_total():
    out=quote_tool(quote_session(quote_payload())).forward("solana","SOL","base","ETH",250)
    assert out["cost_summary"]["scope"]=="token_path_only_network_gas_excluded"
    assert "provider_fee_breakdown_unavailable_legacy_core" in out["cost_summary"]["unpriced_costs"]


def test_quote_accepts_sub_micro_usd_rounding_alignment():
    payload=with_cost_summary(quote_payload());payload["offer"]["expected_receive_usd"]=249.1234567;payload["cost_summary"]["expected_receive_value_usd"]=249.123457;payload["cost_summary"]["expected_total_cost_usd"]=.876543;payload["cost_summary"]["expected_total_cost_percent"]=.3506172
    out=quote_tool(quote_session(payload)).forward("solana","SOL","base","ETH",250)
    assert out["cost_summary"]["expected_receive_value_usd"]==249.123457


def test_polygon_source_quote_happy():
    # Polygon is directional source-only and usable only while live availability permits.
    payload = source_only_quote_payload(
        ("polygon", "USDC"), ("arbitrum", "USDC"), "polygon:USDC->arbitrum:USDC", 1, 1, [1]
    )
    out = quote_tool(quote_session(payload)).forward("polygon", "USDC", "arbitrum", "USDC", 10)
    assert out["from"] == "polygon:USDC" and out["to"] == "arbitrum:USDC"
    assert out["source_only"] is True
    assert out["execution_supported"] is True
    assert out["execution_blocker"] is None
    assert out["assetfare_fee_bps"] == 1
    assert out["fee_modeled_bps"] == 1
    assert out["fee_collectible_now"] is True
    h = out["caller_action_plan_handoff"]
    assert h["available"] is True
    assert h["url"] == "https://api.assetfare.dev/v2/prepare"
    assert len(h["options"]) == 2


def test_polygon_destination_and_wrong_corridor_rejected():
    with pytest.raises(ValueError, match="assetfare_destination_endpoint_invalid"):
        quote_tool(quote_session()).forward("base", "USDC", "polygon", "USDC", 10)
    with pytest.raises(ValueError, match="assetfare_source_endpoint_invalid"):
        quote_tool(quote_session()).forward("polygon", "USDC", "solana", "USDC", 10)


def test_optimism_source_quote_happy():
    # Optimism is directional source-only and usable only while live availability permits.
    payload = source_only_quote_payload(
        ("optimism", "USDC"), ("base", "USDC"), "optimism:USDC->base:USDC", 1, 1, [1]
    )
    out = quote_tool(quote_session(payload)).forward("optimism", "USDC", "base", "USDC", 10)
    assert out["from"] == "optimism:USDC" and out["to"] == "base:USDC"
    assert out["source_only"] is True
    assert out["execution_supported"] is True
    assert out["assetfare_fee_bps"] == 1
    assert out["fee_collectible_now"] is True
    assert out["assetfare_fee_conditional"] is True


def test_optimism_destination_and_wrong_corridor_rejected():
    with pytest.raises(ValueError, match="assetfare_destination_endpoint_invalid"):
        quote_tool(quote_session()).forward("base", "USDC", "optimism", "USDC", 10)
    with pytest.raises(ValueError, match="assetfare_source_endpoint_invalid"):
        quote_tool(quote_session()).forward("optimism", "USDC", "solana", "USDC", 10)


# ---- caller_action_plan_handoff FAIL-CLOSED passthrough (no local fallback) ----

def test_quote_handoff_surfaced_from_upstream():
    # The upstream dual-option handoff is passed through verbatim (validated).
    out = quote_tool(quote_session()).forward("solana", "SOL", "base", "ETH", 250)
    h = out["caller_action_plan_handoff"]
    assert h["note"] == "Upstream guidance: caller-operated; AssetFare never signs or submits."
    assert h["kind"] == "caller_operated_rest_prepare"
    assert h["url"] == "https://api.assetfare.dev/v2/prepare"
    assert h["available"] is True
    assert h["requires_fresh_requote"] is True
    assert h["automatic_prepare_call_forbidden"] is True
    assert h["assetfare_server_signing"] is False and h["assetfare_server_submission"] is False
    assert h["caller_must_verify_sign_and_submit"] is True
    assert h["request_fields"][0] == "caller_approved"
    assert "event_signer_public" in h["request_fields"]
    kinds = [o["kind"] for o in h["options"]]
    assert kinds == ["one_shot_first_unsigned_bundle", "caller_approved_full_workflow_session"]
    # v1 stays old-exact: NO machine fields on the v1 handoff.
    assert not ({"selection", "mutually_exclusive", "do_not_call_both", "enforcement", "schema_version"} & set(h))


def test_quote_surfaces_v2_sibling():
    out = quote_tool(quote_session()).forward("solana", "SOL", "base", "ETH", 250)
    v2 = out["caller_action_plan_handoff_v2"]
    assert out["handoff_schema_version"] == 2 and v2["schema_version"] == 2
    assert v2["selection"] == "choose_exactly_one" and v2["enforcement"] == "advisory_caller_side"
    assert v2["options"][0]["not_a_session"] is True and v2["options"][1]["recommended_for_multistep"] is True


def test_rollback_core_no_v2_still_quotes():
    p = _mutated(lambda q: (q.pop("caller_action_plan_handoff_v2"), q.pop("handoff_schema_version")))
    out = quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)
    assert out["caller_action_plan_handoff_v2"] is None and out["handoff_schema_version"] is None
    assert out["caller_action_plan_handoff"]["available"] is True


@pytest.mark.parametrize(
    "mut",
    [
        lambda q: q.pop("caller_action_plan_handoff_v2"),
        lambda q: q.pop("handoff_schema_version"),
        lambda q: q.__setitem__("caller_action_plan_handoff_v2", None),
        lambda q: q.__setitem__("handoff_schema_version", 3),
        lambda q: q["caller_action_plan_handoff_v2"].__setitem__("schema_version", 1),
        lambda q: q["caller_action_plan_handoff_v2"].pop("do_not_call_both"),
        lambda q: q["caller_action_plan_handoff_v2"].__setitem__("enforcement", "server_enforced"),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][0].pop("note"),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][0].pop("not_a_session"),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][0].__setitem__("recommended_for_multistep", True),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][1]["lifecycle_urls"].pop("create"),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][1]["lifecycle_urls"]["create"].__setitem__("url", "https://api.assetfare.dev/v2/evil"),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][1]["lifecycle_urls"]["create"].pop("method"),
        lambda q: q["caller_action_plan_handoff_v2"]["options"][1]["lifecycle_urls"].__setitem__("extra", {"method": "POST", "url": SESSION_URL}),
        lambda q: (q.__setitem__("caller_action_plan_handoff_v2", None), q.pop("handoff_schema_version")),
        lambda q: q.__setitem__("caller_action_plan_handoff_v2", []),
        lambda q: q["caller_action_plan_handoff_v2"].__setitem__("blocker", None),
    ],
)
def test_quote_v2_sibling_malformed_rejected(mut):
    p = _mutated(mut)
    with pytest.raises(ValueError):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


@pytest.mark.parametrize(
    "mut,match",
    [
        (lambda q: q.pop("caller_action_plan_handoff"), "assetfare_handoff_missing"),
        (lambda q: q.__setitem__("caller_action_plan_handoff", None), "assetfare_handoff_missing"),
        (lambda q: q.__setitem__("caller_action_plan_handoff", []), "assetfare_handoff_missing"),
    ],
)
def test_quote_handoff_fail_closed_no_local_fallback(mut, match):
    # There is NO local fallback: a missing/null/array handoff is a real contract
    # regression and is rejected, never synthesized.
    p = _mutated(mut)
    with pytest.raises(ValueError, match=match):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_extra_field():
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("surprise", "x"))
    with pytest.raises(ValueError, match="assetfare_handoff_extra_field"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_private_key_field():
    # a private_key key anywhere at the handoff top level is not an allowed key ->
    # rejected as an extra field (the handoff never carries secret material).
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("private_key", "abc"))
    with pytest.raises(ValueError, match="assetfare_handoff_extra_field"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_missing_option():
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("options", q["caller_action_plan_handoff"]["options"][:1]))
    with pytest.raises(ValueError, match="assetfare_handoff_options_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_broken_lifecycle_url():
    def mut(q):
        q["caller_action_plan_handoff"]["options"][1]["lifecycle_urls"]["observe_source"] = {"url": "https://evil/x"}
    p = _mutated(mut)
    with pytest.raises(ValueError, match="assetfare_handoff_session_lifecycle_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_server_signing_claim():
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("assetfare_server_signing", True))
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


@pytest.mark.parametrize(
    "fields",
    [
        ["from_chain"],
        [
            "caller_approved", "from_chain", "from_token", "to_chain", "to_token", "amount_usd",
            "wallets", "event_signer_public", "private_key",
        ],
        # 7-field (missing caller_approved) is now noncanonical
        [
            "from_chain", "from_token", "to_chain", "to_token",
            "amount_usd", "wallets", "event_signer_public",
        ],
        # reordered
        [
            "from_chain", "caller_approved", "from_token", "to_chain", "to_token",
            "amount_usd", "wallets", "event_signer_public",
        ],
    ],
)
def test_quote_handoff_rejects_noncanonical_request_fields(fields):
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("request_fields", fields))
    with pytest.raises(ValueError, match="assetfare_handoff_request_fields_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_wrong_url():
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("url", "https://api.assetfare.dev/v2/execute"))
    with pytest.raises(ValueError, match="assetfare_handoff_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_missing_caller_approval_flag():
    p = _mutated(lambda q: q["caller_action_plan_handoff"].__setitem__("requires_explicit_caller_approval", False))
    with pytest.raises(ValueError, match="assetfare_handoff_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_handoff_rejects_missing_requires_fresh_requote():
    p = _mutated(lambda q: q["caller_action_plan_handoff"].pop("requires_fresh_requote"))
    with pytest.raises(ValueError, match="assetfare_handoff_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


# ---- fee EXACTLY 1bp (conditional, not an unconditional flat fee) ----

def test_quote_fee_eligibility_surfaced():
    out = quote_tool(quote_session()).forward("solana", "SOL", "base", "ETH", 250)
    assert out["assetfare_fee_bps"] == 1
    assert out["fee_collection_steps"] == [1]
    assert out["fee_modeled_bps"] == 1
    assert out["fee_collectible_now"] is True
    assert out["assetfare_fee_conditional"] is True
    assert out["fee_collection"] == "only_on_eligible_successful_executor_step"
    assert "eligible successful atomic action" in out["fee_note"]


def test_quote_zero_fee_rejected():
    def mut(q):
        q["offer"]["assetfare_fee_bps"] = 0
        q["offer"]["fee_modeled_bps"] = 0
        q["offer"]["fee_collectible_now"] = False
        q["offer"]["fee_collection_steps"] = []
    p = _mutated(mut)
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


@pytest.mark.parametrize("fee_bps", [2, 8, -1, 5])
def test_quote_rejects_fee_out_of_exact_range(fee_bps):
    # fee must be EXACTLY 1; 8bp / 2bp / negative are rejected.
    p = _mutated(lambda q: q["offer"].__setitem__("assetfare_fee_bps", fee_bps))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_fee_two_steps():
    # fee=1 but 2 collection steps -> step count mismatch
    p = _mutated(lambda q: q["offer"].__setitem__("fee_collection_steps", [0, 1]))
    with pytest.raises(ValueError, match="assetfare_fee_step_count_mismatch"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_positive_fee_with_no_collection_step():
    # fee=1 but 0 steps -> step count mismatch
    p = _mutated(lambda q: q["offer"].__setitem__("fee_collection_steps", []))
    with pytest.raises(ValueError, match="assetfare_fee_step_count_mismatch"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_zero_fee_with_step():
    def mut(q):
        q["offer"]["assetfare_fee_bps"] = 0
        q["offer"]["fee_modeled_bps"] = 0
        q["offer"]["fee_collectible_now"] = False
        q["offer"]["fee_collection_steps"] = [0]
    p = _mutated(mut)
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_fee_step_out_of_range():
    p = _mutated(lambda q: q["offer"].__setitem__("fee_collection_steps", [5]))
    with pytest.raises(ValueError, match="assetfare_fee_step_out_of_range"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_missing_fee_collection_const():
    p = _mutated(lambda q: q["offer"].pop("fee_collection"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


@pytest.mark.parametrize(
    "mut",
    [
        lambda q: q.update(server_signing=True),
        lambda q: q["intent"].update(server_submission=True),
        lambda q: q["offer"].update(server_signing=True),
        lambda q: q["execution"].update(server_submission=True),
        lambda q: q["route"]["steps"][0].update(server_signing=True),
    ],
)
def test_quote_rejects_nested_sign_or_submit_claim(mut):
    payload = quote_payload()
    mut(payload)
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        quote_tool(quote_session(payload)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_posts_normalised_payload():
    s = quote_session()
    quote_tool(s).forward("solana", "sol", "base", "eth", 250)
    method, url, kwargs = s.calls[0]
    assert method == "POST"
    assert url == "https://api.assetfare.dev/v2/quote"
    assert kwargs["json"]["from_token"] == "SOL"
    assert kwargs["json"]["to_token"] == "ETH"
    assert kwargs["json"]["amount_usd"] == 250.0
    assert kwargs["allow_redirects"] is False


# ---- quote input validation ---------------------------------------------

@pytest.mark.parametrize("amt", [0.0, 0.99])
def test_quote_amount_out_of_range(amt):
    with pytest.raises(ValueError, match="assetfare_amount_out_of_range"):
        quote_tool(quote_session()).forward("solana", "SOL", "base", "ETH", amt)


@pytest.mark.parametrize("amt", [1000.01, 5000])
def test_quote_amount_above_former_business_maximum_accepted(amt):
    payload = quote_payload()
    payload["intent"]["amount_usd"] = amt
    payload["offer"]["expected_receive_usd"] = amt - 0.9
    payload["offer"]["estimated_min_receive_usd"] = amt - 3.0
    result = quote_tool(quote_session(with_cost_summary(payload))).forward("solana", "SOL", "base", "ETH", amt)
    assert result["amount_usd"] == amt


@pytest.mark.parametrize("amt", [True, "250", None, float("nan"), float("inf")])
def test_quote_amount_invalid(amt):
    with pytest.raises(ValueError, match="assetfare_amount_invalid"):
        quote_tool(quote_session()).forward("solana", "SOL", "base", "ETH", amt)


def test_quote_source_endpoint_invalid():
    with pytest.raises(ValueError, match="assetfare_source_endpoint_invalid"):
        quote_tool(quote_session()).forward("solana", "BONK", "base", "ETH", 250)


def test_quote_destination_endpoint_invalid():
    with pytest.raises(ValueError, match="assetfare_destination_endpoint_invalid"):
        quote_tool(quote_session()).forward("solana", "SOL", "base", "WBTC", 250)


def test_quote_identity_route_rejected():
    with pytest.raises(ValueError, match="assetfare_identity_route_rejected"):
        quote_tool(quote_session()).forward("solana", "USDC", "solana", "usdc", 250)


# ---- quote response strictness ------------------------------------------

def _mutated(mutate):
    p = copy.deepcopy(quote_payload())
    mutate(p)
    return p


def test_quote_rejects_route_label_mismatch():
    p = _mutated(lambda q: q["route"].__setitem__("route", "solana:SOL->arbitrum:ETH"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_intent_amount_mismatch():
    p = _mutated(lambda q: q["intent"].__setitem__("amount_usd", 251.0))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_min_gt_expected():
    p = _mutated(lambda q: q["offer"].__setitem__("estimated_min_receive_amount", 0.09))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_negative_fee():
    p = _mutated(lambda q: q["offer"].__setitem__("assetfare_fee_bps", -1))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_bad_output_symbol():
    p = _mutated(lambda q: q["offer"].__setitem__("output_symbol", "USDC"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_empty_steps():
    p = _mutated(lambda q: q["route"].__setitem__("steps", []))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_non_dict_step():
    p = _mutated(lambda q: q["route"].__setitem__("steps", ["swap"]))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_route_server_signing():
    p = _mutated(lambda q: q["route"].__setitem__("server_signing", True))
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_fresh_flag_false():
    p = _mutated(lambda q: q["risk"].__setitem__("fresh_quote_required_each_step", False))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_non_atomic_non_bool():
    p = _mutated(lambda q: q["risk"].__setitem__("non_atomic", "yes"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_execution_unsupported():
    # an executable (four-chain) route claiming execution.supported=false is a
    # boundary violation (source-only routes get their own discriminated handling).
    p = _mutated(lambda q: q["execution"].__setitem__("supported", False))
    with pytest.raises(ValueError, match="assetfare_execution_boundary_failed"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_receipts_flag_false():
    p = _mutated(lambda q: q["execution"].__setitem__("future_actions_require_verified_receipts", False))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_bad_uuid():
    p = _mutated(lambda q: q.__setitem__("quote_id", "not-a-uuid"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


@pytest.mark.parametrize("ttl", [0, -5, 86401, "60", 1.5])
def test_quote_rejects_bad_ttl(ttl):
    p = _mutated(lambda q: q.__setitem__("ttl_seconds", ttl))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


# ---- quote freshness (as_of) --------------------------------------------

def test_quote_rejects_naive_as_of():
    p = _mutated(lambda q: q.__setitem__("as_of", "2026-09-17T00:00:05"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_date_only_as_of():
    p = _mutated(lambda q: q.__setitem__("as_of", "2026-09-17"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_expired():
    # as_of + ttl < now: as_of far in the past
    p = _mutated(lambda q: (q.__setitem__("as_of", "2026-09-17T00:00:05Z"), q.__setitem__("ttl_seconds", 1)))
    now = datetime(2026, 9, 17, 0, 5, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p), utcnow=lambda: now).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_future_skew():
    p = _mutated(lambda q: q.__setitem__("as_of", "2026-09-17T01:00:00Z"))  # 1h ahead of FIXED_NOW
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_accepts_numeric_offset_as_of():
    p = _mutated(lambda q: q.__setitem__("as_of", "2026-09-17T00:00:05+00:00"))
    out = quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)
    assert out["as_of"] == "2026-09-17T00:00:05+00:00"


# ---- transport ----------------------------------------------------------

@pytest.mark.parametrize(
    "status,match",
    [
        (301, "assetfare_upstream_unavailable"),
        (429, "assetfare_rate_limited"),
        (500, "assetfare_upstream_unavailable"),
        (400, "assetfare_request_rejected"),
    ],
)
def test_quote_http_status(status, match):
    s = _Session([_Resp(quote_payload(), status=status)])
    with pytest.raises(ValueError, match=match):
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_non_json_media():
    s = _Session([_Resp(quote_payload(), content_type="text/html")])
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_oversize_declared():
    s = _Session([_Resp(quote_payload(), headers={"content-length": str(2 * 1024 * 1024)})])
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_rejects_oversize_stream():
    big = b"x" * (1024 * 1024 + 10)
    s = _Session([_Resp(quote_payload(), chunks=[big, big])])
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_transport_exception_sanitised():
    import requests

    s = _Session([requests.RequestException("boom")])
    with pytest.raises(ValueError, match="assetfare_upstream_unavailable"):
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)


def test_quote_response_closed():
    r = _Resp(quote_payload())
    s = _Session([r])
    quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert r.closed is True


# ---- stale budget -------------------------------------------------------

def test_stale_budget_pre_request_rejected():
    # monotonic: start(0) sets deadline=45; next call returns 100 -> remaining<0
    clk = _Clock([0.0, 100.0])
    s = quote_session()
    with pytest.raises(ValueError, match="assetfare_upstream_unavailable"):
        quote_tool(s, monotonic=clk).forward("solana", "SOL", "base", "ETH", 250)


def test_stale_budget_rejects_delayed_chunk():
    # deadline set at t0=0 (+45). request-time check ok at t=1. chunk boundary at t=100 -> overrun.
    clk = _Clock([0.0, 1.0, 100.0])
    s = quote_session()
    with pytest.raises(ValueError, match="assetfare_upstream_unavailable"):
        quote_tool(s, monotonic=clk).forward("solana", "SOL", "base", "ETH", 250)


def test_no_signing_fields_ever_sent():
    s = quote_session()
    quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    body = s.calls[0][2]["json"]
    for k in body:
        assert "sign" not in k and "submit" not in k and "wallet" not in k and "key" not in k


# ---- hostile parsing (JSONDecodeError / UnicodeDecodeError are ValueError
#      subclasses; they must be sanitized to the fixed code, not leaked) ------

def test_quote_malformed_json_sanitized():
    s = _Session([_Resp(None, chunks=[b"<<not valid json>>"])])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_response_invalid"


def test_quote_invalid_utf8_sanitized():
    s = _Session([_Resp(None, chunks=[b"\xff\xfe\x00\x80bad"])])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_response_invalid"


def test_quote_json_non_object_sanitized():
    s = _Session([_Resp(None, chunks=[b"[1, 2, 3]"])])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_response_invalid"


def test_capabilities_malformed_json_sanitized():
    s = _Session([_Resp(None, chunks=[b"{oops"])])
    with pytest.raises(ValueError) as ei:
        caps_tool(s).forward()
    assert str(ei.value) == "assetfare_response_invalid"


def test_capabilities_invalid_utf8_sanitized():
    s = _Session([_Resp(None, chunks=[b"\xff\xfe\x00\x80bad"])])
    with pytest.raises(ValueError) as ei:
        caps_tool(s).forward()
    assert str(ei.value) == "assetfare_response_invalid"


def test_no_upstream_text_leaks_in_error():
    # truncated body carrying a plausible upstream secret -> JSONDecodeError
    s = _Session([_Resp(None, chunks=[b'{"error": "SECRET UPSTREAM DETAIL"'])])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert "SECRET" not in str(ei.value)
    assert str(ei.value) == "assetfare_response_invalid"


# ---- trust_env forced off on injected session ---------------------------

def test_injected_session_trust_env_forced_false_quote():
    s = _Session([_Resp(quote_payload())])
    assert s.trust_env is True
    t = AssetFareQuoteTool(session=s, monotonic=_Clock([0.0]), utcnow=fixed_now)
    assert s.trust_env is False
    assert t._session is s


def test_injected_session_trust_env_forced_false_capabilities():
    s = _Session([_Resp(caps_payload()), _Resp(status_payload())])
    AssetFareCapabilitiesTool(session=s, monotonic=_Clock([0.0]))
    assert s.trust_env is False


# ---- pinned reproducible requirements emitted to the Hub Space -----------

@pytest.mark.parametrize("Cls", [AssetFareCapabilitiesTool, AssetFareQuoteTool])
def test_pinned_requirements_emitted(Cls):
    req = Cls()._get_requirements()
    assert "smolagents==1.26.0" in req
    assert "requests>=2.32.3,<3" in req


# ---- RFC3339 'Z' normalization (Python 3.10 fromisoformat compat) ---------

def test_quote_z_suffix_as_of_accepted():
    # The happy payload uses '...Z'; on 3.10 fromisoformat rejects a bare 'Z',
    # so this exercises the Z->+00:00 normalization. The raw string is echoed.
    out = quote_tool(quote_session()).forward("solana", "SOL", "base", "ETH", 250)
    assert out["as_of"].endswith("Z")


def test_quote_z_suffix_future_skew_still_rejected():
    # Normalization must not defeat the skew check: a 'Z' time 1h ahead is rejected.
    p = _mutated(lambda q: q.__setitem__("as_of", "2026-09-17T01:00:00Z"))
    with pytest.raises(ValueError, match="assetfare_response_invalid"):
        quote_tool(quote_session(p)).forward("solana", "SOL", "base", "ETH", 250)


# ---- exception-chain suppression (no upstream __cause__; context suppressed) --

def test_parse_error_suppresses_chain():
    s = _Session([_Resp(None, chunks=[b"<<bad json SECRET>>"])])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert ei.value.__cause__ is None
    assert ei.value.__context__ is None
    assert ei.value.__suppress_context__ is False  # nothing to suppress: __context__ is already None
    assert "SECRET" not in str(ei.value)


def test_transport_error_suppresses_chain():
    import requests

    s = _Session([requests.RequestException("boom SECRET UPSTREAM")])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert ei.value.__cause__ is None
    assert ei.value.__context__ is None
    assert ei.value.__suppress_context__ is False  # nothing to suppress: __context__ is already None
    assert "SECRET" not in str(ei.value)


def test_capabilities_transport_error_suppresses_chain():
    import requests

    s = _Session([requests.RequestException("boom SECRET")])
    with pytest.raises(ValueError) as ei:
        caps_tool(s).forward()
    assert ei.value.__cause__ is None
    assert ei.value.__context__ is None
    assert ei.value.__suppress_context__ is False  # nothing to suppress: __context__ is already None


# ---- hostile stream: iter_content raising a ValueError with upstream text ----
#      (the internal budget/size failures use a sentinel, so an external
#       ValueError from the stream is sanitized, not re-raised) ---------------

def test_quote_hostile_iter_valueerror_sanitized():
    hostile = _Resp(quote_payload())
    hostile._iter_exc = ValueError("SECRET_STREAM_DETAIL leaked token")
    s = _Session([hostile])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_upstream_unavailable"
    assert "SECRET" not in str(ei.value)
    assert ei.value.__cause__ is None
    assert ei.value.__context__ is None
    assert ei.value.__suppress_context__ is False  # nothing to suppress: __context__ is already None


def test_capabilities_hostile_iter_valueerror_sanitized():
    hostile = _Resp(caps_payload())
    hostile._iter_exc = ValueError("SECRET_STREAM_DETAIL leaked token")
    s = _Session([hostile])
    with pytest.raises(ValueError) as ei:
        caps_tool(s).forward()
    assert str(ei.value) == "assetfare_upstream_unavailable"
    assert "SECRET" not in str(ei.value)
    assert ei.value.__cause__ is None
    assert ei.value.__context__ is None
    assert ei.value.__suppress_context__ is False  # nothing to suppress: __context__ is already None


def test_quote_hostile_iter_runtimeerror_sanitized():
    hostile = _Resp(quote_payload())
    hostile._iter_exc = RuntimeError("SECRET_CHUNK boom")
    s = _Session([hostile])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_upstream_unavailable"
    assert "SECRET" not in str(ei.value)
    assert ei.value.__context__ is None


def test_quote_malformed_json_context_is_none():
    # the strongest check: final exception carries NO __context__ object at all
    s = _Session([_Resp(None, chunks=[b'{"secret": "SECRET_JSON_DETAIL"'])])  # truncated -> JSONDecodeError
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_response_invalid"
    assert ei.value.__context__ is None
    assert ei.value.__cause__ is None
    assert "SECRET" not in repr(ei.value)


def test_quote_invalid_utf8_context_is_none():
    s = _Session([_Resp(None, chunks=[b"\xff\xfe\x00\x80SECRET"])])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_response_invalid"
    assert ei.value.__context__ is None


def test_transport_error_context_is_none():
    import requests

    s = _Session([requests.RequestException("boom SECRET UPSTREAM")])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert ei.value.__context__ is None
    assert ei.value.__cause__ is None
    assert "SECRET" not in str(ei.value)


# ---- hostile send: injected session.request raising a non-RequestException ----
#      (a broken/hostile session may raise RuntimeError/ValueError with upstream
#       text; the send handler catches Exception broadly and sanitizes) --------

def test_quote_send_hostile_runtimeerror_sanitized():
    s = _Session([RuntimeError("SECRET_SEND boom token")])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_upstream_unavailable"
    assert "SECRET" not in str(ei.value)
    assert ei.value.__context__ is None
    assert ei.value.__cause__ is None


def test_quote_send_hostile_valueerror_sanitized():
    s = _Session([ValueError("SECRET_SEND detail")])
    with pytest.raises(ValueError) as ei:
        quote_tool(s).forward("solana", "SOL", "base", "ETH", 250)
    assert str(ei.value) == "assetfare_upstream_unavailable"
    assert "SECRET" not in str(ei.value)
    assert ei.value.__context__ is None
    assert ei.value.__cause__ is None


def test_capabilities_send_hostile_valueerror_sanitized():
    s = _Session([ValueError("SECRET_SEND detail")])
    with pytest.raises(ValueError) as ei:
        caps_tool(s).forward()
    assert str(ei.value) == "assetfare_upstream_unavailable"
    assert "SECRET" not in str(ei.value)
    assert ei.value.__context__ is None
    assert ei.value.__cause__ is None
