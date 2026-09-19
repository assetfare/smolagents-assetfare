---
title: AssetFare Observe Source Tool
emoji: 📥
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

# AssetFare Observe Source Tool (smolagents)

An **explicit caller-approved** [smolagents](https://github.com/huggingface/smolagents)
`Tool` that observes the caller's **ALREADY-submitted** source transaction hashes
(`POST /v2/session/{id}/observe-source`) and advances the receipt-driven workflow.

- Observes only caller-submitted tx hashes; it **never submits** a transaction and
  never auto-chains.
- Requires the caller-owned session token (header only), the `session_id`, an
  `idempotency_key`, and 1–8 already-submitted source transaction hashes.
- `server_signs_or_submits` is always `false`.

## Inputs

`session_token`, `session_id`, `idempotency_key`, `transaction_hashes` (array, 1–8).

## Output (object)

The advanced, validated session workflow-state; fails closed on any server
signing/submission claim.

## Source

https://github.com/odaiin/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
