"""Build atomic, manually-uploadable Hub *Static* Space bundles for the AssetFare tools.

The agent path (`smolagents.load_tool` -> `Tool.from_hub`) downloads ONLY
``tool.py`` from the Space repo via ``hf_hub_download(repo_type="space", revision=...)``
and never reads the Space SDK, imports gradio, or runs an app. So these Spaces use
the free ``sdk: static`` type with a trivial ``index.html`` -- no Gradio, no compute,
no PRO subscription -- and drop the gradio dependency (and its vuln surface) entirely.

For each tool this writes ``hub_bundles/<space>/`` with exactly the files a static
Space needs, so the owner can upload the whole directory in one atomic commit:

    tool.py           serialized, self-contained tool code (== to_dict()["code"])
    index.html        static landing page (Space app_file for sdk: static)
    requirements.txt  the tool's runtime deps for the loading agent's env only
                      (smolagents==1.26.0, requests>=2.32.3,<3) -- NOT executed by
                      the static Space; no gradio
    README.md         Space card (frontmatter sdk: static, app_file index.html,
                      tags smolagents+tool, license)
    LICENSE, PRIVACY.md

Reproducibility: smolagents' ``instance_to_source`` emits the tool's set-literal
class attributes (CHAINS/ENDPOINTS) via ``repr(set)``, whose element order depends
on PYTHONHASHSEED. To make ``tool.py`` byte-identical across processes, ``build()``
re-execs the real work in a subprocess pinned to ``PYTHONHASHSEED=0`` whenever the
current process is not already at seed 0. The result is deterministic regardless of
the caller's hash seed.

Run: python hub/build_bundles.py   (no network, no login, no push)
"""

from __future__ import annotations

import os
import shutil
import subprocess
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


def _build_impl() -> list[Path]:
    hub = Path(__file__).resolve().parent
    out_root = ROOT / "hub_bundles"
    built = []
    for space, cls, index_name, card_dir in SPECS:
        out = out_root / space
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        # 1. serialized, validated, self-contained tool code (== Hub-loaded code)
        (out / "tool.py").write_text(cls().to_dict()["code"], encoding="utf-8")
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
    """Build the bundles reproducibly. If this process is not pinned to
    PYTHONHASHSEED=0, re-exec the real build in a subprocess that is, so the
    serialized set-literal ordering (and thus the bundle bytes) is identical no
    matter the caller's hash seed."""
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ, PYTHONHASHSEED="0")
        subprocess.run(
            [sys.executable, "-c", "import build_bundles; build_bundles._build_impl()"],
            cwd=str(Path(__file__).resolve().parent),
            env=env,
            check=True,
        )
        return [ROOT / "hub_bundles" / space for space, *_ in SPECS]
    return _build_impl()


if __name__ == "__main__":
    for p in build():
        files = sorted(x.name for x in p.iterdir())
        print(p.relative_to(ROOT), "->", files)
