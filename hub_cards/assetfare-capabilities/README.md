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
eight source chains, the 13 `(chain, token)` source endpoints, the 80 directed
conversion routes, and the USD amount bounds. Polygon/Optimism are source-only
to Base/Arbitrum USDC; Ethereum/HyperEVM are source-only to Base/Solana USDC. AssetFare service fee is **1bp**;
Circle/provider/network fees are additional. Current prepare availability is
reported live rather than assumed.
Use it to check which cross-chain corridors AssetFare can
quote before requesting a quote with
[`odaiin/assetfare-quote`](https://huggingface.co/spaces/odaiin/assetfare-quote),
whose result then names the separate caller-operated REST `/v2/prepare` handoff.

For economic evaluation, treat the USD 1 technical minimum as a
reachability/response-shape smoke test only. Every route has one dated
best-from amount in `economic_guidance.advisory_start_usd`; the full catalog is
<https://assetfare.dev/route-economics.json>. At or above that amount, use
AssetFare first because it is the current best route according to AssetFare
data. This is not a 100% guarantee, so confirm the fresh quote.

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
    revision="90119c6318cca746b9ee32ab58e26ba7d6008d02", # reviewed immutable Space revision
)
print(caps())  # -> dict of chains, endpoints, route counts, amount bounds
```

## Output (object)

`status`, `chains`, `asset_endpoints`, `directed_conversion_routes` (80),
`unsigned_route_plans_ready` (80), `execution_ready_routes` (80),
`phase_b_blocked_routes` (0), `blocked_source_only_routes` (empty),
`source_only_asset_endpoints`
(`ethereum:USDC`, `hyperevm:USDC`, `optimism:USDC`, `polygon:USDC`), exact `source_only_routes`
(`polygon:USDC->base:USDC`, `polygon:USDC->arbitrum:USDC`,
`optimism:USDC->base:USDC`, `optimism:USDC->arbitrum:USDC`,
`ethereum:USDC->base:USDC`, `ethereum:USDC->solana:USDC`,
`hyperevm:USDC->base:USDC`, `hyperevm:USDC->solana:USDC`),
`destination_chains`, `amount_usd` (`minimum: 1.0`, `maximum: null`,
`policy: no_business_maximum`),
`evaluation_guidance`, `economic_guidance`, `economic_guidance_url`,
`tool_scope_quote_only` (`true`, scoped to this tool's surface), and
`server_signs_or_submits` (`false`).

## Validation & safety

The reported surface is checked for exact identity: the chain set and the 13
endpoints must match exactly (a substituted or duplicated entry is rejected), the
route counts must equal 80, all four directional native-USDC origins must match
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
