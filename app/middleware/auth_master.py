"""
app/middleware/auth_master.py
────────────────────────────────────────────────────────────────────────────────
Dependencia FastAPI para autenticación maestra (endpoints de administración).

Uso:
    from app.middleware.auth_master import require_master_key

    @router.get("/admin/tenants")
    async def list_tenants(auth=Depends(require_master_key)):
        ...

La clave se envía en el header:
    x-master-key: ednetpro_2026
"""

import os
from fastapi import Header, HTTPException, status

MASTER_KEY: str = os.environ.get("MASTER_KEY", "ednetpro_2026")


async def require_master_key(x_master_key: str = Header(..., alias="x-master-key")) -> str:
    """
    Dependencia FastAPI. Valida que el header 'x-master-key' coincida con la
    clave maestra. Lanza 403 si no coincide.

    Returns:
        La clave validada (para uso opcional en la ruta).
    """
    if x_master_key != MASTER_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Clave maestra inválida.",
        )
    return x_master_key
