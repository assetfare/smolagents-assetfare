---
title: AssetFare Prepare Tool
emoji: 🧾
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
  - cross-chain
  - prepare
---

# AssetFare Prepare Tool (smolagents)

An **explicit caller-approved**, non-custodial [smolagents](https://github.com/huggingface/smolagents)
`Tool` that performs the one-shot `POST /v2/prepare` for a route whose fresh quote reports current availability
AssetFare route and returns a bounded **FIRST unsigned action bundle** for the
caller to verify, sign, and submit with their **own** wallet.

- **Never auto-called.** This is the tool named by a quote's
  `caller_action_plan_handoff`; a developer/operator invokes it deliberately. A
  quote never triggers it.
- **caller_approved gate.** Rejects anything but the literal boolean `true` before
  any network call. The boolean alone is not human-proof approval.
- **Strict quote binding.** Requires the exact nine-field `approval_v3` built
  locally after explicit unranked selection. `selected_mode` must be `one_shot`;
  use this path only when the fresh continuation allows it. Multi-step routes are
  session-only. Never invoke both prepare and session for one selection.
- **Fail-closed source-only boundary.** Polygon/Optimism are accepted only as
  native-USDC origins to Base/Arbitrum USDC; other directions fail before network.
- **Public wallets only.** The `wallets` map must contain PUBLIC addresses for the
  route's chains; any private key / seed / signed transaction anywhere in the input
  is rejected before any network call.
- **event_signer_public** is required only for Solana-CCTP: generate a fresh ephemeral Solana keypair locally, send only its public key, keep the private key client-side, and use it to co-sign the returned unsigned event-account transaction.
- AssetFare **never signs or submits**; `server_signs_or_submits` is always `false`.
- Before calling this tool, fetch fresh AssetFare and competitor quotes at the
  actual intended amount. USD 1 is smoke-only, USD 50 is only the lowest
  observed native-USDC winning bucket, and the USD 1,000 example below is not an
  approval or guarantee that AssetFare is cheapest.

## Use it in an agent

```python
from smolagents import load_tool
prepare = load_tool(
    "odaiin/assetfare-prepare",
    trust_remote_code=True,
    revision="9c71dd6b1aa51484237d17d69090b599baf8fe3c",
)
bundle = prepare(
    # Set this only after the caller explicitly approves this exact action.
    caller_approved=True,
    from_chain="solana", from_token="SOL",
    to_chain="base", to_token="ETH",
    amount_usd=1000,
    wallets={"solana": "<public-sol-address>", "base": "0x<public-evm-address>"},
    approval_v3={
        "version": "assetfare-quote-bound-approval-v3",
        "quote_id": "<fresh-quote-id>", "quote_fingerprint": "<64-hex>",
        "selection_status": "selected", "selected_mode": "one_shot",
        "maximum_input_base": "<caller-bound>", "minimum_output_base": "<caller-bound>",
        "direct_route_summary_sha256": "<64-hex>", "idempotency_key": "local-choice-001",
    },
    # Generate locally; pass only the public key. Never pass its private key.
    event_signer_public="<fresh-ephemeral-public-solana-key>",
)
```

## Inputs

| name | type | notes |
|------|------|-------|
| `caller_approved` | boolean | must be literal `true` |
| `from_chain`/`from_token`/`to_chain`/`to_token` | string | executable route (no polygon/optimism source) |
| `amount_usd` | number | actual intended finite value; minimum 1 is smoke-only; no business maximum; 1,000 is representative, not guaranteed |
| `wallets` | object | route chains -> PUBLIC addresses only |
| `approval_v3` | object | exact nine fields from the explicitly selected fresh quote; mode `one_shot` |
| `event_signer_public` | string (optional) | Solana-CCTP only; ephemeral PUBLIC key; matching private key stays client-side for co-signing |

## Output (object)

`bundle` (the validated upstream unsigned-action bundle), plus `fresh_requoted`,
`caller_approval_honored`, `action_prepared`, `transaction_signed` (`false`),
`transaction_submitted` (`false`), `caller_must_verify_sign_and_submit` (`true`),
`server_signs_or_submits` (`false`). The bundle must explicitly assert it is neither
signed nor submitted, else the call fails closed.

## Source

https://github.com/assetfare/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
