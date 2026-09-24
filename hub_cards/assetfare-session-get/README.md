---
title: AssetFare Session Get Tool
emoji: 🔎
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

# AssetFare Session Get Tool (smolagents)

A **read-only** [smolagents](https://github.com/huggingface/smolagents) `Tool` that
reads a caller-owned AssetFare session: `GET /v2/session/{session_id}`. Returns the
current workflow state and current unsigned action.

- Requires the caller-owned **session capability token** (sent only in the
  `X-AssetFare-Session-Token` header) and the `session_id` UUID.
- Never signs, submits, or moves funds; `server_signs_or_submits` is always `false`.

## Inputs

`session_token` (caller-owned; not a private key), `session_id` (UUID from create).

## Output (object)

The validated session workflow-state; fails closed on any server signing/submission
claim.

## Use it in an agent

```python
from smolagents import load_tool
get = load_tool(
    "odaiin/assetfare-session-get",
    trust_remote_code=True,
    revision="cf03a26155aba8804aa38c1a4ed7c2c410fe9d1a",
)
state = get(session_token="<caller-owned-token>", session_id="<uuid>")
```

## Source

https://github.com/assetfare/smolagents-assetfare · [MIT](LICENSE) · [PRIVACY.md](PRIVACY.md)
