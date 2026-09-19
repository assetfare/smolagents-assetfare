# Privacy

This tool is a **non-custodial** AssetFare v2 action-plan client. It never receives
a private key, seed, or signed transaction, and it never signs or submits.

## What is sent
- **Only** to the fixed origin `https://api.assetfare.dev` over HTTPS. Any other
  base URL is rejected before a request is made.
- The caller-supplied fields for the specific step (route + PUBLIC wallet addresses
  for prepare/create; the caller-owned session capability token in the
  `X-AssetFare-Session-Token` header; already-submitted transaction hashes for the
  observe steps; an idempotency key). Nothing else is added.

## What is NOT sent or collected
- No private key, seed phrase, mnemonic, or signed transaction — these are rejected
  before any network call.
- No `Authorization` header or ambient credential; `trust_env` is forced off.
- No user identity, email, or account identifier is added by the tool.

## Fail-closed
- Any response claiming the server signs or submits, or that omits the required
  unsigned-action / session fields, raises a single fixed sanitized error.
