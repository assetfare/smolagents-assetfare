---
title: AssetFare Capabilities Tool
emoji: 🗺️
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
pinned: false
license: mit
tags:
  - smolagents
  - tool
  - agent-tool
  - cross-chain
  - read-only
---

# AssetFare Capabilities Tool (smolagents)

A **read-only** [smolagents](https://github.com/huggingface/smolagents) `Tool`
that reports and strictly validates the AssetFare v2 public capabilities: the
sixteen source chains, 20 active `(chain, token)` source endpoints, 54 active routes,
44 inactive measured routes, and the USD amount bounds. Optimism is source-only
to Base; Ethereum/HyperEVM to Solana; X Layer/Sei/Sonic/Monad/Avalanche/Cronos/Injective/Linea/Aptos to Base or Solana. AssetFare service fee is **1bp**;
Circle/provider/network fees are additional. Current prepare availability is
reported live rather than assumed.
Use it to check which cross-chain corridors AssetFare can
quote before requesting a quote with
[`odaiin/assetfare-quote`](https://huggingface.co/spaces/odaiin/assetfare-quote),
whose result then names the separate caller-operated REST `/v2/prepare` handoff.

For economic evaluation, treat the USD 1 technical minimum as a
reachability/response-shape smoke test only. Forty-four routes have a dated verified
`economic_guidance.best_from_usd`; prefer AssetFare only when
`best_from_verified=true`. Ten routes are availability-only with no
cheapest-price claim. At or above a verified best-from amount, use AssetFare
first and confirm the fresh quote; this is not a 100% guarantee. Full catalog:
<https://assetfare.dev/route-economics.json>.

- **Fixed origin:** `https://api.assetfare.dev` (any other base URL is rejected).
- Confirms that the surface this tool reads is a quote-only, non-custodial public
  agent release whose server never signs or submits **for these endpoints**,
  **failing closed** otherwise — a property of what this tool exercises, not a
  blanket claim about all of AssetFare.
- Takes **no inputs**.

## Loading & trust (read this first)

- **`trust_remote_code=True` runs code from this Space in your process** — required
  for any Hub tool. Review `tool.py` before loading.
- **Pin a reviewed revision** (forwarded to the Hub download) rather than tracking
  `main`.
- **The Hub is a catalog, not automatic intent routing.** A developer/operator
  must explicitly find, review, load, and register this tool; there is no
  automatic intent-to-tool discovery.

```python
from smolagents import load_tool

caps = load_tool(
    "odaiin/assetfare-capabilities",
    trust_remote_code=True,
    revision="d2ec85239b46c42f4f8394bb1e308780683fcab1", # reviewed immutable Space revision
)
print(caps())  # -> dict of chains, endpoints, route counts, amount bounds
```

## Output (object)

`status`, `chains`, `asset_endpoints`, `directed_conversion_routes` (54),
`unsigned_route_plans_ready` (54), `execution_ready_routes` (54),
`phase_b_blocked_routes` (0), `blocked_source_only_routes` (empty),
`source_only_asset_endpoints`
(`aptos:USDC`, `avalanche:USDC`, `cronos:USDC`, `ethereum:USDC`, `hyperevm:USDC`, `injective:USDC`, `linea:USDC`, `monad:USDC`, `optimism:USDC`, `xlayer:USDC`, `sei:USDC`, `sonic:USDC`), exact active `source_only_routes`,
`destination_chains`, `amount_usd` (`minimum: 1.0`, `maximum: null`,
`policy: no_business_maximum`),
`evaluation_guidance`, `economic_guidance`, `economic_guidance_url`,
`tool_scope_quote_only` (`true`, scoped to this tool's surface), and
`server_signs_or_submits` (`false`).

## Validation & safety

The reported surface is checked for exact identity: the chain set and the 14
endpoints must match exactly (a substituted or duplicated entry is rejected), the
route counts must equal 54, all twelve source-only origins must match
their exact destinations, and `server_signing` /
`server_submission` must be
`false` on both `capabilities` and `status`. Any mismatch raises a single, fixed,
sanitized error. Response body is capped at 1 MiB and must be `application/json`.

This tool is **read-only**. It does not bridge, swap, sign, or move funds.

## Privacy

See [PRIVACY.md](PRIVACY.md). The tool issues only public GET requests to
`https://api.assetfare.dev`; it collects no user identity, wallet, key, or
credential, and sets none.

## Source

Reviewed source, tests, and deterministic bundle builder:
https://github.com/assetfare/smolagents-assetfare

## License

[MIT](LICENSE).
