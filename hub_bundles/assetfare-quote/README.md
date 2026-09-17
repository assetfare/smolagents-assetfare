---
title: AssetFare Quote Tool
emoji: 🧭
colorFrom: indigo
colorTo: blue
sdk: gradio
app_file: app.py
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
- **Surface:** 4 chains (solana, base, arbitrum, robinhood), 9 `(chain, token)`
  asset endpoints, 72 directed routes, amount **$1–$1000**.
- **Never** authenticates a wallet, opens a session, prepares an unsigned action,
  signs, or submits. The server itself never signs or submits; the tool
  **fails closed** on any response that claims otherwise.

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
      revision="<reviewed commit SHA>",   # pin what you audited
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

quote = load_tool("odaiin/assetfare-quote", trust_remote_code=True, revision="<reviewed SHA>")
agent = CodeAgent(tools=[quote], model=InferenceClientModel())
agent.run("Get an AssetFare quote to convert $250 from Solana SOL to Base ETH.")
```

Direct call:

```python
result = quote(
    from_chain="solana", from_token="SOL",
    to_chain="base",    to_token="ETH",
    amount_usd=250,
)
```

## Inputs

| name | type | notes |
|------|------|-------|
| `from_chain` | string | one of `solana`, `base`, `arbitrum`, `robinhood` |
| `from_token` | string | token symbol on the source chain (e.g. `SOL`, `ETH`, `USDC`, `USDG`) |
| `to_chain`   | string | destination chain |
| `to_token`   | string | destination token symbol |
| `amount_usd` | number | 1–1000 inclusive; source and destination must differ |

## Output (object)

Validated fields only: `from`, `to`, `amount_usd`, `output_symbol`,
`expected_receive_amount`, `estimated_min_receive_amount`,
`expected_receive_usd`, `estimated_min_receive_usd`, `assetfare_fee_bps`,
`estimated_time_seconds`, `non_atomic`, `quote_id`, `as_of`, `ttl_seconds`,
`execution_supported`, `server_signs_or_submits` (always `false`).

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

## License

[MIT](LICENSE).
