# Privacy

`assetfare_new_session_capability` is a **local-only** token generator. It makes
**no network call** of any kind.

## What is sent
- Nothing. The tool never contacts `https://api.assetfare.dev` or any other host.

## What it returns
- A freshly generated, high-entropy (>=256-bit CSPRNG) url-safe session capability
  token, marked **sensitive**. It is a bearer capability, **not** a private key,
  and cannot move funds.

## Caller responsibility
- Treat the token like a bearer credential: never log, share, telemetry, or persist
  it in plaintext. Store it only as long as the session is active. It is passed to
  the AssetFare session tools only in the `X-AssetFare-Session-Token` header; the
  server stores only its hash and never returns it.
