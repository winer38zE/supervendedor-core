import os
import json
import importlib.util
from pathlib import Path
from dotenv import load_dotenv
import httpx

PATH = Path(__file__).resolve().parents[1]
load_dotenv(PATH / ".env")

spec = importlib.util.spec_from_file_location(
    "scc", str(PATH / "scripts/setup_clients_config_collection.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")
token = mod._authenticate(base)
print("Auth OK")
headers = {"Authorization": token}

tr = httpx.get(
    f"{base}/api/collections/tenants/records",
    params={"perPage": 5, "sort": "-created"},
    headers=headers,
    timeout=30,
)
print("Tenants status", tr.status_code)
items = tr.json().get("items", []) if tr.status_code == 200 else []
if tr.status_code == 200:
    print(
        json.dumps(
            [{k: r.get(k) for k in ("id", "name", "slug") if k in r} for r in items],
            indent=2,
        )
    )
else:
    print(tr.text[:1000])

tenant_ref = os.getenv("CHAT_TENANT_ID", "edwuar").strip()
client_id = tenant_ref
for rec in items:
    if (
        str(rec.get("id", "")) == tenant_ref
        or str(rec.get("slug", "")) == tenant_ref
        or str(rec.get("name", "")) == tenant_ref
    ):
        client_id = rec.get("id", tenant_ref)
        print("Matched tenant record id for CHAT_TENANT_ID:", client_id)
        break
else:
    print("Using client_id = CHAT_TENANT_ID value:", client_id)

payload = {
    "client_id": client_id,
    "niche": "moda femenina accesible",
    "brand_voice": "cercana, entusiasta, sin tecnicismos",
    "product_focus": "vestidos y tops tendencia",
    "catalog_query": "vestido verano",
    "content_platform": "instagram",
    "content_caption": "Ejemplo: Nuevo drop de verano. Escribenos por DM.",
    "content_enabled": True,
    "content_webhook_url": "",
    "launch_ads": False,
    "auto_producto": True,
    "use_trends": True,
    "single_pass": False,
    "skip_meta_create": True,
    "llm_preference": "openai",
    "remix_level": 0.35,
    "default_views": 1200,
    "default_likes": 85,
    "default_comments": 12,
    "default_shares": 5,
    "last_caption": "Caption de ejemplo generada por setup",
    "last_metrics": {"views": 1200, "likes": 85, "comments": 12, "shares": 5},
}

flt = httpx.get(
    f"{base}/api/collections/clients_config/records",
    params={"filter": f"client_id={client_id!r}", "perPage": 1},
    headers=headers,
    timeout=30,
)
print("Lookup clients_config status", flt.status_code)
rec_id = None
if flt.status_code == 200 and flt.json().get("items"):
    rec_id = flt.json()["items"][0]["id"]
    print("Existing record id:", rec_id)

if rec_id:
    resp = httpx.patch(
        f"{base}/api/collections/clients_config/records/{rec_id}",
        json=payload,
        headers=headers,
        timeout=30,
    )
    print("Update status", resp.status_code)
else:
    resp = httpx.post(
        f"{base}/api/collections/clients_config/records",
        json=payload,
        headers=headers,
        timeout=30,
    )
    print("Create status", resp.status_code)

print(
    json.dumps(
        resp.json() if resp.status_code in (200, 201) else {"error": resp.text[:800]},
        indent=2,
        ensure_ascii=False,
    )
)
