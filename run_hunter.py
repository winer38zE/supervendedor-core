"""
run_hunter.py
Runner de Hunter con Lead Scorer + Justificacion AI via Claude.
Busca: Clinicas Esteticas en Cucuta - 5 resultados simulados.
"""

import asyncio
import os
import sys
import io

# Forzar UTF-8 en Windows para evitar UnicodeEncodeError
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(dotenv_path=". env")  # El .env de este proyecto tiene espacio en el nombre

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.hunter.prospecting_engine import ProspectingEngine

# -----------------------------------------------------------------
# Mock enriquecido: 5 clinicas esteticas realistas de Cucuta
# -----------------------------------------------------------------
CLINICAS_CUCUTA = [
    {
        "lugar_id":       "mock_cucuta_001",
        "nombre_negocio": "Centro Estetico Cucuta Bella",
        "direccion":      "Av. 0 # 14-35, Centro, Cucuta, Norte de Santander",
        "telefono":       "+573175824601",
        "sitio_web":      "https://cucutabella.com",
        "rating":         4.7,
        "total_reviews":  134,
        "categoria":      "clinica_estetica, spa, belleza",
        "latitud":        7.8939,
        "longitud":       -72.5078,
        "ciudad":         "Cucuta",
        "pais":           "CO",
        "horario":        {"open_now": True, "weekday_text": ["Lun-Sab 8:00-19:00"]},
        "fotos":          ["ref_cucuta_001a", "ref_cucuta_001b"],
        "metadata":       {"mock": True, "descripcion": "Alta demanda, sin sistema de agendamiento online visible"},
    },
    {
        "lugar_id":       "mock_cucuta_002",
        "nombre_negocio": "Clinica Estetica Adriana Morales",
        "direccion":      "Calle 10 # 5E-42, Barrio Caobos, Cucuta",
        "telefono":       "+573224198730",
        "sitio_web":      "",
        "rating":         4.2,
        "total_reviews":  67,
        "categoria":      "clinica_estetica, medicina_estetica",
        "latitud":        7.9058,
        "longitud":       -72.5123,
        "ciudad":         "Cucuta",
        "pais":           "CO",
        "horario":        {"open_now": True},
        "fotos":          [],
        "metadata":       {"mock": True, "descripcion": "Solo WhatsApp para citas, clientes se quejan de filas"},
    },
    {
        "lugar_id":       "mock_cucuta_003",
        "nombre_negocio": "Laser & Estetica Norte",
        "direccion":      "Diagonal Santander # 3-45, Cucuta",
        "telefono":       "+573118904422",
        "sitio_web":      "https://laserestetianorte.co",
        "rating":         4.9,
        "total_reviews":  212,
        "categoria":      "clinica_estetica, laser, depilacion",
        "latitud":        7.8801,
        "longitud":       -72.4994,
        "ciudad":         "Cucuta",
        "pais":           "CO",
        "horario":        {"open_now": True, "weekday_text": ["Lun-Dom 7:00-20:00"]},
        "fotos":          ["ref_cucuta_003a"],
        "metadata":       {"mock": True, "descripcion": "Excelente rating, agenda manual en libreta segun resenas"},
    },
    {
        "lugar_id":       "mock_cucuta_004",
        "nombre_negocio": "SkinGlow Centro Medico Estetico",
        "direccion":      "Carrera 13 # 8-90, El Llano, Cucuta",
        "telefono":       "",
        "sitio_web":      "",
        "rating":         3.1,
        "total_reviews":  8,
        "categoria":      "clinica_estetica, dermatologia",
        "latitud":        7.9111,
        "longitud":       -72.5201,
        "ciudad":         "Cucuta",
        "pais":           "CO",
        "horario":        None,
        "fotos":          [],
        "metadata":       {"mock": True, "descripcion": "Perfil incompleto, poca actividad online"},
    },
    {
        "lugar_id":       "mock_cucuta_005",
        "nombre_negocio": "Beauty Clinic Cucuta Premium",
        "direccion":      "Av. Libertadores # 22-14, Cucuta",
        "telefono":       "+573001847563",
        "sitio_web":      "https://beautyclinicucuta.com",
        "rating":         4.5,
        "total_reviews":  89,
        "categoria":      "clinica_estetica, spa, rejuvenecimiento",
        "latitud":        7.8722,
        "longitud":       -72.5300,
        "ciudad":         "Cucuta",
        "pais":           "CO",
        "horario":        {"open_now": False, "weekday_text": ["Lun-Vie 9:00-18:00"]},
        "fotos":          ["ref_cucuta_005a", "ref_cucuta_005b"],
        "metadata":       {"mock": True, "descripcion": "Buena presencia web pero sin reservas online integradas"},
    },
]

# -----------------------------------------------------------------
# Justificacion AI via Claude
# -----------------------------------------------------------------
def generar_justificacion_ia(prospecto: dict, lead_score: int) -> str:
    """Genera justificacion del score usando Claude. Fallback a reglas si no hay API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        return _justificacion_por_reglas(prospecto, lead_score)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            "Eres un analista de ventas B2B especializado en automatizacion para clinicas esteticas.\n\n"
            "Analiza este prospecto y justifica en 1-2 oraciones (maximo 120 caracteres) "
            "por que tiene urgencia de automatizar su sistema de citas:\n\n"
            f"Negocio: {prospecto['nombre_negocio']}\n"
            f"Rating Google: {prospecto.get('rating', 'N/A')} ({prospecto.get('total_reviews', 0)} resenas)\n"
            f"Tiene telefono: {'Si' if prospecto.get('telefono') else 'No'}\n"
            f"Tiene web: {'Si' if prospecto.get('sitio_web') else 'No'}\n"
            f"Tiene horario publicado: {'Si' if prospecto.get('horario') else 'No'}\n"
            f"Contexto: {prospecto.get('metadata', {}).get('descripcion', '')}\n"
            f"Lead Score: {lead_score}/10\n\n"
            "Responde SOLO con la justificacion, sin preambulo ni comillas."
        )

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()

    except Exception as e:
        print(f"[WARN] Claude API error: {e}. Usando justificacion por reglas.")
        return _justificacion_por_reglas(prospecto, lead_score)


def _justificacion_por_reglas(prospecto: dict, lead_score: int) -> str:
    """Fallback: justificacion determinista basada en el scoring."""
    rating   = prospecto.get("rating") or 0
    reviews  = prospecto.get("total_reviews") or 0
    tiene_tel = bool(prospecto.get("telefono"))
    tiene_web = bool(prospecto.get("sitio_web"))

    if lead_score >= 8:
        if reviews >= 100 and not tiene_web:
            return "Alto volumen de clientes sin web: saturacion de agenda manual inminente."
        return f"Rating {rating} con {reviews} resenas indica alta demanda; citas automatizadas son criticas."
    elif lead_score >= 6:
        if tiene_tel and not tiene_web:
            return "Solo WhatsApp/llamadas para citas: perdida de clientes fuera de horario laboral."
        return f"Presencia activa ({reviews} resenas) pero agendamiento no optimizado."
    elif lead_score >= 4:
        return "Clinica activa con senales basicas; automatizar citas mejoraria captacion."
    else:
        return "Perfil incompleto: si activa automatizacion, tendria ventaja competitiva inmediata."


# -----------------------------------------------------------------
# Runner principal
# -----------------------------------------------------------------
async def main():
    TENANT_ID = "ednetpro_demo"
    SEP = "-" * 65

    print("\n" + SEP)
    print("  [HUNTER] Motor de Prospeccion — SuperVendedor / EdNetPro")
    print("  Busqueda: 'Clinicas Esteticas en Cucuta'")
    print(f"  Tenant  : {TENANT_ID}")
    print(SEP)

    engine = ProspectingEngine(tenant_id=TENANT_ID)
    prospectos = CLINICAS_CUCUTA[:5]

    resultados_finales = []
    print(f"\n  Procesando {len(prospectos)} prospectos...\n")

    for p in prospectos:
        score         = engine.calificar_lead(p)
        justificacion = generar_justificacion_ia(p, score)

        p_enriquecido = dict(p)
        p_enriquecido["metadata"] = {
            **p.get("metadata", {}),
            "justificacion_ia": justificacion,
        }

        try:
            res = engine.guardar_prospecto(p_enriquecido, score)
            db_status = res.get("status", "?")
        except Exception as e:
            db_status = "sin_conexion"
            print(f"  [WARN] Supabase no disponible para {p['nombre_negocio']}: {type(e).__name__}")

        resultados_finales.append({
            "nombre":     p["nombre_negocio"],
            "telefono":   p.get("telefono") or "N/A",
            "lead_score": score,
            "por_que":    justificacion,
            "supabase":   db_status,
        })
        print(f"  [OK] {p['nombre_negocio']} -> Score: {score}/10 | DB: {db_status}")

    # Ordenar por score desc
    resultados_finales.sort(key=lambda x: x["lead_score"], reverse=True)

    # -----------------------------------------------------------------
    # Tabla de resultados
    # -----------------------------------------------------------------
    print("\n\n" + SEP)
    print("  RESULTADOS FINALES — Lead Scorer con Justificacion IA")
    print(SEP)
    print(f"  {'#':<3} {'SCORE':<7} {'NIVEL':<12} {'NOMBRE':<35} {'TELEFONO':<17}")
    print(f"  {'-'*3} {'-'*6} {'-'*11} {'-'*34} {'-'*16}")

    for i, r in enumerate(resultados_finales, 1):
        score = r["lead_score"]
        nivel = "CALIENTE" if score >= 8 else ("TIBIO" if score >= 6 else ("FRIO" if score >= 4 else "INACTIVO"))
        db    = "[Supabase OK]" if r["supabase"] == "guardado" else f"[{r['supabase']}]"
        print(f"  {i:<3} {score:<7} {nivel:<12} {r['nombre'][:34]:<35} {r['telefono']:<17} {db}")

    print(SEP)
    print("\n  DETALLE DE JUSTIFICACIONES:\n")

    for i, r in enumerate(resultados_finales, 1):
        score = r["lead_score"]
        nivel = "CALIENTE" if score >= 8 else ("TIBIO" if score >= 6 else ("FRIO" if score >= 4 else "INACTIVO"))
        print(f"  #{i} [{nivel} - {score}/10] {r['nombre']}")
        print(f"      Tel    : {r['telefono']}")
        print(f"      Por que: {r['por_que']}")
        print()

    scores    = [r["lead_score"] for r in resultados_finales]
    promedio  = round(sum(scores) / len(scores), 1)
    calientes = sum(1 for s in scores if s >= 7)

    guardados = sum(1 for r in resultados_finales if r["supabase"] == "guardado")
    sin_conn  = sum(1 for r in resultados_finales if r["supabase"] == "sin_conexion")

    print(SEP)
    print(f"  RESUMEN: {len(resultados_finales)} prospectos procesados")
    print(f"  Score promedio : {promedio}/10  |  Leads calientes (>=7): {calientes}/{len(scores)}")
    if guardados:
        print(f"  Guardados en Supabase: {guardados}/{len(resultados_finales)}")
    if sin_conn:
        print(f"  [ATENCION] Supabase sin conexion ({sin_conn} prospectos pendientes de guardar).")
        print(f"  -> Verifica que el proyecto Supabase este activo en: https://supabase.com/dashboard")
        print(f"     URL configurada: {os.environ.get('SUPABASE_URL', 'no definida')[:50]}")
    print(SEP + "\n")

    return resultados_finales


if __name__ == "__main__":
    asyncio.run(main())
