"""Custom Gradio app for the AssetFare Capabilities Space.

smolagents 1.26's ``launch_gradio_demo`` raises ``KeyError`` for
``output_type="object"``, so this app uses ``gr.JSON`` directly and never calls
``launch_gradio_demo``. Pressing Run performs a real read-only capabilities probe
against https://api.assetfare.dev.
"""

import gradio as gr
from tool import AssetFareCapabilitiesTool

_tool = AssetFareCapabilitiesTool()


def _run():
    try:
        return _tool.forward()
    except Exception as exc:
        return {"error": str(exc)}


def build_demo():
    with gr.Blocks(title="AssetFare Capabilities (read-only)") as demo:
        gr.Markdown(
            "# AssetFare Capabilities (read-only)\n"
            "Read-only probe of https://api.assetfare.dev capability/status. "
            "No wallet, signing, or submission. Agent tool loadable with "
            "load_tool(..., trust_remote_code=True)."
        )
        out = gr.JSON(label="capabilities")
        gr.Button("Run").click(fn=_run, inputs=None, outputs=out)
    return demo


demo = build_demo()

if __name__ == "__main__":
    demo.launch()
