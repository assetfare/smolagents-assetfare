---
title: AssetFare Observe Output Tool
emoji: 📤
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

# AssetFare Observe Output Tool (smolagents)

An **explicit caller-approved** [smolagents](https://github.com/huggingface/smolagents)
`Tool` that observes the caller's **ALREADY-produced** destination / bridge output
(`POST /v2/session/{id}/observe-output`) and advances the receipt-driven workflow.

- Observes only caller output; it **never submits** a transaction and never
  auto-chains.
- Requires the caller-owned session token (header only), the `session_id` and an
  `idempotency_key`; `transaction_hash` is optional.
- `server_signs_or_submits` is always `false`.

## Inputs

`session_token`, `session_id`, `idempotency_key`, `transaction_hash` (optional).

## Output (object)

The advanced, validated session workflow-state; fails closed on any server
signing/submission claim.

## Source

https://github.com/odaiin/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
