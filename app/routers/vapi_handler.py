import json
import os
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, BackgroundTasks, Request

# ✅ CORREGIDO: Solo imports críticos en el top
# from app.services.call_auditor import auditar_llamada
from app.services.google_calendar import crear_evento
from app.config import settings
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

def handle_tool_call(tool_name: str, raw_args: str | dict, client_id: str) -> str:
    label = _get_label(client_id)

    if tool_name == "agendar_cita":
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            nombre = args.get("nombre", "cliente")
            fecha = args.get("fecha", "")
            hora = args.get("hora", "")
        except (json.JSONDecodeError, AttributeError):
            return "No pude procesar los datos de la cita. Por favor repite nombre, fecha y hora."

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

    return f"La herramienta '{tool_name}' no está disponible en este momento."

def _build_assistant_tools(client_id: str) -> list:
    label = _get_label(client_id)
    webhook_url = os.environ.get("PUBLIC_URL", "").rstrip("/") + "/vapi/webhook"

    tool = {
        "type": "function",
        "function": {
            "name": "agendar_cita",
            "description": (
                f"Agenda una {label['accion']} en la {label['negocio']}. "
                f"Úsala SOLO cuando el cliente haya confirmado explícitamente su nombre, "
                f"la fecha y la hora."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": "Nombre completo del cliente.",
                    },
                    "fecha": {
                        "type": "string",
                        "description": "Fecha de la cita (YYYY-MM-DD o descripción natural como 'mañana').",
                    },
                    "hora": {
                        "type": "string",
                        "description": "Hora de la cita en formato HH:MM o descripción natural como '3 de la tarde'.",
                    },
                },
                "required": ["nombre", "fecha", "hora"],
            },
        },
    }

    if os.environ.get("PUBLIC_URL"):
        tool["server"] = {"url": webhook_url}

    return [tool]

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
    """✅ CORREGIDO: Lazy imports dentro del endpoint para evitar issues al iniciar"""
    try:
        data = await request.json()
        message = data.get("message", {})
        message_type = message.get("type")

        if message_type == "assistant-request":
            client_id = _extract_client_id(request, message)
            system_prompt, modo = get_system_prompt(client_id)
            tools = _build_assistant_tools(client_id)
            print(f"[Vapi] assistant-request | client_id='{client_id}' | modo='{modo}'")
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
            if message_type == "tool-calls":
                tool_call_list = message.get("toolCallList", [])
            else:
                single = message.get("toolCall") or message.get("toolCallList", [{}])[0]
                tool_call_list = [single]

            results = []
            for tool_call in tool_call_list:
                tool_id = tool_call.get("id", "")
                function = tool_call.get("function", {})
                tool_name = function.get("name", "")
                raw_args = function.get("arguments", "{}")

                print(f"[Vapi] tool-call | tool='{tool_name}' | client='{client_id}'")
                result_text = handle_tool_call(tool_name, raw_args, client_id)
                results.append({"toolCallId": tool_id, "result": result_text})

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

            return {"status": "Procesado"}

        return {"status": "Ignorado"}

    except Exception as e:
        print(f"Error Vapi: {e}")
        return {"status": "Error"}
