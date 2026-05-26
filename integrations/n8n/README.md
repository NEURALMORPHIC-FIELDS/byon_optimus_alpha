# n8n → BYON (third-stage automation hooks)

n8n is the **automation muscle**, not the interface and not the authority. BYON
decides; n8n executes controlled workflows. Default `BYON_ENABLE_N8N=false` in alpha.

Allowed automations in alpha:
1. feedback capture (`byon-feedback.workflow.json`)
2. daily alpha report (`byon-webhook.workflow.json` — scheduled metrics pull from `/v1/admin/metrics`)
3. admin notification
4. memory audit export

**Forbidden in alpha** (no autonomous side effects): sending emails, calendar edits,
financial actions, file deletion, account changes. Any sensitive action requires
explicit human approval (`G29`).

Gates `G27..G29`: feedback intake + daily report are validated; the
no-sensitive-action-without-approval rule is a configuration invariant of these
workflows (no sensitive nodes are wired).
