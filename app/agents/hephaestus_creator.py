"""
app/agents/hephaestus_creator.py
────────────────────────────────────────────────────────────────────────────────
Hephaestus — Forjador de creativos: fichas visuales, catálogo y propuestas PDF.

Usa imágenes reales del catálogo Shein (catalog_bridge) cuando están disponibles.
Sin dependencia de Vertex AI.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_VAULT = Path(os.environ.get("LOCAL_STORAGE_DIR", "app/storage_vault")) / "creatives"
_VAULT.mkdir(parents=True, exist_ok=True)


class HephaestusCreator:
    """Genera entregables visuales/comerciales bajo demanda."""

    def generate_catalog_delivery(
        self,
        product: dict[str, Any],
        client_name: str = "Cliente",
    ) -> dict[str, Any]:
        """
        Ficha visual de catálogo para WhatsApp.
        Returns: {text, image_url, file_path}
        """
        titulo = product.get("titulo", "Producto destacado")
        precio = product.get("precio_reventa") or product.get("precio_cop", 0)
        imagen = product.get("imagen_url") or product.get("producto_url", "")
        url = product.get("producto_url", "")

        text = (
            f"🔥 *FICHA DE CATÁLOGO — Hephaestus*\n\n"
            f"📦 *{titulo}*\n"
            f"💰 Precio: *${precio:,.0f} COP*\n"
            f"✅ Pago contra entrega — Cúcuta y envío nacional\n"
            f"🛡️ Garantía de satisfacción\n"
        )
        if url:
            text += f"\n🔗 Ver más: {url}"

        file_path = self._save_ficha_txt(titulo, text, client_name)
        return {
            "text": text,
            "image_url": imagen,
            "file_path": str(file_path),
            "product_titulo": titulo,
        }

    def generate_visual_hook(
        self, product_name: str, user_context: str = ""
    ) -> dict[str, Any]:
        """Hook visual: prioriza imagen del catálogo; fallback a ficha generada."""
        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        product = bridge.find_product(product_name) or bridge.get_featured_product()
        if product:
            return self.generate_catalog_delivery(product, client_name=user_context or "Prospecto")

        prompt_line = self._generate_hook_copy(product_name, user_context)
        file_path = self._save_ficha_txt(product_name, prompt_line, user_context or "lead")
        return {
            "text": prompt_line,
            "image_url": "",
            "file_path": str(file_path),
            "product_titulo": product_name,
        }

    def forge_instant_proposal(
        self, client_name: str, price: float, product_name: str = ""
    ) -> str:
        """Propuesta formal de cierre (archivo .txt listo para enviar/compartir)."""
        safe_name = "".join(c if c.isalnum() else "_" for c in client_name)[:30]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_name = _VAULT / f"propuesta_{safe_name}_{stamp}.txt"

        body = (
            f"PROPUESTA COMERCIAL — ED NET PRO\n"
            f"{'=' * 40}\n"
            f"Cliente: {client_name}\n"
            f"Producto: {product_name or 'Catálogo seleccionado'}\n"
            f"Precio acordado: ${price:,.0f} COP\n"
            f"Modalidad: Pago contra entrega\n"
            f"Cobertura: Cúcuta / Envío nacional\n"
            f"Validez: 48 horas\n"
            f"{'=' * 40}\n"
            f"Generado por Hephaestus — {datetime.now(timezone.utc).isoformat()}\n"
        )
        file_name.write_text(body, encoding="utf-8")
        print(f"[Hephaestus] Propuesta generada: {file_name}")
        return str(file_name)

    def fulfill_catalog_request(
        self, user_message: str, telefono: str = ""
    ) -> Optional[dict[str, Any]]:
        """
        Atiende pedidos de catálogo/imágenes/PDF en WhatsApp.
        Returns None si el mensaje no es solicitud visual.
        """
        msg = user_message.lower()
        triggers = (
            "catalogo", "catálogo", "imagen", "foto", "fotos", "ver ",
            "muestrame", "muéstrame", "pdf", "propuesta", "modelo",
        )
        if not any(t in msg for t in triggers):
            return None

        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        product = bridge.find_product(user_message) or bridge.get_featured_product()
        if not product:
            return {
                "text": (
                    "Te comparto nuestro catálogo de enterizos deportivos más vendidos. "
                    "Escríbeme el modelo que te interesa y te envío la ficha con foto y precio."
                ),
                "image_url": "",
                "file_path": "",
            }

        delivery = self.generate_catalog_delivery(product, client_name=telefono or "Cliente")

        if "pdf" in msg or "propuesta" in msg:
            pdf_path = self.forge_instant_proposal(
                client_name=telefono or "Cliente",
                price=product.get("precio_reventa") or product.get("precio_cop", 0),
                product_name=product.get("titulo", ""),
            )
            delivery["text"] += f"\n\n📄 Propuesta guardada. Referencia: {Path(pdf_path).name}"
            delivery["file_path"] = pdf_path

        return delivery

    def _save_ficha_txt(self, titulo: str, content: str, client_name: str) -> Path:
        safe = "".join(c if c.isalnum() else "_" for c in titulo)[:40]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = _VAULT / f"ficha_{safe}_{stamp}.txt"
        path.write_text(content, encoding="utf-8")
        return path

    def _generate_hook_copy(self, product_name: str, user_context: str) -> str:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        prompt = (
            f"Escribe un gancho de venta corto (máx 3 líneas) para WhatsApp Status "
            f"sobre '{product_name}'. Contexto: {user_context}. "
            f"Incluye CTA pago contra entrega Cúcuta. Español colombiano."
        )
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                return model.generate_content(prompt).text.strip()
            except Exception:
                pass
        return (
            f"🔥 {product_name} — tendencia del momento\n"
            f"💰 Pago contra entrega en Cúcuta\n"
            f"📲 Escríbeme *QUIERO* y te aparto el tuyo"
        )
