"""Build atomic, manually-uploadable Hub *Static* Space bundles for the AssetFare tools.

The agent path (`smolagents.load_tool` -> `Tool.from_hub`) downloads ONLY
``tool.py`` from the Space repo via ``hf_hub_download(repo_type="space", revision=...)``
and never reads the Space SDK, imports gradio, or runs an app. So these Spaces use
the free ``sdk: static`` type with a trivial ``index.html`` -- no Gradio, no compute,
no PRO subscription -- and drop the gradio dependency (and its vuln surface) entirely.

For each tool this writes ``hub_bundles/<space>/`` with exactly the files a static
Space needs, so the owner can upload the whole directory in one atomic commit:

    tool.py           serialized, canonicalized, self-contained tool code
                      (== canonicalize(to_dict()["code"]); loads identically)
    index.html        static landing page (Space app_file for sdk: static),
                      generated deterministically from a shared template
    requirements.txt  the tool's runtime deps for the loading agent's env only
                      (smolagents==1.26.0, requests>=2.32.3,<3) -- NOT executed by
                      the static Space; no gradio
    README.md         Space card (frontmatter sdk: static, app_file index.html,
                      tags smolagents+tool, license)
    LICENSE, PRIVACY.md

Reproducibility (cross-process AND cross-interpreter): smolagents'
``instance_to_source`` emits the top-level ``import`` block and any set-literal
class attributes via ``repr(set)`` in an order that varies both with
``PYTHONHASHSEED`` and between CPython versions. Pinning the hash seed alone is not
enough. ``_canonicalize`` normalizes exactly those two things -- it sorts the
top-level imports and re-emits EVERY set-literal class attribute (any UPPER_CASE
name: CHAINS, ENDPOINTS, SOURCE_ONLY_CHAINS, FORBIDDEN_SECRET_KEYS,
HANDOFF_ALLOWED_KEYS, ...) with its elements sorted -- while leaving every other
line (method bodies, ``inputs`` dict, list literals, string/number constants)
byte-for-byte unchanged. List literals keep their authored order (they carry an
ast.Load ctx, so smolagents cannot host them as class attributes anyway; the exact
8-field request_fields list lives inside a method, not as a class attribute). The
result is identical ``tool.py`` bytes (and whole-bundle SHA) on any interpreter and
any hash seed, with the tool's semantics preserved.

SHA-pin principle: generated cards/landing pages advertise only an immutable
Space revision whose exact bundle was already published and reviewed. A new
bundle must be uploaded first; only then may its revision replace the prior pin.

Run: python hub/build_bundles.py   (no network, no login, no push)
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assetfare_capabilities_tool import AssetFareCapabilitiesTool
from assetfare_prepare_tool import AssetFarePrepareTool
from assetfare_quote_tool import AssetFareQuoteTool
from assetfare_session_capability_tool import AssetFareNewSessionCapabilityTool
from assetfare_session_tools import (
    AssetFareObserveOutputTool,
    AssetFareObserveSourceTool,
    AssetFareRefreshActionTool,
    AssetFareSessionCreateTool,
    AssetFareSessionGetTool,
)

# The tool's runtime deps for the *loading agent's* environment only. The static
# Space itself runs nothing, so no gradio (and no gradio vuln surface) is shipped.
BUNDLE_REQUIREMENTS = "smolagents==1.26.0\nrequests>=2.32.3,<3\n"

# Reviewed public Space revisions. Update a pin only after the exact generated
# bundle has been uploaded and verified at that immutable revision.
REVIEWED_REVISIONS = {
    "assetfare-quote": "1f9dd16326a70aba241aa30b77b75a8310b1bc45",
    "assetfare-capabilities": "2cde821ca957e9ebc4434a4c7d065546fdb05686",
    "assetfare-new-session-capability": "561c6b23da41936757087054ca32e472f4e9a399",
    "assetfare-prepare": "9c71dd6b1aa51484237d17d69090b599baf8fe3c",
    "assetfare-session-create": "213573ca301b764e298faddb5420dbe7b590bc9c",
    "assetfare-session-get": "cf03a26155aba8804aa38c1a4ed7c2c410fe9d1a",
    "assetfare-observe-source": "ee76aa24e745114b5e4cff226b6ef88b7cd69266",
    "assetfare-observe-output": "aeaadbd52a56595e8949f2f9a9eb0ff66dd54c0a",
    "assetfare-refresh-action": "e7ad8ddc91217cf676466212a04bc9c944036ba3",
}

# (space, Class, human title, one-line tagline). space == card dir == repo name.
SPECS = [
    ("assetfare-quote", AssetFareQuoteTool, "AssetFare Quote Tool", "read-only, quote-only cross-chain quote"),
    ("assetfare-capabilities", AssetFareCapabilitiesTool, "AssetFare Capabilities Tool", "read-only capability/status probe"),
    ("assetfare-new-session-capability", AssetFareNewSessionCapabilityTool, "AssetFare Session Capability Token", "local-only session capability token generator (no network)"),
    ("assetfare-prepare", AssetFarePrepareTool, "AssetFare Prepare Tool", "explicit caller-approved one-shot /v2/prepare (unsigned bundle)"),
    ("assetfare-session-create", AssetFareSessionCreateTool, "AssetFare Session Create Tool", "explicit caller-approved /v2/session create (idempotent)"),
    ("assetfare-session-get", AssetFareSessionGetTool, "AssetFare Session Get Tool", "read-only /v2/session/{id}"),
    ("assetfare-observe-source", AssetFareObserveSourceTool, "AssetFare Observe Source Tool", "observe caller-submitted source tx hashes"),
    ("assetfare-observe-output", AssetFareObserveOutputTool, "AssetFare Observe Output Tool", "observe caller-produced destination output"),
    ("assetfare-refresh-action", AssetFareRefreshActionTool, "AssetFare Refresh Action Tool", "refresh an expired unsigned session action"),
]


def canonicalize(code: str) -> str:
    """Make the serialized tool code byte-identical across interpreters and hash
    seeds by normalizing the only two order-unstable parts: the top-level import
    block and set-literal class attributes. Semantics are preserved (same imports,
    same set members); every other line is left unchanged."""
    lines = code.split("\n")
    # 1. Sort the contiguous top-level import block at the very top of the file.
    i = 0
    imports: list[str] = []
    while i < len(lines) and (lines[i].startswith("import ") or lines[i].startswith("from ")):
        imports.append(lines[i])
        i += 1
    rest = lines[i:]
    while rest and rest[0].strip() == "":
        rest.pop(0)
    code = "\n".join(sorted(imports) + [""] + rest)

    # 2. Re-emit each set-literal class attribute (any UPPER_CASE name) with its
    #    elements stably sorted. `repr(set)` order is hash-dependent; a dict literal
    #    matches the same brace regex but literal_eval returns a dict, so it is left
    #    unchanged. List literals use [ ] and never match this brace regex.
    def _sort_set(m: re.Match[str]) -> str:
        indent, name, rhs = m.group("indent"), m.group("name"), m.group("rhs")
        try:
            value = ast.literal_eval(rhs)
        except (ValueError, SyntaxError):
            return m.group(0)
        if isinstance(value, (set, frozenset)):
            return f"{indent}{name} = {{{', '.join(repr(e) for e in sorted(value))}}}"
        return m.group(0)

    return re.sub(
        r"(?P<indent>^[ \t]*)(?P<name>[A-Z_][A-Z0-9_]*) = (?P<rhs>\{[^{}]*\})",
        _sort_set,
        code,
        flags=re.MULTILINE,
    )


def _index_html(space: str, title: str, tagline: str, tool_name: str, description: str) -> str:
    """Deterministic static landing page. Contains load_tool + trust_remote_code=True,
    no gradio, and the already-reviewed immutable Space revision."""
    summary = description[:400]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} (smolagents)</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font: 15px/1.6 system-ui, sans-serif; background: #0f1420; color: #e7ecf3; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 40px 20px; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .2em; }}
  .sub {{ color: #9fb0c7; margin-top: 0; }}
  code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  pre {{ background: #171f2e; border: 1px solid #263349; border-radius: 8px; padding: 14px; overflow-x: auto; }}
  .tag {{ display: inline-block; background: #1c2740; color: #9ec1ff; border-radius: 6px; padding: 2px 8px; font-size: .8rem; margin-right: 6px; }}
  .box {{ background: #171f2e; border: 1px solid #263349; border-radius: 8px; padding: 12px 16px; margin: 14px 0; }}
  a {{ color: #7fb0ff; }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="sub">A non-custodial <a href="https://github.com/huggingface/smolagents">smolagents</a> agent tool &mdash; {tagline}.</p>
  <p><span class="tag">smolagents</span><span class="tag">tool</span><span class="tag">non-custodial</span><span class="tag">cross-chain</span></p>

  <p>This Space hosts an <strong>agent tool</strong> (<code>tool.py</code>), meant to be loaded
  by an agent &mdash; not run as a web app. {summary}
  AssetFare never signs or submits; this tool never receives a private key and fails
  closed on any response that claims the server will sign or submit.</p>

  <div class="box">
    <strong>Load it in an agent (review <code>tool.py</code> first):</strong>
<pre>from smolagents import load_tool

tool = load_tool(
    "odaiin/{space}",
    trust_remote_code=True,           # runs the reviewed tool code in your process
    revision="{REVIEWED_REVISIONS[space]}",  # reviewed immutable Space revision
)</pre>
  </div>

  <p>Tool name: <code>{tool_name}</code>. Does <strong>not</strong> execute, bridge, swap,
  sign, or move funds &mdash; any transfer is a separate caller wallet action taken after
  explicit approval. Review the
  <a href="https://github.com/assetfare/smolagents-assetfare">source and tests</a> and the
  <a href="https://assetfare.dev/agents/">AssetFare agent integration guide</a>.</p>
</main>
</body>
</html>
"""


def _build_impl() -> list[Path]:
    out_root = ROOT / "hub_bundles"
    built = []
    for space, cls, title, tagline in SPECS:
        out = out_root / space
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        instance = cls()
        # 1. serialized, canonicalized, self-contained tool code (== Hub-loaded code)
        (out / "tool.py").write_text(canonicalize(instance.to_dict()["code"]), encoding="utf-8")
        # 2. static landing page (Space app_file for sdk: static; not agent-facing)
        (out / "index.html").write_text(
            _index_html(space, title, tagline, cls.name, cls.description), encoding="utf-8"
        )
        # 3. runtime deps for the loading agent's env (no gradio; static Space runs none)
        (out / "requirements.txt").write_text(BUNDLE_REQUIREMENTS, encoding="utf-8")
        # 4. card + license + privacy
        card = ROOT / "hub_cards" / space
        for fname in ("README.md", "LICENSE", "PRIVACY.md"):
            shutil.copyfile(card / fname, out / fname)
        built.append(out)
    return built


def build() -> list[Path]:
    """Build the bundles. `canonicalize` makes the output identical across
    interpreters and hash seeds, so no subprocess/seed pinning is needed."""
    return _build_impl()


if __name__ == "__main__":
    for p in build():
        files = sorted(x.name for x in p.iterdir())
        print(p.relative_to(ROOT), "->", files)
