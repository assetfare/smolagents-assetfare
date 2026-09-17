"""Bundle boot/import verification for the Hub Space bundles.

For each built bundle this:
  - runs the deterministic builder,
  - checks the bundle files exist and requirements are pinned (incl. gradio),
  - boots the bundle in an isolated subprocess (cwd = bundle dir) that imports
    tool.py, instantiates + validates the tool, and imports app.py so the custom
    gr.JSON demo is *built* (proving the launch_gradio_demo KeyError on
    output_type="object" is avoided) -- WITHOUT launching a server.

No network, no login, no push.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hub"))

import build_bundles


@pytest.fixture(scope="module")
def bundles():
    return {p.name: p for p in build_bundles.build()}


SPACES = ["assetfare-quote", "assetfare-capabilities"]

# Runs inside each bundle dir; asserts tool loads/validates and the demo builds.
_BOOT = r"""
import importlib
tool_mod = importlib.import_module("tool")
cls = [getattr(tool_mod, n) for n in dir(tool_mod)
       if n.startswith("AssetFare") and n.endswith("Tool")][0]
t = cls()
assert t.output_type == "object"
d = t.to_dict()              # validate_tool_attributes must pass on the bundled code
assert d["name"] in ("assetfare_quote", "assetfare_capabilities")
app = importlib.import_module("app")   # builds `demo` via gr.JSON, no launch_gradio_demo
import gradio as gr
assert isinstance(app.demo, gr.Blocks), type(app.demo)
print("BOOT OK", d["name"], "gradio", gr.__version__)
"""


@pytest.mark.parametrize("space", SPACES)
def test_bundle_files_present_and_pinned(bundles, space):
    d = bundles[space]
    for f in ("tool.py", "app.py", "requirements.txt", "README.md", "LICENSE", "PRIVACY.md"):
        assert (d / f).is_file(), f"missing {f} in {space}"
    reqs = (d / "requirements.txt").read_text()
    assert "smolagents==1.26.0" in reqs
    assert "requests>=2.32.3,<3" in reqs
    assert "gradio>=6.16,<7" in reqs
    # app.py must not CALL or import the broken auto demo (a docstring may name it)
    app_src = (d / "app.py").read_text()
    assert "launch_gradio_demo(" not in app_src
    assert "import launch_gradio_demo" not in app_src
    assert "gr.JSON" in app_src


@pytest.mark.parametrize("space", SPACES)
def test_bundle_boots_in_subprocess(bundles, space):
    d = bundles[space]
    r = subprocess.run(
        [sys.executable, "-c", _BOOT],
        cwd=str(d),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert r.returncode == 0, f"boot failed for {space}:\nSTDOUT{r.stdout}\nSTDERR{r.stderr}"
    assert "BOOT OK" in r.stdout, r.stdout


# ---- reproducibility: identical bundle bytes across different PYTHONHASHSEED ----

_CANON = ["tool.py", "app.py", "requirements.txt", "README.md", "LICENSE", "PRIVACY.md"]


def _space_sha(space_dir):
    import hashlib

    h = hashlib.sha256()
    for name in _CANON:  # fixed order, not directory order
        h.update(name.encode())
        h.update(b"\0")
        h.update((space_dir / name).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _run_builder(seed):
    import os

    builder = ROOT / "hub" / "build_bundles.py"
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    r = subprocess.run([sys.executable, str(builder)], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=180, check=False)
    assert r.returncode == 0, r.stderr
    return {s: _space_sha(ROOT / "hub_bundles" / s) for s in SPACES}


def test_bundle_bytes_deterministic_across_hashseeds():
    # The tool's set-literal class attributes serialize via repr(set), whose order
    # depends on PYTHONHASHSEED. The builder re-execs at seed 0, so different parent
    # seeds must still yield byte-identical bundles for both Spaces.
    a = _run_builder(1)
    b = _run_builder(2)
    c = _run_builder(987654321)
    for space in SPACES:
        assert a[space] == b[space] == c[space], f"non-deterministic bundle for {space}"
