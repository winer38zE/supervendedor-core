"""
Compat — reexporta require_master_key desde app.security.
"""

from app.security import require_master_key

__all__ = ["require_master_key"]
