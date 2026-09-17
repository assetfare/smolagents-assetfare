"""Build atomic, manually-uploadable Hub Space bundles for the AssetFare tools.

For each tool this writes ``hub_bundles/<space>/`` containing exactly the files a
Gradio Space needs, so the owner can upload the whole directory in one atomic
commit (no reliance on push_to_hub's auto app.py, which calls launch_gradio_demo
and would KeyError on output_type="object"):

    tool.py           serialized, self-contained tool code (== to_dict()["code"])
    app.py            custom gr.JSON demo (never calls launch_gradio_demo)
    requirements.txt  pinned: smolagents==1.26.0, requests>=2.32.3,<3, gradio>=6.16,<7
    README.md         Space card (frontmatter tags smolagents+tool, license, usage)
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

# The Space demo needs gradio in addition to the tool's own runtime deps.
# gradio is pinned to the 6.x line: the 5.x line (and its transitive deps) carries
# known vulnerabilities (independent pip-audit found 58), whereas the 6.16+ line
# resolves clean (pip-audit 0) on both Python 3.10 and 3.12. smolagents 1.26 only
# requires gradio>=5.14.0 with no upper bound, so 6.x is compatible.
BUNDLE_REQUIREMENTS = "smolagents==1.26.0\nrequests>=2.32.3,<3\ngradio>=6.16,<7\n"

SPECS = [
    ("assetfare-quote", AssetFareQuoteTool, "app_quote.py", "assetfare-quote"),
    ("assetfare-capabilities", AssetFareCapabilitiesTool, "app_capabilities.py", "assetfare-capabilities"),
]


def _build_impl() -> list[Path]:
    hub = Path(__file__).resolve().parent
    out_root = ROOT / "hub_bundles"
    built = []
    for space, cls, app_name, card_dir in SPECS:
        out = out_root / space
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        # 1. serialized, validated, self-contained tool code (== Hub-loaded code)
        (out / "tool.py").write_text(cls().to_dict()["code"], encoding="utf-8")
        # 2. custom gr.JSON app (no launch_gradio_demo)
        (out / "app.py").write_text((hub / app_name).read_text(encoding="utf-8"), encoding="utf-8")
        # 3. pinned requirements (adds gradio for the Space)
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
