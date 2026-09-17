# Privacy

The AssetFare smolagents tools (`assetfare_quote`, `assetfare_capabilities`) are
**read-only** and **quote-only**.

## What is sent

- **Only** to the fixed origin `https://api.assetfare.dev` over HTTPS. Any other
  base URL is rejected before a request is made.
- `assetfare_capabilities`: a public `GET /v2/capabilities` and `GET /v2/status`
  with no body.
- `assetfare_quote`: a `POST /v2/quote` whose body contains **only** the route
  you request — `from_chain`, `from_token`, `to_chain`, `to_token` — and the USD
  `amount_usd`. Nothing else is added.

## What is NOT sent or collected

- No wallet address, private key, seed phrase, API key, token, or account/session
  credential. The tools never add an `Authorization` header or any auth material.
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
