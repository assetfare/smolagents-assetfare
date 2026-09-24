"""Static-Space bundle verification.

For the built bundles this:
  - runs the deterministic builder,
  - checks the exact 6-file allowlist and that requirements pin the tool's runtime
    deps only (smolagents + requests, NO gradio),
  - loads tool.py from each bundle in an isolated subprocess and validates it
    (no gradio, no app to run: static Spaces run nothing),
  - checks index.html is a static HTML landing page,
  - proves the agent load path (smolagents.load_tool -> Tool.from_hub) works from a
    Space *regardless of SDK* by mocking hf_hub_download to return the bundle's
    tool.py, pinning an exact revision, and asserting the loaded tool's schema,
  - asserts byte-identical bundles across PYTHONHASHSEED.

Covers all nine AssetFare tool Spaces (two read-only + the seven caller-approved,
non-custodial action / session / token tools).

No network, no login, no push, no live call (forward() is never called).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hub"))
sys.path.insert(0, str(ROOT))

import build_bundles

# The exact allowlist a static Space carries (HF adds a managed .gitattributes).
ALLOWLIST = ["LICENSE", "PRIVACY.md", "README.md", "index.html", "requirements.txt", "tool.py"]

# space -> (tool name, ordered input keys)
EXPECTED = {
    "assetfare-quote": ("assetfare_quote", ["from_chain", "from_token", "to_chain", "to_token", "amount_usd"]),
    "assetfare-capabilities": ("assetfare_capabilities", []),
    "assetfare-new-session-capability": ("assetfare_new_session_capability", []),
    "assetfare-prepare": (
        "assetfare_prepare",
        ["caller_approved", "from_chain", "from_token", "to_chain", "to_token", "amount_usd", "wallets", "event_signer_public"],
    ),
    "assetfare-session-create": (
        "assetfare_session_create",
        [
            "caller_approved", "from_chain", "from_token", "to_chain", "to_token", "amount_usd",
            "wallets", "session_token", "idempotency_key", "event_signer_public",
        ],
    ),
    "assetfare-session-get": ("assetfare_session_get", ["session_token", "session_id"]),
    "assetfare-observe-source": ("assetfare_observe_source", ["session_token", "session_id", "idempotency_key", "transaction_hashes"]),
    "assetfare-observe-output": ("assetfare_observe_output", ["session_token", "session_id", "idempotency_key", "transaction_hash"]),
    "assetfare-refresh-action": ("assetfare_refresh_action", ["session_token", "session_id", "idempotency_key"]),
}
SPACES = list(EXPECTED)
# Read-only tools may touch only capabilities/status/quote; action tools additionally
# operate the caller-approved prepare/session endpoints.
READONLY_SPACES = {"assetfare-quote", "assetfare-capabilities"}
# The token tool makes no network call at all.
NO_NETWORK_SPACES = {"assetfare-new-session-capability"}


@pytest.fixture(scope="module")
def bundles():
    return {p.name: p for p in build_bundles.build()}


# Runs inside each bundle dir; loads tool.py and validates it. No gradio, no app run.
_BOOT = r"""
import importlib
tool_mod = importlib.import_module("tool")
cls = [getattr(tool_mod, n) for n in dir(tool_mod)
       if n.startswith("AssetFare") and n.endswith("Tool")][0]
t = cls()
assert t.output_type == "object"
d = t.to_dict()              # validate_tool_attributes must pass on the bundled code
assert isinstance(d["name"], str) and d["name"].startswith("assetfare_")
import sys
assert "gradio" not in sys.modules, "tool.py must not import gradio"
print("BOOT OK", d["name"])
"""


@pytest.mark.parametrize("space", SPACES)
def test_bundle_allowlist_exact(bundles, space):
    d = bundles[space]
    got = sorted(p.name for p in d.iterdir())
    assert got == ALLOWLIST, f"{space} files {got} != {ALLOWLIST}"


@pytest.mark.parametrize("space", SPACES)
def test_bundle_requirements_no_gradio(bundles, space):
    reqs = (bundles[space] / "requirements.txt").read_text()
    assert "smolagents==1.26.0" in reqs
    assert "requests>=2.32.3,<3" in reqs
    assert "gradio" not in reqs  # static Space runs nothing; no gradio surface


@pytest.mark.parametrize("space", SPACES)
def test_bundle_card_is_static(bundles, space):
    card = (bundles[space] / "README.md").read_text()
    assert "sdk: static" in card
    assert "app_file: index.html" in card
    assert "sdk: gradio" not in card
    assert "<pin-after-publish>" not in card
    # tags present for discovery
    assert "- smolagents" in card and "- tool" in card


def test_action_card_examples_include_required_solana_event_signer(bundles):
    for space in ("assetfare-prepare", "assetfare-session-create"):
        card = (bundles[space] / "README.md").read_text()
        assert 'from_chain="solana"' in card
        assert 'event_signer_public="<fresh-ephemeral-public-solana-key>"' in card
        assert "caller explicitly approves" in card
        assert "pass only the public key" in card
        assert "Never pass its private key" in card


@pytest.mark.parametrize(
    ("space", "referenced_space"),
    [
        ("assetfare-session-create", "assetfare-new-session-capability"),
        ("assetfare-session-create", "assetfare-session-create"),
        ("assetfare-session-get", "assetfare-session-get"),
    ],
)
def test_session_card_examples_pin_reviewed_public_revisions(bundles, space, referenced_space):
    card = (bundles[space] / "README.md").read_text()
    assert build_bundles.REVIEWED_REVISIONS[referenced_space] in card


@pytest.mark.parametrize("space", SPACES)
def test_index_html_is_static(bundles, space):
    html = (bundles[space] / "index.html").read_text()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "load_tool" in html and "trust_remote_code=True" in html
    assert "gradio" not in html.lower()
    # SHA-pin principle: advertise only the reviewed immutable Space revision.
    assert build_bundles.REVIEWED_REVISIONS[space] in html
    assert "<pin-reviewed-6chain-SHA-after-publish>" not in html


@pytest.mark.parametrize("space", SPACES)
def test_bundle_tool_loads_no_gradio(bundles, space):
    d = bundles[space]
    r = subprocess.run([sys.executable, "-c", _BOOT], cwd=str(d),
                       capture_output=True, text=True, timeout=180, check=False)
    assert r.returncode == 0, f"boot failed for {space}:\nSTDOUT{r.stdout}\nSTDERR{r.stderr}"
    assert "BOOT OK" in r.stdout, r.stdout


@pytest.mark.parametrize("space", SPACES)
def test_load_tool_exact_revision_mocked(bundles, space, monkeypatch):
    # Prove the agent load path works from a Space *regardless of SDK*: from_hub
    # downloads only tool.py (repo_type="space", revision=...). Mock hf_hub_download
    # to return this bundle's tool.py and assert the revision is forwarded and the
    # loaded tool has the right schema. forward() is never called (no live call).
    import smolagents.tools as st

    d = bundles[space]
    seen = {}

    def fake_hf_hub_download(repo_id, filename, **kwargs):
        seen["repo_id"] = repo_id
        seen["filename"] = filename
        seen["repo_type"] = kwargs.get("repo_type")
        seen["revision"] = kwargs.get("revision")
        assert filename == "tool.py"
        return str(d / "tool.py")

    monkeypatch.setattr(st, "hf_hub_download", fake_hf_hub_download)

    from smolagents import load_tool

    name, inputs = EXPECTED[space]
    rev = "deadbeefcafebabe0000000000000000deadbeef"
    tool = load_tool(f"odaiin/{space}", trust_remote_code=True, revision=rev)
    assert seen["repo_type"] == "space"
    assert seen["revision"] == rev  # exact revision forwarded to the Hub download
    assert tool.name == name
    assert list(tool.inputs) == inputs
    assert tool.output_type == "object"


def test_load_tool_requires_trust_remote_code(bundles, monkeypatch):
    import smolagents.tools as st

    d = bundles["assetfare-quote"]
    monkeypatch.setattr(st, "hf_hub_download", lambda *a, **k: str(d / "tool.py"))
    from smolagents import load_tool

    with pytest.raises(ValueError, match="trust_remote_code"):
        load_tool("odaiin/assetfare-quote")  # default trust_remote_code=False


# The recursive no-sign denylist: no sign/submit machinery anywhere in any bundle.
_SIGN_SUBMIT_DENYLIST = [
    ".sign(", "sign_transaction", "submit_transaction", "send_transaction",
    "eth_send", "approve(", "authorization", "api_key", "api-key", "wallet_connect",
]
# Read-only tools additionally must not even name secret material.
_SECRET_KEY_DENYLIST = ["private_key", "mnemonic", "seed_phrase"]


@pytest.mark.parametrize("space", SPACES)
def test_tool_py_no_auth_sign_submit(bundles, space):
    import re

    src = (bundles[space] / "tool.py").read_text()
    low = src.lower()

    # Anchor on the leading quote so only RELATIVE request-path literals passed to
    # self._request match -- the absolute PREPARE_URL/SESSION_URL constants and the
    # handoff URLs the quote tool merely validates (…dev/v2/prepare) do NOT.
    eps = set(re.findall(r'"/v2/(capabilities|status|quote|prepare|session)', src))
    if space in READONLY_SPACES:
        assert eps and eps <= {"capabilities", "status", "quote"}
    elif space in NO_NETWORK_SPACES:
        assert eps == set()  # the token tool makes no network call
    else:
        assert eps and eps <= {"prepare", "session"}

    # No sign/submit machinery in ANY bundle (the recursive no-sign guarantee).
    for bad in _SIGN_SUBMIT_DENYLIST:
        assert bad not in low, f"forbidden token in {space} tool.py: {bad}"
    # Read-only tools never even mention secret-material key names; action tools DO
    # (they list them as REJECTED keys), which is correct, so exempt them here.
    if space in READONLY_SPACES:
        for bad in _SECRET_KEY_DENYLIST:
            assert bad not in low, f"forbidden token in {space} tool.py: {bad}"
    # Every bundle asserts the server never signs/submits somewhere.
    assert "server_signing" in src


# ---- reproducibility: identical bundle bytes across different PYTHONHASHSEED ----

_CANON = ["tool.py", "index.html", "requirements.txt", "README.md", "LICENSE", "PRIVACY.md"]


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
    a = _run_builder(1)
    b = _run_builder(2)
    c = _run_builder(987654321)
    for space in SPACES:
        assert a[space] == b[space] == c[space], f"non-deterministic bundle for {space}"


# ---- canonical form (guarantees cross-interpreter identical tool.py) ---------

@pytest.mark.parametrize("space", ["assetfare-quote", "assetfare-capabilities"])
def test_tool_py_canonical_form(bundles, space):
    import re

    src = (bundles[space] / "tool.py").read_text()
    imports = [l for l in src.split("\n") if l.startswith(("import ", "from "))]
    assert imports == sorted(imports), "top-level imports must be sorted"
    for name in ("CHAINS", "ENDPOINTS"):
        m = re.search(name + r" = (\{[^{}]*\})", src)
        assert m, f"{name} not found"
        # textual element order (NOT list(set(...)), whose order is hash-dependent)
        elems = re.findall(r"'([^']*)'", m.group(1))
        assert elems == sorted(elems), f"{name} elements must be sorted (textually)"


@pytest.mark.parametrize("space", SPACES)
def test_tool_py_imports_sorted(bundles, space):
    src = (bundles[space] / "tool.py").read_text()
    imports = [l for l in src.split("\n") if l.startswith(("import ", "from "))]
    assert imports == sorted(imports), f"{space}: top-level imports must be sorted"


@pytest.mark.parametrize("space", SPACES)
def test_tool_py_set_attrs_sorted(bundles, space):
    # Every UPPER_CASE set-literal class attribute must be textually sorted so the
    # serialized bundle is deterministic across hash seeds / interpreters.
    import re

    src = (bundles[space] / "tool.py").read_text()
    for m in re.finditer(r"^[ \t]*([A-Z_][A-Z0-9_]*) = (\{[^{}]*\})$", src, flags=re.MULTILINE):
        rhs = m.group(2)
        if ":" in rhs:  # dict literal, not a set
            continue
        elems = re.findall(r"'([^']*)'", rhs)
        assert elems == sorted(elems), f"{space}: set attr {m.group(1)} not sorted"


def test_bundle_bytes_deterministic_across_interpreters():
    # Build with an alternate CPython (path in SMOLAGENTS_ALT_PYTHON, a venv that has
    # smolagents==1.26.0) and assert byte-identical bundles. Skips if unset. This is
    # the regression for the cross-3.10/3.12 order drift that canonicalize() fixes.
    import os

    alt = os.environ.get("SMOLAGENTS_ALT_PYTHON")
    if not alt or not Path(alt).exists():
        pytest.skip("SMOLAGENTS_ALT_PYTHON not set")
    build_bundles.build()  # current interpreter
    here = {s: _space_sha(ROOT / "hub_bundles" / s) for s in SPACES}
    builder = ROOT / "hub" / "build_bundles.py"
    r = subprocess.run([alt, str(builder)], cwd=str(ROOT), capture_output=True, text=True, timeout=180, check=False)
    assert r.returncode == 0, r.stderr
    there = {s: _space_sha(ROOT / "hub_bundles" / s) for s in SPACES}
    for space in SPACES:
        assert here[space] == there[space], f"cross-interpreter bundle mismatch for {space}"
