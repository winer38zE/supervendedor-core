"""
Prueba local del ciclo Meta Ads (Capa 5).
Uso: .venv\\Scripts\\python.exe scripts/run_ads_cycle_test.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Raíz del repo en PYTHONPATH
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("FOLLOWUP_SCHEDULER_ENABLED", "false")


async def main() -> None:
    from app.marketing.ads_orchestrator import run_ads_cycle

    result = await run_ads_cycle(
        launch_new_campaign=False,
        evaluar_reglas=True,
        notificar_whatsapp=False,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
