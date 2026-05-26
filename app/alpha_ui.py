"""Gradio UI for BYON — epistemic research interface.

The user sees WHY BYON answered, not just the answer: epistemic status, confidence, the
research clock (elapsed / stress% / phase / sources searched), the multi-perspective
synthesis, web sources, and the per-user memory (candidates / committed / disputed). The UI
only displays BYON output — it never decides truth, never rewrites UNKNOWN, never calls Claude
or the web directly. The 5-minute permission gate surfaces as Continue / Conclude buttons.
"""
from __future__ import annotations

from typing import Any, Dict, List

import gradio as gr

from .audit_view import render_audit
from .local_config import AlphaConfig
from .runtime_manager import RuntimeStatus
from .user_store import UILogStore

_BADGE = {
    "KNOWN": "✅ KNOWN", "PROVISIONAL": "🟡 PROVISIONAL",
    "PROVISIONAL_UNVERIFIED": "🟠 PROVISIONAL (unverified)", "DISPUTED": "⚖️ DISPUTED",
    "NEEDS_MORE_TIME": "⏳ NEEDS MORE TIME", "ASK_USER_FOR_SOURCE": "❓ NEEDS A SOURCE",
    "UNKNOWN": "❓ UNKNOWN", "REFUSED": "⛔ REFUSED", "ERROR": "⚠️ ERROR",
}


def _assistant_text(out: Dict[str, Any]) -> str:
    st = out.get("epistemic_status", "ERROR")
    ans = out.get("answer", "") or ""
    if st == "KNOWN":
        return ans or "(grounded, no text)"
    if st == "UNKNOWN":
        return "❓ UNKNOWN — BYON searched the available sources and has no grounded answer (it will not guess)."
    prefix = _BADGE.get(st, st)
    return f"{prefix} — {ans}" if ans else prefix


def build_ui(config: AlphaConfig, status: RuntimeStatus) -> "gr.Blocks":
    client = status.client
    logs = UILogStore(config.logs_dir)
    demo_mode = status.mode == "DEMO"

    banner = ("### 🟣 BYON — Epistemic Research"
              + ("\n\n> **DEMO MODE — NOT REAL BYON** (canned, UI testing only)" if demo_mode else ""))

    with gr.Blocks(title="BYON Epistemic Research") as demo:
        gr.Markdown(banner)
        gr.Markdown(f"Mode: **{status.mode}** · Gateway: `{config.gateway_url}` · reachable: **{status.gateway_reachable}**")
        last_trace = gr.State("")     # research_trace_id (for continue/conclude)
        last_question = gr.State("")
        last_audit = gr.State("")

        with gr.Row():
            user_id = gr.Textbox(label="User ID", value=config.default_user_id, scale=2)
            session_id = gr.Textbox(label="Session ID", value=config.default_session_id, scale=2)
            allow_claude = gr.Checkbox(label="Allow Claude (hypothesis)", value=True, scale=1)
            allow_web = gr.Checkbox(label="Allow Web", value=False, scale=1)

        chatbot = gr.Chatbot(label="BYON", height=380)
        with gr.Row():
            msg = gr.Textbox(label="Ask BYON", placeholder="Ask a question, or 'remember that …' to teach.",
                             scale=4, autofocus=True)
            send = gr.Button("Send", variant="primary", scale=1)

        with gr.Row():
            status_box = gr.Textbox(label="Epistemic status", interactive=False)
            grounded_box = gr.Textbox(label="Grounded", interactive=False)
            confidence_box = gr.Textbox(label="Confidence", interactive=False)
            trace_box = gr.Textbox(label="Audit trace", interactive=False)

        with gr.Accordion("🔎 Research clock & sources", open=True):
            with gr.Row():
                stress_box = gr.Textbox(label="Stress %", interactive=False)
                elapsed_box = gr.Textbox(label="Elapsed (s)", interactive=False)
                phase_box = gr.Textbox(label="Phase", interactive=False)
            sources_box = gr.Textbox(label="Sources searched", interactive=False)
            with gr.Row():
                continue_btn = gr.Button("Continue research 5 min")
                conclude_btn = gr.Button("Conclude now")
                stop_btn = gr.Button("Stop research")

        with gr.Accordion("🧭 Why this answer (synthesis & sources)", open=False):
            synthesis_json = gr.JSON(label="Multi-perspective synthesis")
            web_json = gr.JSON(label="Web sources (evidence candidates, not committed truth)")
            claude_json = gr.JSON(label="Claude hypothesis (not authority)")

        with gr.Accordion("🧠 Memory (per-user) — candidates / committed / disputed", open=False):
            with gr.Row():
                cand_json = gr.JSON(label="Candidates (provisional + evidence)")
                committed_json = gr.JSON(label="Committed")
                disputed_json = gr.JSON(label="Disputed")
            with gr.Row():
                consolidate_btn = gr.Button("Consolidate memory")
                refresh_mem_btn = gr.Button("Refresh memory")

        with gr.Accordion("📥 Teach / ingest", open=False):
            teach_box = gr.Textbox(label="Teach a fact (stored as your grounded memory)",
                                   placeholder="e.g. my project codename is Orion")
            teach_btn = gr.Button("Teach this")

        with gr.Row():
            clear_btn = gr.Button("Clear chat")
            forget_btn = gr.Button("Forget my memory")
            audit_btn = gr.Button("Show last audit trace")
            export_btn = gr.Button("Export logs")
        info_box = gr.Textbox(label="Info / audit", interactive=False, lines=8)

        with gr.Accordion("🫀 Life State (LifeLoop v2 — internal circulation, never answers you)", open=False):
            life_summary = gr.Markdown("LifeLoop state not loaded yet.")
            life_tasks = gr.JSON(label="Pending internal research tasks")
            life_json = gr.JSON(label="Full LifeLoop status")
            with gr.Row():
                refresh_life = gr.Button("Refresh state")
                tick_btn = gr.Button("Run LifeLoop tick")
                life_consolidate_btn = gr.Button("Run consolidation")
            with gr.Row():
                task_id_box = gr.Textbox(label="Task id (for run/approve/cancel)", scale=2)
                run_task_btn = gr.Button("Run selected task")
                approve_web_btn = gr.Button("Approve selected web research")
                cancel_task_btn = gr.Button("Cancel selected task")
            life_action_info = gr.Textbox(label="LifeLoop action result", interactive=False, lines=4)

        with gr.Accordion("Runtime health", open=False):
            health_json = gr.JSON()
            refresh_health = gr.Button("Refresh health")

        # ---- helpers --------------------------------------------------------
        def _apply(out: Dict[str, Any], history: List[Dict[str, str]], uid, sid, question):
            history = (history or []) + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": _assistant_text(out)},
            ]
            clock = out.get("clock") or {}
            logs.append(user_id=uid, session_id=sid, message=question,
                        response=out.get("answer", ""), epistemic_status=out.get("epistemic_status", ""),
                        grounded=bool(out.get("grounded")), audit_trace_id=out.get("audit_trace_id", ""))
            return (history,
                    _BADGE.get(out.get("epistemic_status"), out.get("epistemic_status", "")),
                    "true" if out.get("grounded") else "false",
                    str(out.get("confidence", "")),
                    out.get("audit_trace_id", "") or "—",
                    str(out.get("stress_percent", clock.get("stress_percent", ""))),
                    str(clock.get("elapsed_seconds", "")),
                    out.get("phase", clock.get("phase", "")),
                    ", ".join(out.get("sources_searched", []) or []),
                    out.get("synthesis") or {}, out.get("web_results") or [],
                    out.get("claude_hypothesis"),
                    out.get("research_trace_id", ""), question, out.get("audit_trace_id", ""))

        _send_outputs = [chatbot, status_box, grounded_box, confidence_box, trace_box,
                         stress_box, elapsed_box, phase_box, sources_box,
                         synthesis_json, web_json, claude_json, last_trace, last_question, last_audit]

        def on_send(message, history, uid, sid, a_claude, a_web):
            if not (message or "").strip():
                return (history or [], "", "", "", "", "", "", "", "", {}, [], None, "", "", "")
            if not uid.strip() or not sid.strip():
                return (history or [], "ERROR", "false", "", "", "", "", "", "", {}, [], None, "", "", "")
            out = client.research(uid.strip(), sid.strip(), message.strip(),
                                  allow_web=bool(a_web), allow_claude=bool(a_claude), action="start")
            res = _apply(out, history, uid.strip(), sid.strip(), message.strip())
            return (res[0], res[1], res[2], res[3], res[4], res[5], res[6], res[7], res[8],
                    res[9], res[10], res[11], res[12], res[13], res[14])

        send.click(on_send, [msg, chatbot, user_id, session_id, allow_claude, allow_web], _send_outputs)
        msg.submit(on_send, [msg, chatbot, user_id, session_id, allow_claude, allow_web], _send_outputs)
        send.click(lambda: "", None, msg)

        def on_action(action, history, uid, sid, a_claude, a_web, trace, question):
            if not trace or not question:
                return on_send("(no active research)", history, uid, sid, a_claude, a_web)
            out = client.research(uid.strip(), sid.strip(), question,
                                  allow_web=bool(a_web), allow_claude=bool(a_claude),
                                  action=action, research_trace_id=trace)
            res = _apply(out, history, uid.strip(), sid.strip(), f"[{action}] {question}")
            return (res[0], res[1], res[2], res[3], res[4], res[5], res[6], res[7], res[8],
                    res[9], res[10], res[11], res[12], res[13], res[14])

        continue_btn.click(lambda h, u, s, c, w, t, q: on_action("continue", h, u, s, c, w, t, q),
                           [chatbot, user_id, session_id, allow_claude, allow_web, last_trace, last_question],
                           _send_outputs)
        conclude_btn.click(lambda h, u, s, c, w, t, q: on_action("conclude", h, u, s, c, w, t, q),
                           [chatbot, user_id, session_id, allow_claude, allow_web, last_trace, last_question],
                           _send_outputs)
        stop_btn.click(lambda: ("⏹ research stopped", ""), None, [info_box, last_trace])

        def on_teach(text, history, uid, sid):
            if not text.strip():
                return history or [], "Type a fact to teach."
            out = client.research(uid.strip(), sid.strip(), f"remember that {text.strip()}", action="start")
            history = (history or []) + [
                {"role": "user", "content": f"(teach) {text.strip()}"},
                {"role": "assistant", "content": _assistant_text(out)}]
            return history, f"Stored: {out.get('answer','')}"
        teach_btn.click(on_teach, [teach_box, chatbot, user_id, session_id], [chatbot, info_box])

        def on_memory(uid):
            st = client.memory_status(uid.strip()) if hasattr(client, "memory_status") else {}
            return st.get("candidates", []), st.get("committed", []), st.get("disputed", [])
        refresh_mem_btn.click(on_memory, user_id, [cand_json, committed_json, disputed_json])

        def on_consolidate(uid):
            out = client.consolidate(uid.strip()) if hasattr(client, "consolidate") else {}
            st = client.memory_status(uid.strip()) if hasattr(client, "memory_status") else {}
            return (f"Consolidation: promoted {out.get('promoted', [])}",
                    st.get("candidates", []), st.get("committed", []), st.get("disputed", []))
        consolidate_btn.click(on_consolidate, user_id, [info_box, cand_json, committed_json, disputed_json])

        def on_clear():
            return [], "", "", "", "", "", "", "", "", {}, [], None, "chat cleared"
        clear_btn.click(on_clear, None,
                        [chatbot, status_box, grounded_box, confidence_box, trace_box,
                         stress_box, elapsed_box, phase_box, sources_box,
                         synthesis_json, web_json, claude_json, info_box])

        def on_forget(uid, sid):
            return client.forget(uid.strip(), sid.strip()).get("message", "forget requested")
        forget_btn.click(on_forget, [user_id, session_id], info_box)

        audit_btn.click(lambda t: render_audit(client, t), last_audit, info_box)

        def on_export(uid, sid):
            p = logs.path_for(uid.strip(), sid.strip())
            return f"Logs: {p.resolve()}" if p.exists() else f"No logs yet: {p.resolve()}"
        export_btn.click(on_export, [user_id, session_id], info_box)

        def on_health():
            if demo_mode:
                return {"Gateway": "DEMO"}
            from .health_checks import summarize
            return summarize(config.gateway_url)
        refresh_health.click(on_health, None, health_json)

        # ---- Life State panel (all actions go through the Gateway client) ----
        def _life_summary(ll: Dict[str, Any]) -> str:
            tops = ", ".join(f"{t['topic'][:30]} ({t['pressure']})" for t in (ll.get("top_pressure_topics") or [])[:3]) or "none"
            return (f"**LifeLoop {ll.get('version','?')}** · running={ll.get('enabled')} · "
                    f"answers user directly: **{ll.get('answers_user_directly')}** · "
                    f"truth authority: **{ll.get('is_truth_authority')}**\n\n"
                    f"- pressure total: **{ll.get('pressure_total')}** · top: {tops}\n"
                    f"- unknown rate: {ll.get('unknown_rate')} · disputed rate: {ll.get('disputed_rate')}\n"
                    f"- pending research tasks: **{len(ll.get('pending_research_tasks') or [])}** · "
                    f"consolidations: {ll.get('consolidation_count')}\n"
                    f"- active/tombstoned vault facts: {ll.get('active_vault_facts')}/{ll.get('tombstoned_vault_facts')}\n"
                    f"- read consistency: {ll.get('memory_service_read_consistency_mode')}")

        def on_life_refresh():
            data = client.lifeloop_state()
            ll = data.get("lifeloop", data)
            return _life_summary(ll), (ll.get("pending_research_tasks") or []), ll

        def on_life_tick():
            client.lifeloop_tick()
            return on_life_refresh()

        def on_life_consolidate(uid):
            r = client.consolidate((uid or "user").strip())
            s, t, j = on_life_refresh()
            return s, t, j, f"consolidation: {r.get('fce_status', r.get('message', r))}"

        def on_run_task(tid):
            r = client.lifeloop_run_task((tid or "").strip())
            return f"run-task: {r}"

        def on_approve_web(tid):
            r = client.lifeloop_approve_web((tid or "").strip())
            return f"approve-web: {r}"

        def on_cancel_task(tid):
            r = client.lifeloop_cancel_task((tid or "").strip())
            return f"cancel-task: {r}"

        refresh_life.click(on_life_refresh, None, [life_summary, life_tasks, life_json])
        tick_btn.click(on_life_tick, None, [life_summary, life_tasks, life_json])
        life_consolidate_btn.click(on_life_consolidate, user_id,
                                   [life_summary, life_tasks, life_json, life_action_info])
        run_task_btn.click(on_run_task, task_id_box, life_action_info)
        approve_web_btn.click(on_approve_web, task_id_box, life_action_info)
        cancel_task_btn.click(on_cancel_task, task_id_box, life_action_info)

    return demo
