"""
admin_panel/bootstrap.py
Añade admin_panel/ y la raíz del repo a sys.path (local + Streamlit Cloud).
Importar al inicio de dashboard.py y pages/*.py antes de ui/pb_store.
"""

from __future__ import annotations

import sys
from pathlib import Path

ADMIN_PANEL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ADMIN_PANEL_DIR.parent

for _path in (ADMIN_PANEL_DIR, PROJECT_ROOT):
    _s = str(_path)
    if _s not in sys.path:
        sys.path.insert(0, _s)
