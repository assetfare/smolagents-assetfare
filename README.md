# smolagents-assetfare — read-only AssetFare tools for smolagents agents

Public source for two self-contained [smolagents](https://github.com/huggingface/smolagents)
`Tool` classes that let an agent **load and call** AssetFare's read-only
cross-chain quote surface — the current, supported Hub tool path (a Space tagged
`smolagents`+`tool`, whose `tool.py` an agent loads via
`load_tool(repo_id, trust_remote_code=True)`), **not** a human-facing Space promo.

| file | what |
|------|------|
| `assetfare_quote_tool.py` | `AssetFareQuoteTool` — validated `POST /v2/quote` |
| `assetfare_capabilities_tool.py` | `AssetFareCapabilitiesTool` — validated `GET /v2/capabilities` + `/v2/status` |
| `tests/test_tools.py` | offline mock tests (no network) |
| `tests/test_bundle.py` | builds + boots each Hub bundle in a subprocess (no network) |
| `hub/app_quote.py`, `hub/app_capabilities.py` | custom `gr.JSON` Space apps (see Publishing) |
| `hub/build_bundles.py` | deterministic builder → `hub_bundles/<space>/` |
| `hub_bundles/<space>/` | generated, atomically-uploadable Space bundle |
| `hub_cards/<space>/README.md` | per-Space Hub card (frontmatter + usage) |
| `LICENSE` / `PRIVACY.md` | MIT license / privacy statement |
| `pyproject.toml` | pins + ruff config |

## Guarantees (both tools)

- Fixed origin `https://api.assetfare.dev`; any other base URL rejected (injected
  `requests.Session` included — `trust_env` is forced off).
- Exact surface: 4 chains, 9 `(chain, token)` endpoints, 72 routes, $1–$1000.
- Strict response validation, RFC3339 tz-aware freshness (stale + future-skew;
  a trailing `Z` is normalized so it validates on Python 3.10 as well as 3.11+),
  1 MiB cap, single fixed sanitized error (no upstream text leaks). Every failure
  is recorded as a flag/sentinel and the fixed `ValueError` is raised *outside* the
  `except` handler, so the final exception has `__context__ is None` and
  `__cause__ is None` — a bare `raise ... from None` would still leave the upstream
  exception object on `__context__`. Internal budget/size stops use a sentinel, so
  a hostile `iter_content` raising its own `ValueError` is sanitized, not surfaced.
- **No** wallet auth, session, unsigned-action prepare, sign, or submit; fails
  closed if a response claims the server signs or submits.
- Self-contained per smolagents `validate_tool_attributes` — each serialises to a
  single `tool.py` via `to_dict()` and round-trips through `from_code` (the
  Hub-load path), asserted in tests.

## Test / lint locally (offline)

```bash
python -m pytest tests/ -q     # py3.12: 101 passed (96 tools + 5 bundle)
                               # py3.10: run tests/test_tools.py -> 96 passed
ruff check .                   # clean (generated hub_bundles/ excluded)
```

The suite is verified on both Python 3.12 and Python 3.10 (the declared floor);
the bundle boot test needs gradio, so it runs under the 3.12 env.

## Reviewed Hub bundles

**Why not `push_to_hub` / the default app.** `Tool.push_to_hub` auto-generates an
`app.py` that calls smolagents' `launch_gradio_demo`, which maps `output_type` to
a Gradio component through a table with **no `"object"` entry** — so for these
tools (both `output_type="object"`) it raises `KeyError` and the Space fails to
build. These tools therefore ship a **custom `gr.JSON` app** and are published by
uploading a self-contained bundle, not by `push_to_hub`.

**How each reviewed Space bundle is built:**

```bash
python hub/build_bundles.py     # regenerates hub_bundles/<space>/ deterministically
                                # (self-re-execs at PYTHONHASHSEED=0: smolagents serializes
                                #  the set-literal class attrs via repr(set), so a fixed seed
                                #  is needed for byte-identical bundles across processes; a
                                #  cross-seed regression asserts both Spaces' SHAs match)
```

Each `hub_bundles/<space>/` contains exactly what the Space needs — `tool.py`
(the serialized, validated, self-contained tool code), the custom `app.py`,
`requirements.txt` (pinned: `smolagents==1.26.0`, `requests>=2.32.3,<3`,
`gradio>=6.16,<7` — the 6.x line resolves clean under pip-audit on Python 3.10
and 3.12, whereas the 5.x line carried transitive vulnerabilities), plus
`README.md` (card with `smolagents`+`tool` tags),
`LICENSE`, and `PRIVACY.md`. The owner (authenticated separately) uploads the
whole directory as **one atomic commit** to the Space (e.g. `huggingface_hub`
`upload_folder` / `create_commit`), so there is no reliance on the broken
auto-generated app. The agent `load_tool` path itself needs only `tool.py` +
`requirements.txt`; the `gr.JSON` app is a secondary human view.

## Discovery & loading (a catalog, not automatic routing)

The Hub is a **catalog, not automatic intent discovery**: an agent does not
silently find and run these tools. A developer/operator explicitly finds a tool
(by the `smolagents`+`tool` tag filter or by name), **reviews `tool.py`**, and
loads it:

```python
from smolagents import load_tool

quote = load_tool(
    "odaiin/assetfare-quote",
    trust_remote_code=True,          # required for any Hub tool: runs Space code in-process
    revision="<reviewed commit SHA>",# pin the exact commit you audited, not moving main
)
```

`trust_remote_code=True` is mandatory (and inherent to Hub tools); `revision` is
forwarded to the Hub download, so pin a reviewed SHA rather than tracking `main`.
