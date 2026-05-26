"""Uvicorn entrypoint for the BYON Gateway.

    python -m gateway.server         # binds BYON_GATEWAY_PORT (default 8090)

Production uses the HTTP backend (BYON_ORCHESTRATOR_URL). If BYON is unreachable,
chat responses come back as ERROR with no answer — the Gateway never fabricates.
"""
from __future__ import annotations

from .app import create_app
from .config import GatewayConfig


def main() -> None:
    import uvicorn
    cfg = GatewayConfig.from_env()
    app = create_app(cfg)
    uvicorn.run(app, host="127.0.0.1", port=cfg.gateway_port)


app = create_app()  # module-level app for `uvicorn gateway.server:app`

if __name__ == "__main__":
    main()
