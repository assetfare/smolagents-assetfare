---
title: AssetFare Session Capability Token
emoji: 🔑
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

# AssetFare Session Capability Token (smolagents)

A **local-only** [smolagents](https://github.com/huggingface/smolagents) `Tool`
that generates ONE caller-owned AssetFare session capability token. It makes
**no network call**, touches no wallet, and returns nothing about AssetFare's
remote state.

- **Zero network.** Purely local CSPRNG generation.
- **Token:** >=256-bit, url-safe, 43–128 chars, marked `sensitive_capability`.
  It is **not** a private key and cannot move funds.
- **Caller owns it.** Because the caller (not the server) holds the token, a lost
  `assetfare_session_create` response can be retried with the **same token +
  idempotency_key** to recover the **same** session (crash recovery). The server
  stores only the token's hash and never returns it.

## Why a separate tool (not auto-generated inside create)

If `session_create` generated the token internally, a lost create response would
force a retry with a *different* token and create a duplicate session. So the token
is minted here first, kept by the caller, and passed as **required** input to
`assetfare_session_create` and every session read/observe/refresh call.

## Use it in an agent

```python
from smolagents import load_tool
new_token = load_tool(
    "odaiin/assetfare-new-session-capability",
    trust_remote_code=True,
    revision="561c6b23da41936757087054ca32e472f4e9a399",
)
cap = new_token()          # {"session_token": "...", "token_bits": 256, ...}
```

## Output (object)

`session_token`, `token_bits` (256), `token_length`, `sensitivity`
(`sensitive_capability`), `is_private_key` (`false`), `network_calls` (`0`),
`usage`, `server_signing` (`false`), `server_submission` (`false`).

## Safety

Never log, share, or persist the token in plaintext. It is a bearer credential,
not a private key. This tool does not execute, bridge, swap, sign, or move funds.

## Source

https://github.com/assetfare/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
