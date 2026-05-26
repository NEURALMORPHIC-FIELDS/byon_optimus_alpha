"""Gradio UI for the BYON Alpha App.

Usable by non-technical people: type a message, see BYON's answer AND its epistemic
status. The UI displays BYON output only — it never decides truth, never rewrites
UNKNOWN/REFUSED into a guess, and never calls Claude directly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import gradio as gr

from .audit_view import compact, render_audit
from .local_config import AlphaConfig
from .runtime_manager import RuntimeStatus
from .user_store import UILogStore

_STATUS_EMOJI = {"KNOWN": "✅ KNOWN", "UNKNOWN": "❓ UNKNOWN", "DISPUTED": "⚖️ DISPUTED",
                 "REFUSED": "⛔ REFUSED", "ERROR": "⚠️ ERROR"}


def _assistant_text(resp) -> str:
    if resp.epistemic_status == "KNOWN" and resp.answer:
        return resp.answer
    if resp.epistemic_status == "UNKNOWN":
        return "❓ UNKNOWN — BYON has no grounded answer for this (it will not guess)."
    if resp.epistemic_status == "DISPUTED":
        return f"⚖️ DISPUTED — {resp.answer or 'BYON found conflicting information.'}"
    if resp.epistemic_status == "REFUSED":
        return f"⛔ REFUSED — {resp.answer or 'BYON declined to answer.'}"
    if resp.epistemic_status == "ERROR":
        return f"⚠️ ERROR — {resp.answer or 'BYON runtime is not available.'}"
    return resp.answer or "(no content)"


def build_ui(config: AlphaConfig, status: RuntimeStatus) -> "gr.Blocks":
    client = status.client
    logs = UILogStore(config.logs_dir)

    banner = ("### 🟣 BYON Alpha"
              + ("\n\n> **DEMO MODE — NOT REAL BYON RUNTIME** (canned responses, UI testing only)"
                 if status.mode == "DEMO" else ""))
    health_line = (f"Mode: **{status.mode}** · Gateway: `{config.gateway_url}` · "
                   f"reachable: **{status.gateway_reachable}**")

    with gr.Blocks(title="BYON Alpha") as demo:
        gr.Markdown(banner)
        gr.Markdown(health_line)
        last_trace = gr.State("")

        with gr.Row():
            user_id = gr.Textbox(label="User ID", value=config.default_user_id, scale=1)
            session_id = gr.Textbox(label="Session ID", value=config.default_session_id, scale=1)

        chatbot = gr.Chatbot(label="BYON", height=420)  # gradio 6 uses messages format (role/content dicts)
        with gr.Row():
            msg = gr.Textbox(label="Your message", placeholder="Ask BYON…", scale=4, autofocus=True)
            send = gr.Button("Send", variant="primary", scale=1)

        with gr.Row():
            status_box = gr.Textbox(label="Epistemic status", interactive=False)
            grounded_box = gr.Textbox(label="Grounded", interactive=False)
            trace_box = gr.Textbox(label="Audit trace ID", interactive=False)

        with gr.Row():
            grounding_json = gr.JSON(label="Grounding summary")
            memory_json = gr.JSON(label="Memory write summary")
            fcem_json = gr.JSON(label="FCE-M summary")

        with gr.Row():
            clear_btn = gr.Button("Clear chat")
            forget_btn = gr.Button("Forget this user memory")
            audit_btn = gr.Button("Show last audit trace")
            export_btn = gr.Button("Export logs")

        info_box = gr.Textbox(label="Info / audit", interactive=False, lines=8)

        def on_send(message: str, history: List[Dict[str, str]], uid: str, sid: str):
            history = history or []
            if not message or not message.strip():
                return history, "", "", "", "", {}, {}, {}, last_trace.value, "Type a message first."
            if not uid or not uid.strip():
                return history, message, "ERROR", "false", "", {}, {}, {}, "", "User ID is required."
            if not sid or not sid.strip():
                return history, message, "ERROR", "false", "", {}, {}, {}, "", "Session ID is required."
            try:
                resp = client.chat(uid.strip(), sid.strip(), message.strip())
            except ValueError as exc:
                return history, message, "ERROR", "false", "", {}, {}, {}, "", str(exc)

            history = history + [
                {"role": "user", "content": message.strip()},
                {"role": "assistant", "content": _assistant_text(resp)},
            ]
            logs.append(user_id=uid.strip(), session_id=sid.strip(), message=message.strip(),
                        response=resp.answer, epistemic_status=resp.epistemic_status,
                        grounded=resp.grounded, audit_trace_id=resp.audit_trace_id)
            return (history, "", _STATUS_EMOJI.get(resp.epistemic_status, resp.epistemic_status),
                    "true" if resp.grounded else "false", resp.audit_trace_id or "—",
                    resp.grounding_summary or {}, resp.memory_summary or {},
                    resp.fcem_summary or {}, resp.audit_trace_id or "", "")

        outputs = [chatbot, msg, status_box, grounded_box, trace_box,
                   grounding_json, memory_json, fcem_json, last_trace, info_box]
        send.click(on_send, [msg, chatbot, user_id, session_id], outputs)
        msg.submit(on_send, [msg, chatbot, user_id, session_id], outputs)

        def on_clear():
            return [], "", "", "", {}, {}, {}, "Chat cleared."
        clear_btn.click(on_clear, None,
                        [chatbot, status_box, grounded_box, trace_box,
                         grounding_json, memory_json, fcem_json, info_box])

        def on_forget(uid: str, sid: str):
            if not uid or not uid.strip():
                return "User ID is required."
            out = client.forget(uid.strip(), (sid or "").strip())
            return out.get("message", "Forget requested.")
        forget_btn.click(on_forget, [user_id, session_id], info_box)

        def on_audit(trace_id: str):
            return render_audit(client, trace_id)
        audit_btn.click(on_audit, last_trace, info_box)

        def on_export(uid: str, sid: str):
            if not uid or not uid.strip() or not sid or not sid.strip():
                return "User ID and Session ID are required to export logs."
            p = logs.path_for(uid.strip(), sid.strip())
            return f"Logs file: {p.resolve()}" if p.exists() else f"No logs yet at: {p.resolve()}"
        export_btn.click(on_export, [user_id, session_id], info_box)

    return demo
