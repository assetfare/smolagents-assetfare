# smolagents-assetfare — non-custodial AssetFare tools for smolagents agents

Public source for nine self-contained [smolagents](https://github.com/huggingface/smolagents)
`Tool` classes that let an agent **load and call** AssetFare's non-custodial
cross-chain surface — read-only quote/capabilities discovery **plus** the explicit,
caller-approved v2 action surface (one-shot `/v2/prepare` and the full `/v2/session`
receipt-driven lifecycle). This is the supported Hub tool path (a Space tagged
`smolagents`+`tool`, whose `tool.py` an agent loads via
`load_tool(repo_id, trust_remote_code=True)`), **not** a human-facing Space promo.
No tool signs, submits, or receives a private key; the action tools are never
auto-called from a quote and require an explicit `caller_approved: true`.

Static Spaces (one per tool; nine total):

- `odaiin/assetfare-quote`, `odaiin/assetfare-capabilities` (read-only)
- `odaiin/assetfare-new-session-capability` (local-only token; no network)
- `odaiin/assetfare-prepare` (one-shot `/v2/prepare`)
- `odaiin/assetfare-session-create`, `-session-get`, `-observe-source`,
  `-observe-output`, `-refresh-action` (full `/v2/session` lifecycle)

| file | what |
|------|------|
| `assetfare_quote_tool.py` | `AssetFareQuoteTool` — validated `POST /v2/quote`, ordered direct-route proof, fail-closed handoff passthrough |
| `assetfare_capabilities_tool.py` | `AssetFareCapabilitiesTool` — validated `GET /v2/capabilities` + `/v2/status` |
| `assetfare_session_capability_tool.py` | `AssetFareNewSessionCapabilityTool` — local-only 256-bit token, **zero network** |
| `assetfare_prepare_tool.py` | `AssetFarePrepareTool` — caller-approved one-shot `POST /v2/prepare` |
| `assetfare_session_tools.py` | `AssetFareSessionCreate/Get/ObserveSource/ObserveOutput/RefreshAction` — full `/v2/session` lifecycle |
| `tests/test_tools.py` | offline mock tests for quote + capabilities (no network) |
| `tests/test_action_tools.py` | offline mock tests for prepare/session/token + 76-route e2e matrix (no network) |
| `tests/test_bundle.py` | builds + loads each Static-Space bundle in a subprocess (no network) |
| `hub/build_bundles.py` | deterministic builder → `hub_bundles/<space>/` (generates `index.html`) |
| `hub_bundles/<space>/` | generated, atomically-uploadable Space bundle (9 spaces) |
| `hub_cards/<space>/README.md` | per-Space Hub card (frontmatter + usage) |
| `BLOCKERS.md` | Hub-model coverage notes for the action/session tools |
| `LICENSE` / `PRIVACY.md` | MIT license / privacy statement |
| `pyproject.toml` | pins + ruff config |

## Guarantees (all tools)

- Fixed origin `https://api.assetfare.dev`; any other base URL rejected (injected
  `requests.Session` included — `trust_env` is forced off). The
  `new_session_capability` token tool makes **no network call** at all.
- Exact surface: 6 source chains, 11 `(chain, token)` source endpoints, **76**
  implemented directed routes, and finite numeric USD amounts of at least $1
  with no business maximum. The $1 technical minimum is only for
  reachability/response-shape smoke tests, never economic comparison. Start
  native-USDC economic evaluation at $50: that is the lowest observed winning
  bucket, not a guarantee. Use $1,000 as the primary representative economic
  example when no intended amount is known. Always fetch fresh AssetFare and
  competitor quotes at the actual intended amount and never assume AssetFare is
  always cheapest. Polygon and Optimism are directional
  native-USDC source-only origins to Base or Arbitrum USDC. Current prepare
  availability is read from the API, not assumed. AssetFare service fee is 1bp;
  Circle/provider/network fees are additional and the quote exposes total
  token-path cost.
- Every quote exposes a validated `direct_route_summary`: the ordered named
  protocols, normalized `chain:asset` endpoints, expected/minimum base-unit
  amounts for every step, and the one exact step index that collects the 1bp
  AssetFare fee. Missing, extra, reordered, discontinuous, or contradictory
  summary data fails closed against the raw route and risk fields.
- Strict response validation, RFC3339 tz-aware freshness (stale + future-skew;
  a trailing `Z` is normalized so it validates on Python 3.10 as well as 3.11+),
  1 MiB cap, single fixed sanitized error (no upstream text leaks). Every failure
  is recorded as a flag/sentinel and the fixed `ValueError` is raised *outside* the
  `except` handler, so the final exception has `__context__ is None` and
  `__cause__ is None` — a bare `raise ... from None` would still leave the upstream
  exception object on `__context__`. Internal budget/size stops use a sentinel, so
  a hostile `iter_content` raising its own `ValueError` is sanitized, not surfaced.
- **AssetFare never signs or submits, and never receives a private key/seed.** The
  quote result carries the caller-operated `caller_action_plan_handoff` as a
  **FAIL-CLOSED passthrough** of the upstream `/v2/quote` handoff — **no local
  fallback**: a missing/null/array/extra/wrong-field handoff is a real contract
  regression and is rejected, never synthesized. For a route the fresh quote reports available it
  carries `available: true`, `url: …/v2/prepare`, and **two options** (one-shot
  `POST /v2/prepare` + full `POST /v2/session` lifecycle), the exact **8-field**
  `request_fields` (`caller_approved` first), and the invariants
  `requires_explicit_caller_approval` / `requires_public_wallet_addresses` /
  `requires_fresh_requote` / `automatic_prepare_call_forbidden` /
  `assetfare_server_signing=false` / `assetfare_server_submission=false` /
  `caller_must_verify_sign_and_submit=true`. Directional source-only routes carry
  the same available caller-approved prepare/session handoff.
- **Fee is EXACTLY `1bp` on every route.** `assetfare_fee_bps` and
  `fee_modeled_bps` must both be 1 (0bp/8bp/2bp/negative rejected), with exactly
  one eligible `fee_collection_steps` index. Plus
  `fee_collectible_now` (true exactly for 1bp routes), and the constant
  `fee_collection = "only_on_eligible_successful_executor_step"`.
- **Direct-route classification is explicit, not inferred by the agent.**
  `direct_protocol_only` means every step is one of the named direct protocols.
  `external_intent` is allowed only for a path containing
  `across_intent_bridge`. `route_aggregator_used=false` means AssetFare did not
  call a market-wide route-aggregator API; it does not claim that a provider has
  no internal routing. Across may internally source or aggregate destination
  liquidity, so those paths explicitly set
  `provider_internal_dex_aggregation_possible=true`.
- **Action tools are explicit and caller-owned.** `assetfare_prepare` and
  `assetfare_session_create` require the literal `caller_approved: true` and the
  route's own PUBLIC wallet addresses (private key/seed/signed material rejected
  before any network call); Polygon/Optimism routes are constrained to native
  USDC sources for Base/Arbitrum USDC destinations. The
  session capability token is **caller-generated** by `new_session_capability`
  (256-bit CSPRNG, marked sensitive, not a private key) and passed as **required**
  input to `session_create` (sent only in the `X-AssetFare-Session-Token` header),
  so a lost create response retried with the same token + idempotency_key recovers
  the **same** session. observe-source/observe-output observe only the caller's
  already-submitted tx hashes; nothing auto-submits or auto-chains. Before
  prepare or session creation, obtain fresh AssetFare and competitor quotes at
  the actual intended amount; the $1,000 representative example is not an
  approval, default transaction amount, or guarantee of savings.
- Self-contained per smolagents `validate_tool_attributes` — each serialises to a
  single `tool.py` via `to_dict()` and round-trips through `from_code` (the
  Hub-load path), asserted in tests.

## Test / lint locally (offline)

```bash
python -m pytest tests/ -q     # 355 passed with SMOLAGENTS_ALT_PYTHON set; otherwise 354 passed + 1 skipped
ruff check .                   # clean (generated hub_bundles/ excluded)
```

The full suite (tools + bundle) is verified on both Python 3.12 and Python 3.10
(the declared floor). It needs no gradio, so both run the whole suite. A fresh
isolated resolution of the bundle deps (`smolagents==1.26.0`, `requests>=2.32.3,<3`)
is `pip-audit`-clean (0 vulnerabilities) on 3.10 and 3.12.

## Reviewed Static-Space bundles

**Static Spaces, no gradio.** `smolagents.load_tool` → `Tool.from_hub` downloads
**only `tool.py`** from the Space repo (`hf_hub_download(repo_type="space",
revision=...)`) and never reads the Space SDK, imports gradio, or runs an app. So
each Space uses the free **`sdk: static`** type with a trivial `index.html` — no
Gradio, no compute, no PRO subscription — and the gradio dependency (and its
transitive vuln surface) is dropped entirely. (This also sidesteps `push_to_hub`,
whose auto-generated Gradio `app.py` calls `launch_gradio_demo`, which `KeyError`s
on `output_type="object"`.)

**How each reviewed Space bundle is built:**

```bash
python hub/build_bundles.py     # regenerates hub_bundles/<space>/ deterministically
                                # (canonicalize() sorts the serialized top-level imports and
                                #  set-literal class attrs, whose order otherwise varies with
                                #  PYTHONHASHSEED and between CPython 3.10/3.12; tool.py bytes
                                #  are then identical on any interpreter/seed, semantics intact;
                                #  cross-seed AND cross-interpreter regressions assert the SHAs)
```

Each `hub_bundles/<space>/` contains exactly the 6-file allowlist a static Space
needs — `tool.py` (the serialized, validated, self-contained tool code),
`index.html` (the static Space `app_file`), `requirements.txt` (the loading
agent's runtime deps: `smolagents==1.26.0`, `requests>=2.32.3,<3` — **no gradio**;
the static Space runs nothing), `README.md` (card with `sdk: static` and
`smolagents`+`tool` tags), `LICENSE`, and `PRIVACY.md`. The owner (authenticated
separately) uploads the whole directory as **one atomic commit** to the Space
(e.g. `huggingface_hub` `upload_folder` / `create_commit`). The agent `load_tool`
path needs only `tool.py`; `index.html` is a secondary human-facing landing page.

## Discovery & loading (a catalog, not automatic routing)

The Hub is a **catalog, not automatic intent discovery**: an agent does not
silently find and run these tools. A developer/operator explicitly finds a tool
(by the `smolagents`+`tool` tag filter or by name), **reviews `tool.py`**, and
loads it:

```python
from smolagents import load_tool

quote = load_tool(
    "odaiin/assetfare-quote",
    trust_remote_code=True,          # required for any Hub tool: runs Space code in-process
    revision="03a062115d9dafad706b7674b3e16c3ed2bfbac6",
)

capabilities = load_tool(
    "odaiin/assetfare-capabilities",
    trust_remote_code=True,
    revision="c88f0e104b6c0ae208bc27fa48d0fe025032cab4",
)
```

`trust_remote_code=True` is mandatory (and inherent to Hub tools); `revision` is
forwarded to the Hub download, so pin a reviewed SHA rather than tracking `main`.
