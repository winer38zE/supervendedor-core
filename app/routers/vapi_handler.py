import json
import os
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

# ✅ CORREGIDO: Solo imports críticos en el top
# from app.services.call_auditor import auditar_llamada
from app.services.google_calendar import crear_evento
from app.config import settings
from app.security import verify_vapi_webhook
from app.services.vapi_tools_service import (
    build_vapi_tool_results_async,
    extract_tool_call_list,
    get_vapi_tool_definitions,
    parse_tool_call,
)
from app.agents.prompts_factory import get_system_prompt

router = APIRouter(prefix="/vapi", tags=["Vapi Voice"])

_DEFAULT_CLIENT_ID = "default"
_VAPI_MODEL = "gpt-4o-mini"
_VAPI_PROVIDER = "openai"

_BUSINESS_LABELS = {
    "clinica": {"negocio": "clínica", "accion": "cita médica", "emoji": "🏥"},
    "barberia": {"negocio": "barbería", "accion": "turno de barbería", "emoji": "✂️"},
    "heladeria": {"negocio": "heladería", "accion": "pedido especial", "emoji": "🍦"},
    "tenis": {"negocio": "tienda", "accion": "reserva de producto", "emoji": "👟"},
    "default": {"negocio": "negocio", "accion": "cita", "emoji": "📅"},
}

def _get_label(client_id: str) -> dict:
    for key, label in _BUSINESS_LABELS.items():
        if key in client_id.lower():
            return label
    return _BUSINESS_LABELS["default"]

def handle_agendar_cita(args: dict, client_id: str) -> str:
    """Agenda cita vía Google Calendar — tool Vapi `agendar_cita`."""
    label = _get_label(client_id)
    nombre = args.get("nombre", "cliente")
    fecha = args.get("fecha", "")
    hora = args.get("hora", "")

    if not fecha or not hora:
        return "Necesito la fecha y la hora para agendar. ¿Me los confirmas?"

    titulo = f"{label['emoji']} {label['accion'].capitalize()} — {nombre}"
    result = crear_evento(
        nombre=nombre,
        fecha=fecha,
        hora=hora,
        titulo=titulo,
        client_id=client_id,
    )

    if not result["success"]:
        print(f"[Calendar ERROR] {result.get('error')}")
        return (
            f"Tuve un problema al guardar la cita en el calendario: {result.get('error')}. "
            "Por favor llama de nuevo o escríbenos por WhatsApp."
        )

    modo = " [simulado]" if result.get("mock") else ""
    print(f"[Calendar OK{modo}] client='{client_id}' | {nombre} @ {result['start_iso']} | id={result['event_id']}")

    return (
        f"{label['emoji']} ¡Todo listo! Tu {label['accion']} en la {label['negocio']} "
        f"quedó guardada para el {fecha} a las {hora}, a nombre de {nombre}. "
        f"Recibirás un recordatorio. ¿Hay algo más en que pueda ayudarte?"
    )


def handle_tool_call(tool_name: str, raw_args: str | dict, client_id: str) -> str:
    """Compatibilidad — delega al servicio central de tools Vapi."""
    from app.services.vapi_tools_service import execute_tool

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            args = {}
    else:
        args = raw_args or {}

    return execute_tool(tool_name, args, client_id=client_id)


def _build_assistant_tools(client_id: str) -> list:
    return get_vapi_tool_definitions(include_agenda=True)

def _extract_client_id(request: Request, message: dict) -> str:
    client_id = request.headers.get("x-client-id")
    if not client_id:
        client_id = (
            message.get("call", {}).get("metadata", {}).get("client_id")
            or message.get("metadata", {}).get("client_id")
        )
    return client_id or _DEFAULT_CLIENT_ID

_MOCK_S3_DIR = os.path.join(os.path.dirname(__file__), "..", "agents", "mock_s3")

_ANALYSIS_PROMPT = textwrap.dedent("""\
    Eres un analista experto en mejora de agentes de ventas por voz.
    Analiza la siguiente transcripción de una llamada atendida por un bot de IA
    e identifica oportunidades de mejora concretas.

    Responde ÚNICAMENTE con este formato (sin texto extra):

    ## PREGUNTAS SIN RESPUESTA
    - [Lista las preguntas o temas que el bot no supo responder o respondió mal]

    ## INFORMACIÓN FALTANTE
    - [Datos que el cliente pidió y el bot no tenía: precios, horarios, políticas, etc.]

    ## SUGERENCIAS DE MEJORA
    - [Acciones concretas para que el bot mejore en la próxima llamada]

    ## PUNTUACIÓN DE LA LLAMADA
    [Número del 1 al 10 con una frase de justificación]

    TRANSCRIPCIÓN:
    {transcripcion}
""")

def extract_missed_info(transcripcion: str, client_id: str, call_outcome: str) -> None:
    """✅ CORREGIDO: Imports lazily para evitar circular imports"""
    if not transcripcion or not transcripcion.strip():
        return

    prompt = _ANALYSIS_PROMPT.format(transcripcion=transcripcion.strip())
    analisis = ""

    if getattr(settings, "ANTHROPIC_API_KEY", ""):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            analisis = message.content[0].text
            motor = "Claude Haiku"
        except Exception as e:
            print(f"[Feedback] Anthropic falló: {e}")

    if not analisis and getattr(settings, "GROQ_API_KEY", ""):
        try:
            from groq import Groq
            groq_client = Groq(api_key=settings.GROQ_API_KEY)
            completion = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )
            analisis = completion.choices[0].message.content
            motor = "Llama3 (Groq)"
        except Exception as e:
            print(f"[Feedback] Groq falló: {e}")

    if not analisis:
        analisis = "## TRANSCRIPCIÓN (análisis manual pendiente)\n" + transcripcion
        motor = "sin IA"

    client_dir = os.path.join(_MOCK_S3_DIR, client_id)
    feedback_path = os.path.join(client_dir, "feedback.txt")
    os.makedirs(client_dir, exist_ok=True)

    ts = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S")
    separator = "─" * 60

    entry = (
        f"\n{separator}\n"
        f"📅 LLAMADA: {ts}  |  RESULTADO: {call_outcome}  |  MOTOR: {motor}\n"
        f"{separator}\n"
        f"{analisis.strip()}\n"
    )

    with open(feedback_path, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"[Feedback] Guardado en {feedback_path} usando {motor}")

@router.post("/webhook")
async def vapi_webhook(request: Request, background_tasks: BackgroundTasks):
    verify_vapi_webhook(request)

    try:
        data = await request.json()

        from app.services.processed_events import (
            extract_vapi_event_id,
            is_processed,
            mark_processed,
        )

        event_id = extract_vapi_event_id(data)
        if event_id and is_processed("vapi", event_id):
            return {"status": "ok", "duplicate": True}

        message = data.get("message", {})
        message_type = message.get("type")

        if message_type == "assistant-request":
            client_id = _extract_client_id(request, message)
            system_prompt, modo = get_system_prompt(client_id)
            tools = _build_assistant_tools(client_id)
            print(f"[Vapi] assistant-request | client_id='{client_id}' | modo='{modo}'")
            if event_id:
                mark_processed("vapi", event_id)
            return {
                "assistant": {
                    "model": {
                        "provider": _VAPI_PROVIDER,
                        "model": _VAPI_MODEL,
                        "systemPrompt": system_prompt,
                        "tools": tools,
                    },
                    "metadata": {"modo_operacion": modo},
                }
            }

        if message_type in ("tool-calls", "tool-call"):
            client_id = _extract_client_id(request, message)
            tool_call_list = extract_tool_call_list(message)

            for tool_call in tool_call_list:
                _, tool_name, _ = parse_tool_call(tool_call)
                print(f"[Vapi] tool-call | tool='{tool_name}' | client='{client_id}'")

            results = await build_vapi_tool_results_async(
                tool_call_list,
                client_id=client_id,
            )

            if event_id:
                mark_processed("vapi", event_id)
            return {"results": results}

        if message_type == "end-of-call-report":
            # ✅ CORREGIDO: Imports lazy aquí también
            client_id = _extract_client_id(request, message)
            cliente = message.get("customer", {}).get("number", "Anonimo")
            analisis_raw = message.get("analysis", {})
            exito = bool(analisis_raw.get("successEvaluation", False))
            transcripcion = message.get("transcript", "")
            
            estado = "Cerrado" if exito else "Perdida"
            print(f"[Vapi] end-of-call | {cliente} | client_id='{client_id}' | Estado: {estado}")

            if transcripcion:
                # ✅ Solo intenta analizar si la función existe
                try:
                    if exito:
                        from app.ai_engine import analizar_chat_para_aprender
                        analizar_chat_para_aprender(transcripcion)
                except ImportError:
                    print("[Warning] analizar_chat_para_aprender no disponible, omitiendo")
                
                background_tasks.add_task(extract_missed_info, transcripcion, client_id, estado)

            # ✅ CORREGIDO: evolve_business_logic necesita 3 parámetros (client_id, tenant_id, n)
            try:
                from app.agents.business_evolver import evolve_business_logic
                # Parámetros: client_id, tenant_id (same as client_id), n (número de leads/items)
                background_tasks.add_task(evolve_business_logic, client_id, client_id, 10)
            except ImportError:
                print("[Warning] evolve_business_logic no disponible, omitiendo")

            if event_id:
                mark_processed("vapi", event_id)
            return {"status": "Procesado"}

        if event_id:
            mark_processed("vapi", event_id)

        return {"status": "Ignorado"}

    except Exception as e:
        print(f"Error Vapi: {e}")
        return {"status": "Error"}


@router.post("/tools/webhook")
async def vapi_tools_webhook(request: Request):
    """
    Server URL dedicado para tools Vapi (inventario + ventas + agenda).

    Configura en Vapi: tool.server.url = {PUBLIC_URL}/vapi/tools/webhook
<<<<<<< HEAD

    Acepta message.type = tool-calls | tool-call y responde:
      { "results": [ { "toolCallId": "...", "result": "..." } ] }
=======
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2
    """
    verify_vapi_webhook(request)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    message = data.get("message") or data
    msg_type = message.get("type", "")

    if msg_type not in ("tool-calls", "tool-call"):
        return {"status": "ignored", "reason": f"type={msg_type}"}

    client_id = _extract_client_id(request, message)
    tool_call_list = extract_tool_call_list(message)

    if not tool_call_list:
        return {"results": []}

    results = await build_vapi_tool_results_async(
        tool_call_list,
        client_id=client_id,
    )
    return {"results": results}
