"""Offline mock tests for the caller-approved, non-custodial AssetFare action tools.

Covers the new smolagents tools:
  - assetfare_new_session_capability (local-only token; zero network)
  - assetfare_prepare               (POST /v2/prepare)
  - assetfare_session_create/get/observe_source/observe_output/refresh_action

No network. A stateful fake session models the server's create idempotency (keyed on
the caller-owned X-AssetFare-Session-Token + idempotency_key) so replay / crash /
independent-session behaviour can be asserted. Also runs the full 76-route multi-step
MOCK e2e matrix: all 76 execution-ready routes complete quote -> prepare ->
session lifecycle, including the four directional Polygon/Optimism source-only routes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assetfare_prepare_tool import AssetFarePrepareTool
from assetfare_session_capability_tool import AssetFareNewSessionCapabilityTool
from assetfare_session_tools import (
    AssetFareObserveOutputTool,
    AssetFareObserveSourceTool,
    AssetFareRefreshActionTool,
    AssetFareSessionCreateTool,
    AssetFareSessionGetTool,
)

EVM = "0x" + "1" * 40
SOL = "So11111111111111111111111111111111111111112"  # 43-char base58
TOKEN = "A" * 43  # valid session-token shape (43 url-safe chars)
TOKEN2 = "B" * 43
TX_SRC = "5" * 32
TX_OUT = "0x" + "a" * 40


def approval(mode, key="approval-0001"):
    quote = {
        "version": "assetfare-quote-bound-approval-v3",
        "quote_id": "11111111-1111-4111-8111-111111111111",
        "quote_fingerprint": "a" * 64,
        "selection_status": "selected",
        "selected_mode": mode,
        "maximum_input_base": "250000000",
        "minimum_output_base": "249000000",
        "direct_route_summary_sha256": "b" * 64,
        "idempotency_key": key,
    }
    return quote


class _Clock:
    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def __call__(self):
        v = self._values[min(self._i, len(self._values) - 1)]
        self._i += 1
        return v


def clk():
    return _Clock([0.0])


class _Resp:
    def __init__(self, payload, status=200, content_type="application/json"):
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        self._body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.headers = {"content-type": content_type}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        self.closed = True


class _Session:
    """Fake session yielding queued responses; records calls."""

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


class FakeServer:
    """Stateful non-custodial /v2 server model with token-scoped create idempotency."""

    def __init__(self):
        self._sessions = {}  # (token, idempotency_key) -> session_id
        self._counter = 0
        self.trust_env = True
        self.calls = []

    def _new_id(self):
        self._counter += 1
        return f"{self._counter:08d}-0000-4000-8000-000000000000"

    def _session_body(self, session_id, phase="created"):
        return {
            "session_id": session_id,
            "phase": phase,
            "server_signing": False,
            "server_submission": False,
            "signed": False,
            "submitted": False,
            "unsigned_action": {"kind": "source", "chain": "solana"},
        }

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        headers = kwargs.get("headers") or {}
        token = headers.get("X-AssetFare-Session-Token")
        body = kwargs.get("json") or {}
        path = url.replace("https://api.assetfare.dev", "")

        if path == "/v2/prepare" and method == "POST":
            return _Resp(
                {
                    "server_signing": False,
                    "server_submission": False,
                    "signed": False,
                    "submitted": False,
                    "unsigned_action": {"kind": "source", "chain": body.get("from_chain")},
                    "fresh_quote": {"quote_id": "11111111-1111-4111-8111-111111111111"},
                }
            )

        if path == "/v2/session" and method == "POST":
            key = (token, body.get("idempotency_key"))
            sid = self._sessions.get(key)
            if sid is None:
                sid = self._new_id()
                self._sessions[key] = sid
            return _Resp(self._session_body(sid))

        if path.startswith("/v2/session/"):
            sid = path.split("/v2/session/")[1].split("/")[0]
            if path.endswith("/observe-source"):
                return _Resp(self._session_body(sid, "source_observed"))
            if path.endswith("/observe-output"):
                return _Resp(self._session_body(sid, "output_observed"))
            if path.endswith("/refresh-action"):
                return _Resp(self._session_body(sid, "refreshed"))
            return _Resp(self._session_body(sid, "read"))

        return _Resp({"error": "not_found"}, status=404)


def prepare_tool(session):
    return AssetFarePrepareTool(session=session, monotonic=clk())


def create_tool(session):
    return AssetFareSessionCreateTool(session=session, monotonic=clk())


def get_tool(session):
    return AssetFareSessionGetTool(session=session, monotonic=clk())


def observe_source_tool(session):
    return AssetFareObserveSourceTool(session=session, monotonic=clk())


def observe_output_tool(session):
    return AssetFareObserveOutputTool(session=session, monotonic=clk())


def refresh_tool(session):
    return AssetFareRefreshActionTool(session=session, monotonic=clk())


def prepare_bundle_resp():
    return _Resp(
        {
            "server_signing": False,
            "server_submission": False,
            "signed": False,
            "submitted": False,
            "unsigned_action": {"kind": "source", "chain": "solana"},
        }
    )


def session_resp(session_id="3f2504e0-4f89-41d3-9a0c-0305e82c3301", phase="created"):
    return _Resp(
        {
            "session_id": session_id,
            "phase": phase,
            "server_signing": False,
            "server_submission": False,
            "signed": False,
            "submitted": False,
        }
    )


WALLETS = {"solana": SOL, "base": EVM}


# ---- new_session_capability (local-only, zero network) ------------------------

def test_new_session_capability_zero_network():
    t = AssetFareNewSessionCapabilityTool()
    out = t.forward()
    import re

    assert re.match(r"^[A-Za-z0-9_-]{43,128}$", out["session_token"])
    assert out["token_bits"] == 256
    assert out["is_private_key"] is False
    assert out["network_calls"] == 0
    assert out["sensitivity"] == "sensitive_capability"
    assert out["server_signing"] is False and out["server_submission"] is False


def test_new_session_capability_unique_each_call():
    t = AssetFareNewSessionCapabilityTool()
    assert t.forward()["session_token"] != t.forward()["session_token"]


# ---- prepare happy + hostiles -------------------------------------------------

def test_prepare_happy():
    s = _Session([prepare_bundle_resp()])
    out = prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, approval("one_shot"))
    assert out["action_prepared"] is True
    assert out["transaction_signed"] is False and out["transaction_submitted"] is False
    assert out["server_signs_or_submits"] is False
    assert out["bundle"]["unsigned_action"]["kind"] == "source"
    # caller_approved:true was sent; no signing fields present in body.
    body = s.calls[0][2]["json"]
    assert body["caller_approved"] is True
    assert body["approval_v3"]["selected_mode"] == "one_shot"
    assert s.calls[0][1] == "https://api.assetfare.dev/v2/prepare"


@pytest.mark.parametrize("mut", [
    lambda a:a.update(extra=True),
    lambda a:a.update(version="legacy"),
    lambda a:a.update(selection_status="unranked_candidate"),
    lambda a:a.update(selected_mode="session"),
    lambda a:a.update(quote_fingerprint="0" * 63),
    lambda a:a.update(maximum_input_base=250000000),
    lambda a:a.update(minimum_output_base="0"),
    lambda a:a.update(private_key="forbidden"),
])
def test_prepare_rejects_malformed_or_wrong_mode_approval_before_network(mut):
    candidate = approval("one_shot")
    mut(candidate)
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_(approval_v3|secret_material)"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, candidate)
    assert s.calls == []


@pytest.mark.parametrize("amt", [1000.01, 5000])
def test_prepare_amount_above_former_business_maximum_accepted(amt):
    s = _Session([prepare_bundle_resp()])
    prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", amt, WALLETS, approval("one_shot"))
    assert s.calls[0][2]["json"]["amount_usd"] == amt


@pytest.mark.parametrize("amt", [0.99, True, "5", float("nan"), float("inf")])
def test_prepare_rejects_non_finite_non_numeric_or_below_minimum_amount(amt):
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_amount_(invalid|out_of_range)"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", amt, WALLETS, approval("one_shot"))
    assert s.calls == []


@pytest.mark.parametrize("approved", [False, None, "true", 1, 0])
def test_prepare_caller_approved_gate(approved):
    s = _Session([])  # must fail BEFORE any network call
    with pytest.raises(ValueError, match="assetfare_caller_approval_required"):
        prepare_tool(s).forward(approved, "solana", "SOL", "base", "ETH", 250, WALLETS, approval("one_shot"))
    assert s.calls == []


def test_prepare_accepts_source_only_execution_route():
    s = _Session([prepare_bundle_resp()])
    out = prepare_tool(s).forward(True, "polygon", "USDC", "base", "USDC", 10, {"polygon": EVM, "base": EVM}, approval("one_shot"))
    assert out["action_prepared"] is True


@pytest.mark.parametrize(
    "wallets",
    [
        {"solana": SOL, "base": EVM, "private_key": "deadbeef"},
        {"solana": SOL, "base": {"seed_phrase": "a b c"}},
    ],
)
def test_prepare_rejects_secret_material(wallets):
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_secret_material_rejected"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, wallets, approval("one_shot"))
    assert s.calls == []


def test_prepare_rejects_non_public_wallet():
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_wallet_not_public_address"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, {"solana": SOL, "base": "not-an-address"}, approval("one_shot"))
    assert s.calls == []


def test_prepare_rejects_wallets_route_mismatch():
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_wallets_route_mismatch"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, {"arbitrum": EVM}, approval("one_shot"))
    assert s.calls == []


def test_prepare_event_signer_public_passed_through():
    s = _Session([prepare_bundle_resp()])
    prepare_tool(s).forward(True, "solana", "USDC", "base", "USDC", 250, WALLETS, approval("one_shot"), event_signer_public=SOL)
    assert s.calls[0][2]["json"]["event_signer_public"] == SOL


def test_prepare_rejects_private_key_as_event_signer():
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_event_signer_not_public_address"):
        prepare_tool(s).forward(True, "solana", "USDC", "base", "USDC", 250, WALLETS, approval("one_shot"), event_signer_public="0xshort")
    assert s.calls == []


def test_prepare_rejects_unsafe_bundle():
    s = _Session([_Resp({"server_signing": True, "unsigned_action": {}})])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, approval("one_shot"))


def test_prepare_rejects_bundle_missing_action():
    s = _Session([_Resp({"server_signing": False, "server_submission": False, "signed": False, "submitted": False})])
    with pytest.raises(ValueError, match="assetfare_bundle_missing_action"):
        prepare_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, approval("one_shot"))


# ---- session create + gate + token hostiles -----------------------------------

def test_session_create_happy_sends_token_header():
    s = _Session([session_resp()])
    out = create_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-00000001", approval("session", "key-00000001"))
    assert out["session_id"] == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    hdr = s.calls[0][2]["headers"]["X-AssetFare-Session-Token"]
    assert hdr == TOKEN
    # token must NOT appear in the request body
    assert "session_token" not in s.calls[0][2]["json"]
    assert s.calls[0][2]["json"]["approval_v3"]["selected_mode"] == "session"
    assert TOKEN not in json.dumps(out, sort_keys=True)


@pytest.mark.parametrize("mut", [
    lambda a:a.update(extra=True),
    lambda a:a.update(version="legacy"),
    lambda a:a.update(selection_status="unranked_candidate"),
    lambda a:a.update(selected_mode="one_shot"),
    lambda a:a.update(idempotency_key="other-key-001"),
    lambda a:a.update(direct_route_summary_sha256="b" * 63),
    lambda a:a.update(private_key="forbidden"),
])
def test_session_create_rejects_malformed_wrong_mode_or_key_approval_before_network(mut):
    candidate = approval("session", "key-00000001")
    mut(candidate)
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_(approval_v3|secret_material)"):
        create_tool(s).forward(
            True, "solana", "SOL", "base", "ETH", 250, WALLETS,
            TOKEN, "key-00000001", candidate,
        )
    assert s.calls == []


@pytest.mark.parametrize("amt", [1000.01, 5000])
def test_session_create_amount_above_former_business_maximum_accepted(amt):
    s = _Session([session_resp()])
    create_tool(s).forward(True, "solana", "SOL", "base", "ETH", amt, WALLETS, TOKEN, "key-00000001", approval("session", "key-00000001"))
    assert s.calls[0][2]["json"]["amount_usd"] == amt


@pytest.mark.parametrize("approved", [False, None, "true", 1])
def test_session_create_caller_approved_gate(approved):
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_caller_approval_required"):
        create_tool(s).forward(approved, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-00000001", approval("session", "key-00000001"))
    assert s.calls == []


@pytest.mark.parametrize("bad", [None, "", "short", "A" * 200, 123])
def test_session_create_rejects_bad_token(bad):
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_session_token_invalid"):
        create_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, bad, "key-00000001", approval("session", "key-00000001"))
    assert s.calls == []


@pytest.mark.parametrize("bad", [None, "short", "bad key!"])
def test_session_create_rejects_bad_idempotency(bad):
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_idempotency_key_invalid"):
        create_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, bad, approval("session", "key-00000001"))
    assert s.calls == []


def test_session_create_accepts_source_only_execution_route():
    s = _Session([session_resp()])
    out = create_tool(s).forward(True, "optimism", "USDC", "base", "USDC", 10, {"optimism": EVM, "base": EVM}, TOKEN, "key-00000001", approval("session", "key-00000001"))
    assert out["session_id"] == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


# ---- idempotency / crash-recovery via the stateful FakeServer ------------------

def test_session_replay_same_token_and_key_returns_same_session():
    srv = FakeServer()
    a = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-abc-001", approval("session", "key-abc-001"))
    b = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-abc-001", approval("session", "key-abc-001"))
    assert a["session_id"] == b["session_id"]  # replay -> same session


def test_session_lost_response_retry_same_token_key_recovers_same_session():
    # Simulate a lost create response: the first create commits server-side but the
    # response never reaches the caller; the caller retries with the SAME token +
    # idempotency_key and recovers the SAME session (no duplicate).
    srv = FakeServer()
    first = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-lost-1", approval("session", "key-lost-1"))
    # caller never saw `first`; retries identically
    retry = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-lost-1", approval("session", "key-lost-1"))
    assert first["session_id"] == retry["session_id"]
    assert srv._counter == 1  # exactly one session created despite two create calls


def test_session_different_token_same_key_independent_sessions():
    srv = FakeServer()
    a = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-shared", approval("session", "key-shared"))
    b = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN2, "key-shared", approval("session", "key-shared"))
    assert a["session_id"] != b["session_id"]  # idempotency key is token-scoped


# ---- session get / observe / refresh -----------------------------------------

def test_session_get_happy():
    srv = FakeServer()
    created = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-get-1", approval("session", "key-get-1"))
    got = get_tool(srv).forward(TOKEN, created["session_id"])
    assert got["session_id"] == created["session_id"]
    # last call carried the token header and hit the {id} path
    m, url, kw = srv.calls[-1]
    assert m == "GET" and url.endswith("/v2/session/" + created["session_id"])
    assert kw["headers"]["X-AssetFare-Session-Token"] == TOKEN


def test_session_get_rejects_bad_session_id():
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_session_id_invalid"):
        get_tool(s).forward(TOKEN, "not-a-uuid")
    assert s.calls == []


def test_observe_source_happy_only_caller_tx_hashes():
    srv = FakeServer()
    created = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-os-1", approval("session", "key-os-1"))
    out = observe_source_tool(srv).forward(TOKEN, created["session_id"], "key-os-2", [TX_SRC])
    assert out["session_id"] == created["session_id"]
    body = srv.calls[-1][2]["json"]
    assert body["transaction_hashes"] == [TX_SRC]  # only caller-submitted hashes observed


@pytest.mark.parametrize("hashes", [[], ["short"], ["x" * 200], "notalist", [123]])
def test_observe_source_rejects_bad_hashes(hashes):
    s = _Session([])
    with pytest.raises(ValueError, match="assetfare_transaction_hashes_invalid"):
        observe_source_tool(s).forward(TOKEN, "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "key-os-2", hashes)
    assert s.calls == []


def test_observe_output_happy_optional_hash():
    srv = FakeServer()
    created = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-oo-1", approval("session", "key-oo-1"))
    out = observe_output_tool(srv).forward(TOKEN, created["session_id"], "key-oo-2", TX_OUT)
    assert out["session_id"] == created["session_id"]
    assert srv.calls[-1][2]["json"]["transaction_hash"] == TX_OUT


def test_observe_output_without_hash():
    srv = FakeServer()
    created = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-oo-3", approval("session", "key-oo-3"))
    observe_output_tool(srv).forward(TOKEN, created["session_id"], "key-oo-4")
    assert "transaction_hash" not in srv.calls[-1][2]["json"]


def test_refresh_action_happy():
    srv = FakeServer()
    created = create_tool(srv).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-rf-1", approval("session", "key-rf-1"))
    out = refresh_tool(srv).forward(TOKEN, created["session_id"], "key-rf-2")
    assert out["session_id"] == created["session_id"]
    assert srv.calls[-1][1].endswith("/refresh-action")


def test_refresh_expired_session_rejected():
    # A refresh on an expired/unknown session -> server 409 -> fixed request_rejected.
    s = _Session([_Resp({"error": "session_expired"}, status=409)])
    with pytest.raises(ValueError, match="assetfare_request_rejected"):
        refresh_tool(s).forward(TOKEN, "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "key-rf-3")


@pytest.mark.parametrize("tool_factory", [get_tool, refresh_tool])
def test_session_read_rejects_bad_token(tool_factory):
    s = _Session([])
    t = tool_factory(s)
    with pytest.raises(ValueError, match="assetfare_session_token_invalid"):
        if tool_factory is get_tool:
            t.forward("short", "3f2504e0-4f89-41d3-9a0c-0305e82c3301")
        else:
            t.forward("short", "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "key-00000001")
    assert s.calls == []


def test_session_rejects_unsafe_response():
    s = _Session([_Resp({"session_id": "x", "server_signing": True})])
    with pytest.raises(ValueError, match="assetfare_safety_boundary_failed"):
        create_tool(s).forward(True, "solana", "SOL", "base", "ETH", 250, WALLETS, TOKEN, "key-unsafe", approval("session", "key-unsafe"))


# ---- 76-route multi-step MOCK e2e matrix (all executable) ---------------------

SOURCE_ENDPOINTS = [
    ("solana", "SOL"), ("solana", "USDC"), ("solana", "USDG"),
    ("base", "ETH"), ("base", "USDC"),
    ("arbitrum", "ETH"), ("arbitrum", "USDC"),
    ("robinhood", "ETH"), ("robinhood", "USDG"),
    ("polygon", "USDC"), ("optimism", "USDC"),
]
DEST_ENDPOINTS = [ep for ep in SOURCE_ENDPOINTS if ep[0] not in ("polygon", "optimism")]
SOURCE_ONLY = {"polygon", "optimism"}
WALLET_ADDR = {
    "solana": SOL, "base": EVM, "arbitrum": EVM, "robinhood": EVM, "polygon": EVM, "optimism": EVM,
}


def _enumerate_routes():
    routes = []
    for sc, st in SOURCE_ENDPOINTS:
        for dc, dt in DEST_ENDPOINTS:
            if (sc, st) == (dc, dt):
                continue
            if sc in SOURCE_ONLY and not (st == "USDC" and dc in ("base", "arbitrum") and dt == "USDC"):
                continue
            routes.append((sc, st, dc, dt))
    return routes


def _quote_payload(sc, st, dc, dt):
    from_s, to_s = f"{sc}:{st}", f"{dc}:{dt}"
    fee = 1
    steps_meta = []

    def add_swap(chain, source, destination):
        if chain == "solana":
            provider = "raydium_clmm" if {source, destination} == {"SOL", "USDC"} else "orca_whirlpool"
        else:
            provider = "uniswap_v3"
        steps_meta.append({
            "kind": "direct_swap", "provider": provider, "chain": chain,
            "from": source, "to": destination,
        })

    def add_bridge(provider, source, destination, source_asset, destination_asset):
        row = {"kind": "direct_bridge", "provider": provider, "from": source, "to": destination}
        if provider == "across_intent_bridge":
            row.update(from_asset=source_asset, to_asset=destination_asset)
        else:
            assert source_asset == destination_asset
            row["asset"] = source_asset
        steps_meta.append(row)

    if sc in SOURCE_ONLY:
        mode = sc + "_source_cctp"
        add_bridge("circle_cctp", sc, dc, "USDC", "USDC")
    elif sc == dc:
        if sc == "solana" and {st, dt} == {"SOL", "USDG"}:
            mode = "same_chain_direct_composition"
            if st == "SOL":
                add_swap("solana", "SOL", "USDC")
                add_swap("solana", "USDC", "USDG")
            else:
                add_swap("solana", "USDG", "USDC")
                add_swap("solana", "USDC", "SOL")
        else:
            mode = "same_chain_direct"
            add_swap(sc, st, dt)
    elif sc == "robinhood":
        mode = "robinhood_paxos_egress_composition"
        if st == "ETH":
            add_swap("robinhood", "ETH", "USDG")
        add_bridge("paxos_usdg_layerzero_oft", "robinhood", "solana", "USDG", "USDG")
        if dc == "solana":
            if dt == "USDC":
                add_swap("solana", "USDG", "USDC")
            elif dt == "SOL":
                add_swap("solana", "USDG", "USDC")
                add_swap("solana", "USDC", "SOL")
        else:
            add_swap("solana", "USDG", "USDC")
            add_bridge("circle_cctp", "solana", dc, "USDC", "USDC")
            if dt == "ETH":
                add_swap(dc, "USDC", "ETH")
    elif dc == "robinhood":
        mode = "robinhood_across_ingress_composition"
        if sc == "solana":
            if st == "SOL":
                add_swap("solana", "SOL", "USDC")
            elif st == "USDG":
                add_swap("solana", "USDG", "USDC")
            add_bridge("circle_cctp", "solana", "base", "USDC", "USDC")
            across_source = "base"
        else:
            if st == "ETH":
                add_swap(sc, "ETH", "USDC")
            across_source = sc
        add_bridge("across_intent_bridge", across_source, "robinhood", "USDC", "USDG")
        if dt == "ETH":
            add_swap("robinhood", "USDG", "ETH")
    else:
        mode = "cctp_direct_composition"
        if st != "USDC":
            add_swap(sc, st, "USDC")
        add_bridge("circle_cctp", sc, dc, "USDC", "USDC")
        if dt != "USDC":
            add_swap(dc, "USDC", dt)

    summary_steps = []
    expected_input = minimum_input = 1000000
    external = False
    for index, row in enumerate(steps_meta):
        expected_output = expected_input - 1000
        minimum_output = minimum_input - 2000
        row.update(
            index=index,
            route_fee_bps=1 if index == 0 else 0,
            expected_input_base=expected_input,
            floor_input_base=minimum_input,
            expected_output_base=expected_output,
            minimum_output_base=minimum_output,
        )
        is_external = row["provider"] == "across_intent_bridge"
        if row["kind"] == "direct_swap":
            source_ep = f"{row['chain']}:{row['from']}"
            destination_ep = f"{row['chain']}:{row['to']}"
            action = "swap"
        else:
            source_asset = row.get("from_asset") if is_external else row["asset"]
            destination_asset = row.get("to_asset") if is_external else row["asset"]
            source_ep = f"{row['from']}:{source_asset}"
            destination_ep = f"{row['to']}:{destination_asset}"
            action = "bridge"
        summary_steps.append({
            "index": index, "action": action, "provider": row["provider"],
            "from": source_ep, "to": destination_ep,
            "expected_input_base": str(expected_input), "minimum_input_base": str(minimum_input),
            "expected_output_base": str(expected_output), "minimum_output_base": str(minimum_output),
            "assetfare_fee_bps": row["route_fee_bps"], "direct_protocol": not is_external,
            "external_intent_protocol": is_external, "aggregator_api_used": False,
        })
        external = external or is_external
        expected_input = expected_output
        minimum_input = minimum_output
    handoff = {
        "kind": "caller_operated_rest_prepare",
        "method": "POST",
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
        "note": "Caller-operated; AssetFare never signs or submits.",
    }
    handoff["available"] = True
    handoff["url"] = "https://api.assetfare.dev/v2/prepare"
    handoff["options"] = [
            {
                "kind": "one_shot_first_unsigned_bundle", "method": "POST",
                "url": "https://api.assetfare.dev/v2/prepare",
                "requires_explicit_caller_approval": True,
                "requires_public_wallet_addresses": True,
                "assetfare_never_signs_submits_or_auto_calls": True,
            },
            {
                "kind": "caller_approved_full_workflow_session", "method": "POST",
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
    ]
    execution = {
        "supported": True,
        "first_unsigned_action_supported": True,
        "future_actions_require_verified_receipts": True,
    }
    quote = {
        "status": "capped_public_agent_release",
        "quote_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        "ttl_seconds": 60,
        "as_of": "2026-09-17T00:00:05Z",
        "intent": {"from": from_s, "to": to_s, "amount_usd": 250.0, "estimated_input_base": 1000000},
        "route": {"route": f"{from_s}->{to_s}", "mode": mode, "input_base": 1000000,
                  "expected_output_base": expected_input, "minimum_output_base": minimum_input,
                  "steps": steps_meta, "quote_latency_ms": 12, "aggregator_api_used": False,
                  "external_intent_protocol_used": external,
                  "server_signing": False, "server_submission": False},
        "offer": {
            "expected_receive_amount": 1.02, "estimated_min_receive_amount": 1.0,
            "expected_receive_usd": 249.0, "estimated_min_receive_usd": 247.0,
            "output_symbol": dt, "assetfare_fee_bps": fee, "fee_modeled_bps": fee,
            "fee_collectible_now": fee == 1,
            "fee_collection_steps": [0] if fee == 1 else [],
            "fee_collection": "only_on_eligible_successful_executor_step",
            "estimated_time_seconds": 30,
        },
        "risk": {"non_atomic": True, "fresh_quote_required_each_step": True,
                 "external_intent_protocol_used": external,
                 "provider_internal_dex_aggregation_possible": external,
                 "server_signing": False, "server_submission": False},
        "direct_route_summary": {
            "version": "assetfare-direct-route-summary-v1", "route": f"{from_s}->{to_s}",
            "from": from_s, "to": to_s,
            "classification": "external_intent" if external else "direct_protocol_only",
            "mode": mode, "route_aggregator_used": False,
            "external_intent_protocol_used": external,
            "provider_internal_dex_aggregation_possible": external,
            "assetfare_fee_bps": 1, "fee_collection_step_index": 0,
            "server_signing": False, "server_submission": False,
            "step_count": len(summary_steps), "steps": summary_steps,
        },
        "execution": execution,
        "caller_action_plan_handoff": handoff,
    }
    return _add_continuation(quote)


def _add_continuation(quote):
    quote.pop("continuation_v3", None)
    summary = quote["direct_route_summary"]
    intent = quote["intent"]
    canonical = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    wallets = sorted({ep.split(":", 1)[0] for step in summary["steps"] for ep in (step["from"], step["to"])})
    signer = any(step["provider"] == "circle_cctp" and step["from"].startswith("solana:") for step in summary["steps"])
    modes = ["session"] if summary["step_count"] > 1 else ["one_shot", "session"]
    bounds = {"minimum": str(intent["estimated_input_base"]), "maximum": str(intent["estimated_input_base"])}
    summary_hash = canonical(summary)
    def typed_canonical(value):
        if value is None:return b"n"
        if value is True:return b"t"
        if value is False:return b"f"
        if isinstance(value, int):
            if abs(value)>9007199254740991:raise ValueError("unsafe integer")
            return b"d"+struct.pack(">d",float(value)).hex().encode()
        if isinstance(value,float):
            if value.is_integer() and abs(value)>9007199254740991:raise ValueError("unsafe integer")
            return b"d"+struct.pack(">d",value).hex().encode()
        if isinstance(value,str):
            if any(0xD800<=ord(character)<=0xDFFF for character in value):raise ValueError("invalid unicode")
            encoded=value.encode();return b"s"+str(len(encoded)).encode()+b":"+encoded
        if isinstance(value,list):return b"a"+str(len(value)).encode()+b":["+b"".join(map(typed_canonical,value))+b"]"
        items=sorted(value.items(),key=lambda item:item[0].encode())
        return b"o"+str(len(items)).encode()+b":{"+b"".join(typed_canonical(key)+typed_canonical(item) for key,item in items)+b"}"

    payload = copy.deepcopy(quote)
    summary_steps = payload["direct_route_summary"]["steps"]
    raw_steps = payload["route"]["steps"]
    payload["intent"]["estimated_input_base"] = summary_steps[0]["expected_input_base"]
    payload["route"]["input_base"] = summary_steps[0]["expected_input_base"]
    payload["route"]["expected_output_base"] = summary_steps[-1]["expected_output_base"]
    payload["route"]["minimum_output_base"] = summary_steps[-1]["minimum_output_base"]
    for raw, exact in zip(raw_steps, summary_steps):
        raw["expected_input_base"] = exact["expected_input_base"]
        raw["floor_input_base"] = exact["minimum_input_base"]
        raw["expected_output_base"] = exact["expected_output_base"]
        raw["minimum_output_base"] = exact["minimum_output_base"]
    payload_hash = hashlib.sha256(typed_canonical(payload)).hexdigest()
    payload_spec = "sha256(AssetFare typed-canonical-v1 bytes of the quote without continuation_v3 after exact base-unit substitution: n=null; t/f=boolean; d=<IEEE-754 binary64 big-endian 16 lowercase hex> for each finite JSON number; s=<UTF-8 byte length>:<Unicode scalar text with lone surrogates forbidden>; a=<count>:[items]; o=<count>:{UTF-8-byte-sorted string-key/value pairs}; every non-substituted integral JSON number must be within +/-9007199254740991; substituted paths are intent.estimated_input_base, route.input_base, route.expected_output_base, route.minimum_output_base, and every route.steps[i].expected_input_base/floor_input_base/expected_output_base/minimum_output_base from direct_route_summary exact decimal strings)"
    claim = {
        "version":"assetfare-quote-bound-continuation-v3", "quote_id":quote["quote_id"],
        "issued_at":"2026-09-17T00:00:00.000Z", "expires_at":"2026-09-17T00:01:00.000Z",
        "ttl_seconds":"60", "intent":{"from":intent["from"],"to":intent["to"],"amount_usd_decimal":"250","estimated_input_base":str(intent["estimated_input_base"])},
        "direct_route_summary_sha256":summary_hash,"quote_payload_sha256":payload_hash,"quote_payload_sha256_spec":payload_spec,"input_base_bounds":bounds,
        "minimum_output_base":str(quote["route"]["minimum_output_base"]),"required_wallet_chains":wallets,
        "event_signer_public_required":signer,"step_count":str(summary["step_count"]),"allowed_modes":modes,
        "server_signing":False,"server_submission":False,
    }
    quote["continuation_v3"] = {
        "version":"assetfare-quote-bound-continuation-v3","enforcement":"server_enforced_quote_binding",
        "selection_status":"unranked_candidate","automatic_selection_forbidden":True,"caller_approved_boolean_is_not_human_proof":True,
        "quote_id":quote["quote_id"],"quote_fingerprint":canonical(claim),
        "quote_fingerprint_spec":"sha256(UTF-8 sorted-key compact JSON of quote_fingerprint_claim; every numeric claim is a non-exponent decimal string)",
        "quote_fingerprint_claim":claim,"issued_at":claim["issued_at"],"expires_at":claim["expires_at"],"ttl_seconds":60,
        "intent":dict(intent),"direct_route_summary_sha256":summary_hash,"quote_payload_sha256":payload_hash,"quote_payload_sha256_spec":payload_spec,"input_base_bounds":bounds,
        "minimum_output_base":claim["minimum_output_base"],"required_wallet_chains":wallets,"event_signer_public_required":signer,
        "step_count":summary["step_count"],"recommended_mode":"session" if summary["step_count"]>1 else "one_shot_or_session",
        "allowed_modes":modes,"session_header":{"name":"X-AssetFare-Session-Token","required_for":"session","caller_generated":True,"minimum_entropy_bits":256,"server_returns_raw_value":False},
        "idempotency":{"required":True,"field":"idempotency_key","pattern":"^[A-Za-z0-9._:-]{8,128}$","scope":"quote_and_selected_mode"},
        "approval_v3_required_fields":["direct_route_summary_sha256","idempotency_key","maximum_input_base","minimum_output_base","quote_fingerprint","quote_id","selected_mode","selection_status","version"],
        "legacy_handoff_enforcement":"legacy_advisory","server_signing":False,"server_submission":False,
    }
    return quote


def _fixed_utcnow():
    from datetime import datetime, timezone

    return datetime(2026, 9, 17, 0, 0, 10, tzinfo=timezone.utc)


def test_route_matrix_counts():
    routes = _enumerate_routes()
    assert len(routes) == 76
    executable = [r for r in routes if r[0] not in SOURCE_ONLY]
    blocked = [r for r in routes if r[0] in SOURCE_ONLY]
    assert len(executable) == 72
    assert len(blocked) == 4
    assert sorted(f"{a}:{b}->{c}:{d}" for a, b, c, d in blocked) == [
        "optimism:USDC->arbitrum:USDC",
        "optimism:USDC->base:USDC",
        "polygon:USDC->arbitrum:USDC",
        "polygon:USDC->base:USDC",
    ]


def test_e2e_76_route_matrix():
    from assetfare_quote_tool import AssetFareQuoteTool

    routes = _enumerate_routes()
    executed_full = 0
    for sc, st, dc, dt in routes:
        # 1) quote (all 76)
        qs = _Session([_Resp(_quote_payload(sc, st, dc, dt))])
        q = AssetFareQuoteTool(session=qs, monotonic=clk(), utcnow=_fixed_utcnow)
        quote = q.forward(sc, st, dc, dt, 250)
        assert quote["from"] == f"{sc}:{st}" and quote["to"] == f"{dc}:{dt}"

        # Every route executes through the caller-approved multi-step lifecycle.
        assert quote["source_only"] is (sc in SOURCE_ONLY)
        assert quote["execution_supported"] is True
        wallets = {sc: WALLET_ADDR[sc], dc: WALLET_ADDR[dc]}
        # 2) prepare one-shot bundle
        ppr = _Session([prepare_bundle_resp()])
        bundle = prepare_tool(ppr).forward(True, sc, st, dc, dt, 250, wallets, approval("one_shot"))
        assert bundle["action_prepared"] is True and bundle["server_signs_or_submits"] is False
        # 3) full session lifecycle on one shared FakeServer
        srv = FakeServer()
        created = create_tool(srv).forward(True, sc, st, dc, dt, 250, wallets, TOKEN, "key-e2e-0001", approval("session", "key-e2e-0001"))
        sid = created["session_id"]
        assert get_tool(srv).forward(TOKEN, sid)["session_id"] == sid
        assert observe_source_tool(srv).forward(TOKEN, sid, "key-e2e-0002", [TX_SRC])["session_id"] == sid
        assert observe_output_tool(srv).forward(TOKEN, sid, "key-e2e-0003", TX_OUT)["session_id"] == sid
        assert refresh_tool(srv).forward(TOKEN, sid, "key-e2e-0004")["session_id"] == sid
        executed_full += 1

    assert executed_full == 76
