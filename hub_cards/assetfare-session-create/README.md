---
title: AssetFare Session Create Tool
emoji: 🗂️
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
  - non-custodial
  - session
---

# AssetFare Session Create Tool (smolagents)

An **explicit caller-approved**, non-custodial [smolagents](https://github.com/huggingface/smolagents)
`Tool` that opens one idempotent, receipt-driven `POST /v2/session` for an
route whose fresh quote reports current availability and returns its first workflow state / unsigned action.

- **caller_approved gate** (literal `true`), **public wallets only**, and the
  directional Polygon/Optimism native-USDC source constraint are all enforced
  before any network call, exactly as in the prepare tool.
- **Caller-owned session token is REQUIRED input.** Generate it first with
  `assetfare_new_session_capability` and pass it as `session_token`; this tool does
  **not** generate it. It is sent only in the `X-AssetFare-Session-Token` header.
- **Crash recovery.** Retrying with the **same token + idempotency_key** recovers
  the **same** session (no duplicate). Different token + same key = independent
  session; same token + same key + different request = conflict (server-enforced).
- Never auto-chains, signs, or submits; `server_signs_or_submits` is always `false`.
- Before session creation, fetch fresh AssetFare and competitor quotes at the
  actual intended amount. USD 1 is smoke-only, USD 50 is only the lowest
  observed native-USDC winning bucket, and the USD 1,000 example below is not an
  approval or guarantee that AssetFare is cheapest.

## Use it in an agent

```python
from smolagents import load_tool
new_token = load_tool(
    "odaiin/assetfare-new-session-capability",
    trust_remote_code=True,
    revision="561c6b23da41936757087054ca32e472f4e9a399",
)
create = load_tool(
    "odaiin/assetfare-session-create",
    trust_remote_code=True,
    revision="213573ca301b764e298faddb5420dbe7b590bc9c",
)
cap = new_token()
session = create(
    # Set this only after the caller explicitly approves this exact session.
    caller_approved=True,
    from_chain="solana", from_token="SOL", to_chain="base", to_token="ETH",
    amount_usd=1000,
    wallets={"solana": "<public>", "base": "0x<public>"},
    session_token=cap["session_token"],
    idempotency_key="my-unique-key-001",
    # Generate locally; pass only the public key. Never pass its private key.
    event_signer_public="<fresh-ephemeral-public-solana-key>",
)
```

## Inputs

`caller_approved`, `from_chain`, `from_token`, `to_chain`, `to_token`, `amount_usd`,
`wallets` (public addresses), `session_token` (caller-owned), `idempotency_key`,
`event_signer_public` (Solana-CCTP only: public key of a fresh locally generated ephemeral keypair; keep its private key client-side for co-signing).

## Output (object)

The validated session workflow-state (`session_id`, current unsigned action, ...);
it must assert `server_signing`/`server_submission`/`signed`/`submitted` are all
`false`, else the call fails closed.

## Source

https://github.com/assetfare/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
