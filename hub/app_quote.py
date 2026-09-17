"""Custom Gradio app for the AssetFare Quote Space.

smolagents 1.26's ``launch_gradio_demo`` maps ``output_type`` to a Gradio
component through a table that has NO entry for ``"object"`` — so it raises
``KeyError`` for this tool. This app renders the object output with ``gr.JSON``
directly and never calls ``launch_gradio_demo``.

The primary use of this tool is agent loading via ``load_tool``; this Space demo
is a secondary, human-facing view. It performs a real read-only quote request
against https://api.assetfare.dev when you press Submit.
"""

import gradio as gr
from tool import AssetFareQuoteTool

_tool = AssetFareQuoteTool()


def _run(from_chain, from_token, to_chain, to_token, amount_usd):
    try:
        return _tool.forward(from_chain, from_token, to_chain, to_token, float(amount_usd))
    except Exception as exc:
        return {"error": str(exc)}


def build_demo():
    return gr.Interface(
        fn=_run,
        inputs=[
            gr.Textbox(label="from_chain", value="solana"),
            gr.Textbox(label="from_token", value="SOL"),
            gr.Textbox(label="to_chain", value="base"),
            gr.Textbox(label="to_token", value="ETH"),
            gr.Number(label="amount_usd", value=250),
        ],
        outputs=gr.JSON(label="quote"),
        title="AssetFare Quote (read-only, quote-only)",
        description=(
            "Read-only cross-chain conversion quote via https://api.assetfare.dev. "
            "No wallet, signing, or submission. This demo is a human view of the "
            "agent tool loadable with load_tool(..., trust_remote_code=True)."
        ),
    )


demo = build_demo()

if __name__ == "__main__":
    demo.launch()
