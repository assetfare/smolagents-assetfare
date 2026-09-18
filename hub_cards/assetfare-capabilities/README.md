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
five source chains, the 10 `(chain, token)` source endpoints, the 74 directed
conversion routes, and the USD amount bounds. Use it to check which cross-chain
corridors AssetFare can quote before requesting a quote with
[`odaiin/assetfare-quote`](https://huggingface.co/spaces/odaiin/assetfare-quote).

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
    revision="995b5c5be4d88a6c94241ef22ac3a6581dfa8cdb", # previous 72-route release; not Polygon-capable
)
print(caps())  # -> dict of chains, endpoints, route counts, amount bounds
```

## Output (object)

`status`, `chains`, `asset_endpoints`, `directed_conversion_routes` (72),
`unsigned_route_plans_ready` (72), `amount_usd_min` (1.0), `amount_usd_max`
(1000.0), `tool_scope_quote_only` (`true`, scoped to this tool's surface), `server_signs_or_submits` (`false`).

## Validation & safety

The reported surface is checked for exact identity: the chain set and the 9
endpoints must match exactly (a substituted or duplicated entry is rejected), the
route counts must equal 72, and `server_signing` / `server_submission` must be
`false` on both `capabilities` and `status`. Any mismatch raises a single, fixed,
sanitized error. Response body is capped at 1 MiB and must be `application/json`.

This tool is **read-only**. It does not bridge, swap, sign, or move funds.

## Privacy

See [PRIVACY.md](PRIVACY.md). The tool issues only public GET requests to
`https://api.assetfare.dev`; it collects no user identity, wallet, key, or
credential, and sets none.

## Source

Reviewed source, tests, and deterministic bundle builder:
https://github.com/odaiin/smolagents-assetfare

## License

[MIT](LICENSE).
