---
title: AssetFare Refresh Action Tool
emoji: ♻️
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

# AssetFare Refresh Action Tool (smolagents)

An **explicit caller-approved** [smolagents](https://github.com/huggingface/smolagents)
`Tool` that replaces an expired, **UNSUBMITTED** session action with a fresh
quote-bound unsigned action (`POST /v2/session/{id}/refresh-action`) for the caller
to verify, sign, and submit.

- Never signs, never submits, never auto-chains.
- Requires the caller-owned session token (header only), the `session_id` and an
  `idempotency_key`.
- `server_signs_or_submits` is always `false`.

## Inputs

`session_token`, `session_id`, `idempotency_key`.

## Output (object)

The refreshed, validated session workflow-state; fails closed on any server
signing/submission claim.

## Source

https://github.com/odaiin/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
