# smolagents-assetfare — read-only AssetFare tools for smolagents agents

Public source for two self-contained [smolagents](https://github.com/huggingface/smolagents)
`Tool` classes that let an agent **load and call** AssetFare's read-only
cross-chain quote surface — the current, supported Hub tool path (a Space tagged
`smolagents`+`tool`, whose `tool.py` an agent loads via
`load_tool(repo_id, trust_remote_code=True)`), **not** a human-facing Space promo.

Published Static Spaces:

- `https://huggingface.co/spaces/odaiin/assetfare-quote`
- `https://huggingface.co/spaces/odaiin/assetfare-capabilities`

| file | what |
|------|------|
| `assetfare_quote_tool.py` | `AssetFareQuoteTool` — validated `POST /v2/quote` |
| `assetfare_capabilities_tool.py` | `AssetFareCapabilitiesTool` — validated `GET /v2/capabilities` + `/v2/status` |
| `tests/test_tools.py` | offline mock tests (no network) |
| `tests/test_bundle.py` | builds + loads each Static-Space bundle in a subprocess (no network) |
| `hub/index_quote.html`, `hub/index_capabilities.html` | static Space landing pages (`app_file`) |
| `hub/build_bundles.py` | deterministic builder → `hub_bundles/<space>/` |
| `hub_bundles/<space>/` | generated, atomically-uploadable Space bundle |
| `hub_cards/<space>/README.md` | per-Space Hub card (frontmatter + usage) |
| `LICENSE` / `PRIVACY.md` | MIT license / privacy statement |
| `pyproject.toml` | pins + ruff config |

## Guarantees (both tools)

- Fixed origin `https://api.assetfare.dev`; any other base URL rejected (injected
  `requests.Session` included — `trust_env` is forced off).
- Exact surface: 5 source chains, 10 `(chain, token)` source endpoints, 74 routes, $1–$1000. Polygon is native-USDC source-only to Base or Arbitrum USDC.
- Strict response validation, RFC3339 tz-aware freshness (stale + future-skew;
  a trailing `Z` is normalized so it validates on Python 3.10 as well as 3.11+),
  1 MiB cap, single fixed sanitized error (no upstream text leaks). Every failure
  is recorded as a flag/sentinel and the fixed `ValueError` is raised *outside* the
  `except` handler, so the final exception has `__context__ is None` and
  `__cause__ is None` — a bare `raise ... from None` would still leave the upstream
  exception object on `__context__`. Internal budget/size stops use a sentinel, so
  a hostile `iter_content` raising its own `ValueError` is sanitized, not surfaced.
- **No** wallet auth, session, unsigned-action prepare, sign, or submit. A
  quote result includes only a documentation-only REST `/v2/prepare` handoff,
  usable after explicit caller approval with public wallet addresses; it fails
  closed if a response claims the server signs or submits.
- Self-contained per smolagents `validate_tool_attributes` — each serialises to a
  single `tool.py` via `to_dict()` and round-trips through `from_code` (the
  Hub-load path), asserted in tests.

## Test / lint locally (offline)

```bash
python -m pytest tests/ -q     # 128 passed with SMOLAGENTS_ALT_PYTHON set; otherwise 127 passed + 1 skipped
ruff check .                   # clean (generated hub_bundles/ excluded)
```

The full suite (tools + bundle) is verified on both Python 3.12 and Python 3.10
(the declared floor). It needs no gradio, so both run the whole suite. A fresh
isolated resolution of the bundle deps (`smolagents==1.26.0`, `requests>=2.32.3,<3`)
is `pip-audit`-clean (0 vulnerabilities) on 3.10 and 3.12.

## Reviewed Static-Space bundles

**Static Spaces, no gradio.** `smolagents.load_tool` → `Tool.from_hub` downloads
**only `tool.py`** from the Space repo (`hf_hub_download(repo_type="space",
revision=...)`) and never reads the Space SDK, imports gradio, or runs an app. So
each Space uses the free **`sdk: static`** type with a trivial `index.html` — no
Gradio, no compute, no PRO subscription — and the gradio dependency (and its
transitive vuln surface) is dropped entirely. (This also sidesteps `push_to_hub`,
whose auto-generated Gradio `app.py` calls `launch_gradio_demo`, which `KeyError`s
on `output_type="object"`.)

**How each reviewed Space bundle is built:**

```bash
python hub/build_bundles.py     # regenerates hub_bundles/<space>/ deterministically
                                # (canonicalize() sorts the serialized top-level imports and
                                #  set-literal class attrs, whose order otherwise varies with
                                #  PYTHONHASHSEED and between CPython 3.10/3.12; tool.py bytes
                                #  are then identical on any interpreter/seed, semantics intact;
                                #  cross-seed AND cross-interpreter regressions assert the SHAs)
```

Each `hub_bundles/<space>/` contains exactly the 6-file allowlist a static Space
needs — `tool.py` (the serialized, validated, self-contained tool code),
`index.html` (the static Space `app_file`), `requirements.txt` (the loading
agent's runtime deps: `smolagents==1.26.0`, `requests>=2.32.3,<3` — **no gradio**;
the static Space runs nothing), `README.md` (card with `sdk: static` and
`smolagents`+`tool` tags), `LICENSE`, and `PRIVACY.md`. The owner (authenticated
separately) uploads the whole directory as **one atomic commit** to the Space
(e.g. `huggingface_hub` `upload_folder` / `create_commit`). The agent `load_tool`
path needs only `tool.py`; `index.html` is a secondary human-facing landing page.

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
    revision="8e0f9ffbf4308f496f88c64dc912499845f4e371", # reviewed Polygon-capable quote release
)
```

`trust_remote_code=True` is mandatory (and inherent to Hub tools); `revision` is
forwarded to the Hub download, so pin a reviewed SHA rather than tracking `main`.
