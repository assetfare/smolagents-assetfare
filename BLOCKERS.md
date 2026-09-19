# Hub-model coverage & blockers — smolagents AssetFare adapter

This records, per the overnight adapter spec (directives 3, 5, 12, 16, 26), exactly
what the smolagents Hub tool model can and cannot host for the full caller-approved
v2 non-custodial contract, so nothing is silently dropped and no adapter's real
functionality is falsely shrunk in docs.

## Result: NO hard Hub blocker — full contract is hosted

Every tool in the core contract is implemented as its own self-contained
`smolagents.Tool` subclass and published as its own Static-Space bundle:

| capability | tool class | Space | endpoint |
|------------|-----------|-------|----------|
| quote discovery | `AssetFareQuoteTool` | `assetfare-quote` | `POST /v2/quote` |
| capabilities | `AssetFareCapabilitiesTool` | `assetfare-capabilities` | `GET /v2/capabilities` + `/v2/status` |
| session token (local) | `AssetFareNewSessionCapabilityTool` | `assetfare-new-session-capability` | none (zero network) |
| one-shot prepare | `AssetFarePrepareTool` | `assetfare-prepare` | `POST /v2/prepare` |
| session create | `AssetFareSessionCreateTool` | `assetfare-session-create` | `POST /v2/session` |
| session read | `AssetFareSessionGetTool` | `assetfare-session-get` | `GET /v2/session/{id}` |
| observe source | `AssetFareObserveSourceTool` | `assetfare-observe-source` | `POST /v2/session/{id}/observe-source` |
| observe output | `AssetFareObserveOutputTool` | `assetfare-observe-output` | `POST /v2/session/{id}/observe-output` |
| refresh action | `AssetFareRefreshActionTool` | `assetfare-refresh-action` | `POST /v2/session/{id}/refresh-action` |

The MCP/Dify reference adapters expose the same set; the smolagents Hub model can
host all of it, so there is **no** reduction of REST/A2A/MCP/Dify functionality to
report and **no** capability was dropped.

## Model constraints handled (not blockers)

These are shape constraints of the smolagents Hub tool model that shaped the
implementation. Each is worked around without losing behaviour:

1. **One tool class == one tool == one Static-Space bundle.** smolagents serialises
   a single `Tool` subclass to a self-contained `tool.py` (`Tool.to_dict()` →
   `instance_to_source`). There is no multi-tool bundle, so the session lifecycle is
   five separate tools (create / get / observe-source / observe-output / refresh)
   plus the local token tool and the prepare tool — seven new Spaces. This is the
   correct Hub idiom, not a limitation of the contract.

2. **Self-containment (no shared module).** `validate_tool_attributes` requires each
   method to be self-contained with imports done inside methods, so the transport
   (`_request`), the recursive no-sign guard (`_reject_signing_claims` /
   `_no_sign_tree`), the secret-material reject, and the validators are duplicated
   into each tool class rather than shared via a helper module. Cost is duplication;
   there is no behavioural loss.

3. **Class attributes must be literal Constant/Dict/List/Set.** So the exact 8-field
   `request_fields` **list** cannot be a class attribute (a `List` literal carries an
   `ast.Load` ctx that `validate_tool_attributes` rejects as "complex"); it lives as
   a local inside the handoff validator. Set attributes (CHAINS, ENDPOINTS,
   SOURCE_ONLY_CHAINS, FORBIDDEN_SECRET_KEYS, HANDOFF_ALLOWED_KEYS) are allowed and
   re-emitted by `repr(set)` in hash order, so `hub/build_bundles.py::canonicalize`
   sorts **every** UPPER_CASE set-literal attribute to keep bundles byte-identical
   across `PYTHONHASHSEED` and CPython versions (asserted in `tests/test_bundle.py`).

4. **No generator expressions in tool methods.** smolagents' method validator tracks
   comprehension targets for list/set/dict comprehensions but **not** for bare
   generator expressions, so `all(... for x in ...)` / `any(... for x in ...)` are
   written as explicit `for` loops.

5. **Nullable inputs.** Optional inputs (`event_signer_public`, `transaction_hash`)
   are declared `"nullable": True` in `inputs` and given a default in `forward`, as
   required by `validate_tool_attributes`.

## Marketplace / publish policy

smolagents Spaces are published as free `sdk: static` Spaces (no gradio, no compute,
no PRO). There is **no marketplace submission gate** analogous to Dify's, so the
unsigned prepare/session tools raise no publish-classification blocker here. The
only publish-time discipline is the SHA-pin principle (directive 5 / 11): the cards
and generated landing pages do **not** advertise a pre-publish / pre-Optimism commit
as the 6-chain canonical revision — the reviewed revision SHA is pinned only **after**
the 6-chain build is published (until then a clearly annotated placeholder is used).

## Not done here (out of scope for this adapter)

- No publish/push to the Hub (no `push_to_hub`, no login) — bundles are generated and
  committed for the owner to upload as one atomic commit per Space.
- Revision SHAs are intentionally left as placeholders pending publish.
