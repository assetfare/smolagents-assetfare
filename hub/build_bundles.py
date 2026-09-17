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
    index.html        static landing page (Space app_file for sdk: static)
    requirements.txt  the tool's runtime deps for the loading agent's env only
                      (smolagents==1.26.0, requests>=2.32.3,<3) -- NOT executed by
                      the static Space; no gradio
    README.md         Space card (frontmatter sdk: static, app_file index.html,
                      tags smolagents+tool, license)
    LICENSE, PRIVACY.md

Reproducibility (cross-process AND cross-interpreter): smolagents'
``instance_to_source`` emits the top-level ``import`` block and the set-literal
class attributes (CHAINS/ENDPOINTS) in an order that varies both with
``PYTHONHASHSEED`` and between CPython versions (e.g. 3.10 vs 3.12). Pinning the
hash seed alone is therefore not enough. ``_canonicalize`` normalizes exactly those
two things -- it sorts the top-level imports and re-emits each set literal with its
elements sorted -- while leaving every other line (method bodies from ``get_source``,
the ``inputs`` dict, string/number constants) byte-for-byte unchanged. The result is
identical ``tool.py`` bytes (and whole-bundle SHA) on any interpreter and any hash
seed, with the tool's semantics preserved (same members, same imports).

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
from assetfare_quote_tool import AssetFareQuoteTool

# The tool's runtime deps for the *loading agent's* environment only. The static
# Space itself runs nothing, so no gradio (and no gradio vuln surface) is shipped.
BUNDLE_REQUIREMENTS = "smolagents==1.26.0\nrequests>=2.32.3,<3\n"

SPECS = [
    ("assetfare-quote", AssetFareQuoteTool, "index_quote.html", "assetfare-quote"),
    ("assetfare-capabilities", AssetFareCapabilitiesTool, "index_capabilities.html", "assetfare-capabilities"),
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

    # 2. Re-emit each set-literal assignment with its elements stably sorted.
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
        r"(?P<indent>^[ \t]*)(?P<name>CHAINS|ENDPOINTS) = (?P<rhs>\{[^{}]*\})",
        _sort_set,
        code,
        flags=re.MULTILINE,
    )


def _build_impl() -> list[Path]:
    hub = Path(__file__).resolve().parent
    out_root = ROOT / "hub_bundles"
    built = []
    for space, cls, index_name, card_dir in SPECS:
        out = out_root / space
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        # 1. serialized, canonicalized, self-contained tool code (== Hub-loaded code)
        (out / "tool.py").write_text(canonicalize(cls().to_dict()["code"]), encoding="utf-8")
        # 2. static landing page (Space app_file for sdk: static; not agent-facing)
        (out / "index.html").write_text((hub / index_name).read_text(encoding="utf-8"), encoding="utf-8")
        # 3. runtime deps for the loading agent's env (no gradio; static Space runs none)
        (out / "requirements.txt").write_text(BUNDLE_REQUIREMENTS, encoding="utf-8")
        # 4. card + license + privacy
        card = ROOT / "hub_cards" / card_dir
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
