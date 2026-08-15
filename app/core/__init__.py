"""
app/core — Núcleo ED NET PRO 3.0

Registro de routers, ciclo de vida y metadatos de plataforma.
"""

from app.core.platform import PLATFORM, PlatformChannel
from app.core.router_registry import register_platform_routers

__all__ = ["PLATFORM", "PlatformChannel", "register_platform_routers"]
