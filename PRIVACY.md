# Privacy

The AssetFare smolagents tools are **non-custodial**: the read-only tools
(`assetfare_quote`, `assetfare_capabilities`) plus the explicit, caller-approved
action tools (`assetfare_new_session_capability`, `assetfare_prepare`,
`assetfare_session_create`, `assetfare_session_get`, `assetfare_observe_source`,
`assetfare_observe_output`, `assetfare_refresh_action`). None sign, submit, or
receive a private key or seed.

## What is sent

- **Only** to the fixed origin `https://api.assetfare.dev` over HTTPS. Any other
  base URL is rejected before a request is made.
- `assetfare_new_session_capability`: **nothing** — it makes no network call. It
  only generates a local session capability token.
- `assetfare_capabilities`: a public `GET /v2/capabilities` and `GET /v2/status`
  with no body.
- `assetfare_quote`: a `POST /v2/quote` whose body contains **only** the route
  you request — `from_chain`, `from_token`, `to_chain`, `to_token` — and the USD
  `amount_usd`. Nothing else is added.
- `assetfare_prepare` / `assetfare_session_create`: the route, `amount_usd`, the
  literal `caller_approved: true`, and the caller's **PUBLIC** wallet addresses (and
  an optional PUBLIC `event_signer_public` for Solana-CCTP). Session create also
  sends the caller-owned session capability token — only in the
  `X-AssetFare-Session-Token` header, never in the body — and an `idempotency_key`.
- The session read/observe/refresh tools send the session id, the header token, an
  `idempotency_key`, and (for observe) only the caller's **already-submitted**
  transaction hashes.

## What is NOT sent or collected

- No private key, seed phrase, mnemonic, or signed transaction — these are rejected
  before any network call. Only PUBLIC wallet addresses are ever sent.
- No API key or `Authorization` header; `trust_env` is forced off. The session
  capability token is a sensitive bearer credential, not a private key.
- No user identity, email, or account identifier is added by the tools.

## Transport details you should know

- **Egress metadata.** Every request is an ordinary HTTPS call to
  `https://api.assetfare.dev`, so the following reach that host as a normal
  consequence of making the request: your **client/network IP address**, a
  **User-Agent** header (by default `python-requests/<version>`), standard TLS
  metadata, and a fixed channel marker header **`x-assetfare-channel: smolagents`**
  (a static string identifying the integration, not you). No cookies are set by
  the tools.
- **In-memory cookie jar.** The tools use a `requests.Session`, which keeps an
  **in-memory** cookie jar for the life of the process. If AssetFare ever returned
  a `Set-Cookie`, `requests` would store it in that jar and echo it on subsequent
  calls *within the same session*; it is never written to disk and does not persist
  across process restarts. AssetFare's quote/capability endpoints are not expected
  to set cookies.
- **Injected session (advanced).** You may pass your own `requests.Session` to the
  tool. The tool forces `trust_env = False` on it (so ambient proxy/credential
  environment variables such as `HTTP_PROXY`/`NETRC` are ignored) but it does
  **not** strip anything you configured on that session yourself: any adapters,
  default headers, or pre-existing cookies you set will be used and sent. If you
  inject a session, its contents are your responsibility. With the default (no
  injected session) the tool creates a clean session with `trust_env = False`.

## What is returned

Only the validated quote/capability fields documented in each tool's card. Error
conditions surface as a single fixed, sanitized error code with **no upstream
message or cause**, so no third-party response text is propagated to the agent.

## Boundaries

These tools never authenticate a wallet, open a session, prepare an unsigned
action, sign, or submit, and the AssetFare server itself never signs or submits.
Any actual on-chain transfer is a separate action taken by the user's own wallet,
outside these tools, and requires the user's explicit approval.

## Data controller

The AssetFare API is operated independently of these tools; see AssetFare's own
terms for how it handles request data. Questions: support@assetfare.dev.
