---
title: AssetFare Quote Tool
emoji: 🧭
colorFrom: indigo
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: mit
tags:
  - smolagents
  - tool
  - agent-tool
  - cross-chain
  - quote
  - read-only
---

# AssetFare Quote Tool (smolagents)

A **read-only, quote-only** [smolagents](https://github.com/huggingface/smolagents)
`Tool` that fetches a non-custodial cross-chain conversion **quote** from the
AssetFare v2 API. It is meant to be **discovered and loaded by agents**, not used
as a human demo.

- **Fixed origin:** `https://api.assetfare.dev` (any other base URL is rejected).
- **Surface:** 6 source chains (solana, base, arbitrum, robinhood, polygon,
  optimism), 11 `(chain, token)` source endpoints, 76 directed routes, and finite
  numeric USD amounts of at least **$1**, with no business maximum. Polygon and Optimism are native-USDC **source-only** to Base or
  Arbitrum USDC. All paths are usable only while the live quote reports them
  available. AssetFare service fee is 1bp; Circle/provider/network fees are
  additional and the quote exposes total token-path cost.
- **Never** authenticates a wallet, opens a session, prepares an unsigned action,
  signs, or submits. The server itself never signs or submits; the tool
  **fails closed** on any response that claims otherwise.

## Economic evaluation

- **$1 is only the technical minimum** for reachability/response-shape smoke
  tests; do not use it to judge economics.
- Start native-USDC evaluation at **$50**. This is the lowest observed winning
  bucket, not a guarantee for any route or time.
- **$1,000** is the primary representative example, not a default transaction or
  promise of savings.
- Always fetch fresh AssetFare and competitor quotes at the actual intended
  amount. Compare total cost, expected/minimum receive, ETA, and risk; never
  assume AssetFare is always cheapest.

## Loading & trust (read this first)

- **`trust_remote_code=True` runs code from this Space in your process.** That is
  required for *any* Hub tool and is not specific to this one. Review `tool.py`
  before loading and only load a revision you have read.
- **Pin a reviewed revision.** `load_tool` forwards `revision` to the Hub
  download, so pin the exact commit SHA you reviewed rather than tracking the
  moving `main`:

  ```python
  from smolagents import load_tool
  quote = load_tool(
      "odaiin/assetfare-quote",
      trust_remote_code=True,
      revision="<pin-reviewed-6chain-SHA-after-publish>", # pin the reviewed 6-chain SHA only AFTER publish (do not advertise a pre-Optimism SHA as canonical)
  )
  ```

- **The Hub is a catalog, not automatic intent routing.** An agent does not
  silently discover and run this tool. A developer/operator must explicitly find
  it (by the `smolagents`+`tool` tag or by name), review it, load it with the two
  acknowledgements above, and add it to an agent's tool list. There is no
  automatic intent-to-tool discovery.

## Use it in an agent

```python
from smolagents import load_tool, CodeAgent, InferenceClientModel

quote = load_tool(
    "odaiin/assetfare-quote",
    trust_remote_code=True,
    revision="<pin-reviewed-6chain-SHA-after-publish>",
)
agent = CodeAgent(tools=[quote], model=InferenceClientModel())
agent.run("Get an AssetFare quote to convert $1,000 from Solana SOL to Base ETH.")
```

Direct call:

```python
result = quote(
    from_chain="solana", from_token="SOL",
    to_chain="base",    to_token="ETH",
    amount_usd=1000,
)
```

## Inputs

| name | type | notes |
|------|------|-------|
| `from_chain` | string | one of `solana`, `base`, `arbitrum`, `robinhood`, `polygon`, `optimism`; Polygon and Optimism are native-USDC source-only to Base/Arbitrum USDC |
| `from_token` | string | token symbol on the source chain (e.g. `SOL`, `ETH`, `USDC`, `USDG`) |
| `to_chain`   | string | destination chain |
| `to_token`   | string | destination token symbol |
| `amount_usd` | number | actual intended finite value; minimum 1 is smoke-only; no business maximum; 1,000 is representative, not guaranteed; source and destination must differ |

## Output (object)

Validated fields only: `from`, `to`, `amount_usd`, `output_symbol`,
`expected_receive_amount`, `estimated_min_receive_amount`,
`expected_receive_usd`, `estimated_min_receive_usd`, `assetfare_fee_bps`,
`fee_modeled_bps`, `fee_collectible_now`, `assetfare_fee_conditional`,
`fee_collection_steps`, `fee_collection`, `fee_note`, `estimated_time_seconds`,
`non_atomic`, `quote_id`, `as_of`, `ttl_seconds`, `source_only`,
`execution_supported`, `execution_blocker`, `server_signs_or_submits` (always
`false`), and `caller_action_plan_handoff`.

**AssetFare service fee — EXACTLY `1bp` on every route; not total cost.** A 0bp, 8bp, 2bp, or negative service fee fails
closed. It is **conditional**, never an unconditional flat charge: the 1bp fee is
collected only on **one** eligible **successful atomic action** named in
`fee_collection_steps`; any mismatch fails closed. The
constant `fee_collection` is always
`"only_on_eligible_successful_executor_step"`. `fee_modeled_bps` is what AssetFare
models; `fee_collectible_now` is `true` exactly for a `1`bp route. Circle,
provider, and network fees are additional. `cost_summary` contains expected and
maximum token-path cost; unpriced gas stays explicit. `assetfare_fee_conditional`
is `true` iff the service fee is positive.

**`caller_action_plan_handoff` — FAIL-CLOSED passthrough (no local fallback).** The
upstream `/v2/quote` handoff is passed through **verbatim after strict validation**;
there is **no** synthesized local descriptor. A missing / null / array / extra-field
/ wrong-field handoff is a real contract regression and is **rejected**. For an
a route the fresh quote reports available it carries `available: true`, `url:
https://api.assetfare.dev/v2/prepare`, and **two options** — a one-shot
`POST /v2/prepare` first unsigned bundle and a full caller-approved
`POST /v2/session` lifecycle (create / `GET {id}` / observe-source / observe-output
/ refresh-action). Its invariants: `requires_explicit_caller_approval: true`,
`requires_public_wallet_addresses: true`, `requires_fresh_requote: true`,
`automatic_prepare_call_forbidden: true`, `assetfare_server_signing: false`,
`assetfare_server_submission: false`, `caller_must_verify_sign_and_submit: true`,
and the exact **8-field** `request_fields`
`["caller_approved", "from_chain", "from_token", "to_chain", "to_token",
"amount_usd", "wallets", "event_signer_public"]`. The four directional
Polygon/Optimism source-only routes carry the same available two-option handoff.
This tool never calls `/v2/prepare` or `/v2/session`, never receives a private key,
and never signs or submits.

## Companion action tools

Execution is a **separate, explicit, caller-approved** step, exposed as separate
Hub tools that this quote tool only names (it never auto-calls them):
`assetfare_new_session_capability` (local-only token; no network),
`assetfare_prepare` (one-shot `/v2/prepare`), and the full session lifecycle
`assetfare_session_create` / `assetfare_session_get` / `assetfare_observe_source` /
`assetfare_observe_output` / `assetfare_refresh_action`. All require an explicit
`caller_approved: true` and the caller's own PUBLIC wallet addresses; none sign or
submit. Source-only (Polygon/Optimism) routes are fail-closed rejected there.

## Validation & safety

Every response is strictly validated before it is returned. The call raises a
single, fixed, sanitized error (no upstream text) when anything is off:

- route label must equal the requested `from->to` corridor;
- `as_of` must be an RFC3339 **timezone-aware** timestamp — a naive or date-only
  value is rejected; a quote whose `as_of + ttl` has passed (stale) or whose
  `as_of` is more than 5 minutes in the future (skew/forgery) is rejected;
- offer amounts must satisfy `min > 0` and `expected >= min` (native and USD);
- `server_signing` / `server_submission` must be `false` on every section, and
  `fresh_quote_required_each_step` must be `true`;
- response body is capped at 1 MiB and must be `application/json`.

This is a **quote oracle**, not an executor. It does **not** bridge, swap, sign,
or move funds. Any actual transfer remains the user's own wallet action, taken
separately with explicit user approval.

## Privacy

See [PRIVACY.md](PRIVACY.md). The tool sends only the requested route and USD
amount to `https://api.assetfare.dev`; it collects no user identity, wallet, key,
or credential, and sets none.

## Source

Reviewed source, tests, and deterministic bundle builder:
https://github.com/assetfare/smolagents-assetfare

## License

[MIT](LICENSE).
