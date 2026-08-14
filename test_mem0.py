"""
test_mem0.py — Prueba de memoria persistente con mem0ai
────────────────────────────────────────────────────────────────────────────────
Simula:
  • Día 1: el cliente comparte preferencias (talla, color, presupuesto).
  • Día 5: el bot recupera esas memorias para personalizar la respuesta.

Uso:
  set OPENAI_API_KEY=sk-...
  pip install mem0ai
  python test_mem0.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Asegura que la raíz del proyecto esté en el path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.memory_service import CustomerMemoryManager


def _parse_turn(turn: str | tuple[str, str] | list[str]) -> tuple[str, str | None]:
    """
    Normaliza un turno de conversación para save_interaction().

    Acepta:
      - tupla/lista de 2 strings → (user_msg, bot_msg)
      - string suelto → (user_msg, None)
    """
    if isinstance(turn, str):
        return turn.strip(), None

    if isinstance(turn, (tuple, list)):
        if len(turn) == 0:
            return "", None
        if len(turn) == 1:
            return str(turn[0]).strip(), None
        if len(turn) >= 2:
            return str(turn[0]).strip(), str(turn[1]).strip()

    return str(turn).strip(), None


def _separator(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    _separator("INICIO — Prueba mem0ai / CustomerMemoryManager")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("\n❌ OPENAI_API_KEY no encontrada en .env")
        print("   Agrega tu clave en .env y vuelve a ejecutar:")
        print("   OPENAI_API_KEY=sk-...")
        sys.exit(1)

    print(f"\n✅ OPENAI_API_KEY detectada ({api_key[:8]}...)")

    memory = CustomerMemoryManager()
    if not memory.is_available:
        print("\n❌ CustomerMemoryManager no pudo inicializarse.")
        print("   Verifica: pip install mem0ai")
        sys.exit(1)

    # Cliente de prueba — en producción sería el teléfono WhatsApp o lead_id
    user_id = "573001234567"

    # ── DÍA 1: conversación inicial — el cliente comparte preferencias ────────
    _separator("DÍA 1 — Guardando preferencias del cliente")

    day1_messages: list[str | tuple[str, str]] = [
        (
            "Hola, busco enterizos deportivos. Uso talla 38 en calzado y M en ropa. "
            "Me gusta mucho el color negro. Mi presupuesto máximo es $120.000 COP.",
            "Perfecto, anoto tus preferencias: talla M, calzado 38, color negro "
            "y presupuesto hasta $120.000. Te aviso cuando lleguen enterizos que encajen.",
        ),
    ]

    for i, turn in enumerate(day1_messages, start=1):
        user_msg, bot_msg = _parse_turn(turn)
        if not user_msg:
            print(f"\n[Turno {i}] ⚠️  Turno vacío — omitido")
            continue
        preview = user_msg[:80] + ("..." if len(user_msg) > 80 else "")
        print(f"\n[Turno {i}] Cliente: {preview}")
        result = memory.save_interaction(user_id, user_msg, bot_msg)
        if result.get("ok"):
            print(f"   ✅ Memoria guardada — {result.get('result', {})}")
        else:
            print(f"   ❌ Error: {result.get('error')}")

    # Mostrar todas las memorias extraídas tras el Día 1
    all_memories = memory.get_all_memories(user_id)
    print(f"\n📋 Total memorias almacenadas para {user_id}: {len(all_memories)}")
    for mem in all_memories:
        text = mem.get("memory") or mem.get("text") or str(mem)
        print(f"   • {text}")

    # ── DÍA 5: nueva consulta — recuperar contexto semántico ──────────────────
    _separator("DÍA 5 — Recuperando memorias para nueva consulta")

    day5_query = (
        "Hola de nuevo, ¿tienen enterizos en mi talla y dentro de mi presupuesto?"
    )
    print(f"\n[Consulta Día 5] Cliente: {day5_query}")

    context = memory.get_memories_context(user_id, day5_query)

    if context:
        print("\n🧠 Contexto recuperado (listo para System Prompt):\n")
        print(context)
    else:
        print("\n⚠️  No se recuperaron memorias relevantes.")
        print("   Esto puede ocurrir si mem0 aún está indexando o la query no coincide.")

    # Segunda búsqueda más específica
    _separator("BÚSQUEDA ESPECÍFICA — color y calzado")
    context2 = memory.get_memories_context(
        user_id,
        "¿Recuerdas qué color y talla de calzado prefiero?",
    )
    print(context2 or "(sin resultados)")

    _separator("FIN — Prueba completada")
    print("\nSi ves las preferencias del Día 1 en el contexto del Día 5, mem0 funciona ✅\n")


if __name__ == "__main__":
    main()
