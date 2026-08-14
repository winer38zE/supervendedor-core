import os
import sys
from pathlib import Path

_panel = Path(__file__).resolve().parents[1]
if str(_panel) not in sys.path:
    sys.path.insert(0, str(_panel))

import bootstrap  # noqa: F401

import streamlit as st

from pb_store import save_planes_config
from ui import require_pocketbase

st.set_page_config(page_title="Planes y Paquetes", page_icon="💼", layout="wide")

st.header("💼 Configuración de Planes y Paquetes — ED NET PRO")

planes_data = {
    "1. Básico (Tarjeta NFC)": {
        "base": 150_000,
        "pma": 50_000,
        "web": "Sencilla (One-page)",
    },
    "2. Intermedio (Chatbot IA)": {
        "base": 350_000,
        "pma": 100_000,
        "web": "Profesional",
    },
    "3. Avanzado (Ing. Ventas + Tokenización)": {
        "base": 850_000,
        "pma": 200_000,
        "web": "Avanzada Futurista (3D/Interactiva)",
    },
}

_, pb_detail = require_pocketbase()
st.caption(f"PocketBase · {pb_detail}")

client_id = st.text_input(
    "ID Cliente / Tenant",
    value=os.getenv("CHAT_TENANT_ID", "edwuar"),
    help="Clave única en PocketBase (colección planes_config).",
)

usar_bundle = st.checkbox("🔥 Activar Pack Completo (Los 3 servicios juntos - 20% de descuento)")

total_mes = 0.0
valor_regular = 0.0
descuento = 0.0
planes_seleccionados: list[str] = []

if usar_bundle:
    st.success("¡Pack Completo activado! Aplicando 20% de descuento en el total.")
    planes_seleccionados = list(planes_data.keys())
    valor_regular = sum(info["base"] + info["pma"] for info in planes_data.values())
    descuento = valor_regular * 0.20
    total_mes = valor_regular - descuento

    c1, c2, c3 = st.columns(3)
    c1.metric("Valor Regular Sumado", f"${valor_regular:,.0f} COP")
    c2.metric("Descuento aplicado (20%)", f"-${descuento:,.0f} COP")
    c3.metric("Total Mensual Final (Bundle)", f"${total_mes:,.0f} COP")
else:
    st.write("Selecciona los servicios de forma individual:")
    for plan, info in planes_data.items():
        subtotal = info["base"] + info["pma"]
        label = (
            f"{plan} — Web: {info['web']} "
            f"(Base: ${info['base']:,} + PMA: ${info['pma']:,} = ${subtotal:,} COP/mes)"
        )
        if st.checkbox(label, key=f"plan_{plan}"):
            planes_seleccionados.append(plan)
            total_mes += subtotal

    st.markdown("---")
    st.metric("Total Mensual Seleccionado", f"${total_mes:,.0f} COP")

if st.button("💾 Guardar Configuración de Plan en PocketBase", type="primary"):
    if total_mes <= 0:
        st.warning("Selecciona al menos un plan o activa el Pack Completo.")
    else:
        result = save_planes_config(
            {
                "client_id": client_id,
                "usar_bundle": usar_bundle,
                "planes_seleccionados": planes_seleccionados,
                "total_mes": total_mes,
                "valor_regular": valor_regular,
                "descuento": descuento,
                "detalle": {
                    "planes": planes_data,
                    "seleccionados": planes_seleccionados,
                },
            }
        )
        if result.get("ok"):
            st.success(f"¡{result.get('message', 'Guardado')}")
        else:
            st.error(result.get("message", "Error desconocido"))
            st.info("Si la colección no existe: python scripts/setup_planes_config_collection.py")
