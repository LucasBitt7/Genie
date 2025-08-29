# instala Docker/Compose (Ubuntu/Debian),

# cria /opt/genieacs,

# grava docker-compose.yml completo,

# grava backend/genieacs_backend_mvp.py (arquivo completo, v0.6.0),

# grava backend/Dockerfile.backend,

# gera .backend.env com API key,

# faz docker compose build e up.

# Salve como install-genieacs-backend.sh, dê permissão e execute:
# sudo bash install-genieacs-backend.sh
#!/usr/bin/env bash
set -euo pipefail

# ==========================================
# Instala GenieACS + STUN (coTURN) + Backend FastAPI
# ==========================================

# --- Parâmetros ajustáveis ---
INSTALL_DIR="/opt/genieacs"
GENIEACS_IMAGE="drumsergio/genieacs:latest"
MONGO_IMAGE="mongo:6.0"
STUN_IMAGE="coturn/coturn:latest"

# Binds locais (UI/NBI/FS/Backend só via loopback)
UI_BIND="127.0.0.1:3000:3000"
NBI_BIND="127.0.0.1:7557:7557"
FS_BIND="127.0.0.1:7567:7567"
BACKEND_BIND="127.0.0.1:8000:8000"

# Portas públicas (expostas)
CWMP_BIND="7547:7547"          # TCP
STUN_BIND="3478:3478/udp"      # UDP

echo "[1/7] Instalando Docker e Compose (Ubuntu/Debian)..."
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg lsb-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/$(. /etc/os-release; echo "$ID")/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") \
$(. /etc/os-release; echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

echo "[2/7] Criando estrutura em ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}/backend"
cd "${INSTALL_DIR}"

echo "[3/7] Gravando docker-compose.yml..."
cat > docker-compose.yml <<'YAML'
services:
  mongo:
    image: mongo:6.0
    container_name: mongo-genieacs
    restart: always
    volumes:
      - data_db:/data/db
      - data_configdb:/data/configdb
    expose:
      - "27017"
    networks:
      - genieacs_net
    logging:
      driver: "local"
      options:
        max-size: "10m"
        max-file: "5"

  genieacs:
    image: drumsergio/genieacs:latest
    container_name: genieacs
    restart: always
    depends_on:
      - mongo
    env_file:
      - .env
    environment:
      GENIEACS_MONGODB_CONNECTION_URL: mongodb://mongo/genieacs?authSource=admin
      DEBUG: "genieacs:*"
      # Porta de ORIGEM usada pelo ACS para UDP Connection Request (casar com o STUN)
      GENIEACS_UDP_CONNECTION_REQUEST_PORT: "3478"
      # redundante/compatibilidade
      GENIEACS_CWMP_UDP_CONNECTION_REQUEST_PORT: "3478"
    ports:
      - "7547:7547"            # CWMP/TR-069 público
      - "127.0.0.1:3000:3000"  # UI (loopback)
      - "127.0.0.1:7557:7557"  # NBI (loopback)
      - "127.0.0.1:7567:7567"  # File Server (loopback)
      - "3478:3478/udp"        # STUN/ConnReq (publish pelo genieacs)
    networks:
      - genieacs_net
    logging:
      driver: "local"
      options:
        max-size: "10m"
        max-file: "5"

  # STUN sidecar no MESMO namespace de rede do 'genieacs'
  stun:
    image: coturn/coturn:latest
    container_name: stun-server
    network_mode: "container:genieacs"
    restart: always
    command: >
      turnserver -n
        --stun-only
        --no-auth
        --no-tls --no-dtls --no-tcp
        --listening-ip=0.0.0.0
        --listening-port=3478
        --verbose
    logging:
      driver: "local"
      options:
        max-size: "10m"
        max-file: "5"

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile.backend
    container_name: genieacs-backend
    restart: always
    env_file:
      - ./.backend.env
    environment:
      GENIEACS_NBI_URL: http://genieacs:7557
    depends_on:
      - genieacs
    networks:
      - genieacs_net
    ports:
      - "127.0.0.1:8000:8000"

volumes:
  data_db: {}
  data_configdb: {}

networks:
  genieacs_net:
    driver: bridge
YAML

echo "[4/7] Gravando backend (código completo + Dockerfile)..."
cat > backend/genieacs_backend_mvp.py <<'PY'
# -*- coding: utf-8 -*-
"""
GenieACS MVP Backend (v0.6.0)

- CORS + OPTIONS explícito (preflight OK).
- Endpoints de negócio (wifi/pppoe/reboot/factory_reset/parameters/connreq).
- Métricas (/metrics/*) com datas ISO.
- SSE (/metrics/stream) para overview em tempo real.
- /devices/list com paginação/filtros/sort (JSON válido ex: {"_lastInform": -1}).
- extract_value_from_path SEMPRE devolve ESCALAR (nunca dict/list).
- Compatível com TR-098 e TR-181 (fallback automático para Wi-Fi).
"""

from typing import List, Optional, Any, Dict, Iterable, Union
import os
import json
import asyncio
import httpx
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Security, status, Request, Query
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# ---------------------------------------------------------------------------
# Config

NBI_URL: str = os.getenv("GENIEACS_NBI_URL", "http://localhost:7557")


def _read_file_if_exists(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def load_api_key() -> str:
    # prioridade: ACS_API_KEY / ACS_API_KEY_FILE; depois GENIEACS_API_KEY / GENIEACS_API_KEY_FILE
    for env_key, env_file in (
        ("ACS_API_KEY", "ACS_API_KEY_FILE"),
        ("GENIEACS_API_KEY", "GENIEACS_API_KEY_FILE"),
    ):
        val = os.getenv(env_key)
        if val:
            return val
        p = os.getenv(env_file)
        if p:
            f = _read_file_if_exists(p)
            if f:
                return f
    raise RuntimeError("Missing API Key. Set ACS_API_KEY or ACS_API_KEY_FILE.")


API_KEY: str = load_api_key()
API_KEY_NAME: str = "X-API-Key"
api_key_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

DEFAULT_FRONT_ORIGINS = ["http://localhost:1234", "http://127.0.0.1:1234"]
_env = os.getenv("FRONTEND_ORIGINS")
ALLOWED_ORIGINS = [o.strip() for o in _env.split(",")] if _env else DEFAULT_FRONT_ORIGINS


def get_api_key(request: Request, api_key_header: Optional[str] = Security(api_key_scheme)) -> str:
    if request.method == "OPTIONS":
        return ""
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing API Key")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Modelos


class WifiCredentials(BaseModel):
    ssid: str
    password: str


class PPPoECredentials(BaseModel):
    username: str
    password: str


class ParameterRequest(BaseModel):
    parameter_names: List[str]


# ---------------------------------------------------------------------------
# App + CORS

app = FastAPI(
    title="GenieACS MVP Backend",
    description="API mínima para encapsular tarefas do NBI do GenieACS.",
    version="0.6.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# ---------------------------------------------------------------------------
# HTTP client (reutilizado)

_client: Optional[httpx.AsyncClient] = None


@app.on_event("startup")
async def _startup():
    global _client
    _client = httpx.AsyncClient(base_url=NBI_URL, timeout=httpx.Timeout(30.0, read=30.0))


@app.on_event("shutdown")
async def _shutdown():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _cli() -> httpx.AsyncClient:
    assert _client is not None, "HTTP client not initialized"
    return _client


# ---------------------------------------------------------------------------
# Helpers NBI


async def send_task(device_id: str, task_body: dict, connection_request: bool = False, timeout: Optional[int] = None) -> dict:
    params: Dict[str, str] = {}
    if connection_request:
        params["connection_request"] = ""
        if timeout and timeout > 0:
            params["timeout"] = str(timeout)
    try:
        resp = await _cli().post(f"/devices/{device_id}/tasks", params=params, json=task_body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"POST /devices/{device_id}/tasks failed: {exc}") from exc
    if resp.status_code not in (200, 202):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def fetch_device_doc(device_id: str) -> Dict[str, Any]:
    params = {"query": json.dumps({"_id": device_id})}
    try:
        resp = await _cli().get("/devices", params=params)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"GET /devices failed: {exc}") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    arr = resp.json() or []
    if not arr:
        raise HTTPException(status_code=404, detail="Device not found")
    return arr[0]


def _normalize_sort(sort: Union[str, Dict[str, int], None]) -> Optional[str]:
    if sort is None:
        return None
    if isinstance(sort, dict):
        return json.dumps(sort)
    if isinstance(sort, str):
        if ":" in sort:
            field, direction = sort.split(":", 1)
            try:
                dirn = int(direction)
                if dirn not in (1, -1):
                    dirn = -1
            except Exception:
                dirn = -1
            return json.dumps({field: dirn})
        return json.dumps({sort: -1})
    return None


async def nbi_get_devices(
    query: dict,
    projection: Iterable[str] = (),
    limit: int = 1000,
    skip: int = 0,
    sort: Union[str, Dict[str, int], None] = None,
) -> List[dict]:
    params: Dict[str, str] = {"query": json.dumps(query), "limit": str(limit), "skip": str(skip)}
    if projection:
        params["projection"] = ",".join(projection)
    s = _normalize_sort(sort)
    if s:
        params["sort"] = s
    resp = await _cli().get("/devices", params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json() or []


async def nbi_count(query: dict) -> int:
    params = {"query": json.dumps(query), "projection": "_id"}
    resp = await _cli().get("/devices", params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    total = resp.headers.get("X-Total-Count") or resp.headers.get("x-total-count")
    if total:
        try:
            return int(total)
        except Exception:
            pass
    # fallback (contagem por array)
    params["limit"] = "10000"
    resp = await _cli().get("/devices", params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return len(resp.json() or [])


def extract_value_from_path(doc: Dict[str, Any], dotted_path: str) -> Any:
    cur: Any = doc
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    if isinstance(cur, dict) and "_value" in cur:
        val = cur["_value"]
        if isinstance(val, (str, int, float, bool)) or val is None:
            return val
        return None
    if isinstance(cur, (dict, list)):
        return None
    return cur


def _has_value(doc: Dict[str, Any], path: str) -> bool:
    return extract_value_from_path(doc, path) is not None


def resolve_wifi_params(doc: Dict[str, Any], wlan_index: int) -> Dict[str, str]:
    """
    Tenta TR-181 primeiro; se não existir, cai para TR-098.
    Retorna caminhos de parâmetros SSID e senha.
    """
    # TR-181
    ssid_181 = f"Device.WiFi.SSID.{wlan_index}.SSID"
    pass_181_a = f"Device.WiFi.AccessPoint.{wlan_index}.Security.KeyPassphrase"
    pass_181_b = f"Device.WiFi.AccessPoint.{wlan_index}.Security.PreSharedKey"  # fallback

    if _has_value(doc, ssid_181) or "Device.WiFi" in str(doc):
        pwd = pass_181_a if _has_value(doc, pass_181_a) else pass_181_b
        return {"parameter_ssid": ssid_181, "parameter_password": pwd}

    # TR-098
    base = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{wlan_index}"
    ssid_098 = f"{base}.SSID"
    kp_098 = f"{base}.PreSharedKey.1.KeyPassphrase"
    ps_098 = f"{base}.PreSharedKey.1.PreSharedKey"
    pwd_098 = kp_098 if _has_value(doc, kp_098) else ps_098
    return {"parameter_ssid": ssid_098, "parameter_password": pwd_098}


# ---------------------------------------------------------------------------
# Health & OPTIONS (CORS)


@app.get("/health")
def health():
    return {"ok": True, "nbi": NBI_URL}


@app.options("/devices/{device_id:path}/wifi")
def _opt_wifi(device_id: str):
    return Response(status_code=200)


@app.options("/devices/{device_id:path}/pppoe")
def _opt_pppoe(device_id: str):
    return Response(status_code=200)


@app.options("/devices/{device_id:path}/reboot")
def _opt_reboot(device_id: str):
    return Response(status_code=200)


@app.options("/devices/{device_id:path}/factory_reset")
def _opt_factory(device_id: str):
    return Response(status_code=200)


@app.options("/devices/{device_id:path}/parameters")
def _opt_params(device_id: str):
    return Response(status_code=200)


@app.options("/{full_path:path}")
def _opt_catch_all(full_path: str):
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Business


class WifiAndRebootReq(WifiCredentials):
    pass


@app.post("/devices/{device_id:path}/wifi")
async def change_wifi(
    device_id: str,
    credentials: WifiCredentials,
    wlan_index: int = 1,
    parameter_ssid: Optional[str] = None,
    parameter_password: Optional[str] = None,
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    doc = await fetch_device_doc(device_id)
    if not (parameter_ssid and parameter_password):
        res = resolve_wifi_params(doc, wlan_index)
        parameter_ssid = parameter_ssid or res["parameter_ssid"]
        parameter_password = parameter_password or res["parameter_password"]
    task_body = {
        "name": "setParameterValues",
        "parameterValues": [
            [parameter_ssid, credentials.ssid, "xsd:string"],
            [parameter_password, credentials.password, "xsd:string"],
        ],
    }
    return await send_task(device_id, task_body, connection_request, timeout=cr_timeout)


@app.post("/devices/{device_id:path}/pppoe")
async def change_pppoe(
    device_id: str,
    credentials: PPPoECredentials,
    enable: Optional[bool] = True,
    parameter_username: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username",
    parameter_password: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Password",
    parameter_enable: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Enable",
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    pvals = [
        [parameter_username, credentials.username, "xsd:string"],
        [parameter_password, credentials.password, "xsd:string"],
    ]
    if enable is not None:
        pvals.append([parameter_enable, enable, "xsd:boolean"])
    task_body = {"name": "setParameterValues", "parameterValues": pvals}
    return await send_task(device_id, task_body, connection_request, timeout=cr_timeout)


@app.post("/devices/{device_id:path}/reboot")
async def reboot_device(
    device_id: str,
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    return await send_task(device_id, {"name": "reboot"}, connection_request, timeout=cr_timeout)


@app.post("/devices/{device_id:path}/factory_reset")
async def factory_reset(
    device_id: str,
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    return await send_task(device_id, {"name": "factoryReset"}, connection_request, timeout=cr_timeout)


@app.post("/devices/{device_id:path}/parameters")
async def get_parameters(
    device_id: str,
    request: ParameterRequest,
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    task_body = {"name": "getParameterValues", "parameterNames": request.parameter_names}
    return await send_task(device_id, task_body, connection_request, timeout=cr_timeout)


@app.post("/devices/{device_id:path}/wifi_and_reboot")
async def wifi_and_reboot(
    device_id: str,
    credentials: WifiAndRebootReq,
    wlan_index: int = 1,
    parameter_ssid: Optional[str] = None,
    parameter_password: Optional[str] = None,
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    doc = await fetch_device_doc(device_id)
    if not (parameter_ssid and parameter_password):
        res = resolve_wifi_params(doc, wlan_index)
        parameter_ssid = parameter_ssid or res["parameter_ssid"]
        parameter_password = parameter_password or res["parameter_password"]
    task_wifi = {
        "name": "setParameterValues",
        "parameterValues": [
            [parameter_ssid, credentials.ssid, "xsd:string"],
            [parameter_password, credentials.password, "xsd:string"],
        ],
    }
    wifi_task = await send_task(device_id, task_wifi, connection_request, timeout=cr_timeout)
    reboot_task = await send_task(device_id, {"name": "reboot"}, connection_request=False)
    return {"wifi_task": wifi_task, "reboot_task": reboot_task, "note": "Wi-Fi aplicado e reboot agendado."}


# extra: “summon” via API (connreq + noop leve)
@app.post("/devices/{device_id:path}/connreq")
async def connreq(
    device_id: str,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    body = {"name": "getParameterValues", "parameterNames": ["Device.DeviceInfo.SoftwareVersion"]}
    return await send_task(device_id, body, connection_request=True, timeout=cr_timeout)


# ---------------------------------------------------------------------------
# Leitura unitária


@app.get("/devices/{device_id:path}/ssid")
async def read_ssid(
    device_id: str,
    wlan_index: int = 1,
    _: str = Depends(get_api_key),
) -> dict:
    ssid_181 = f"Device.WiFi.SSID.{wlan_index}.SSID"
    ssid_098 = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{wlan_index}.SSID"
    doc = await fetch_device_doc(device_id)
    value = extract_value_from_path(doc, ssid_181) or extract_value_from_path(doc, ssid_098)
    return {"device": device_id, "parameter": ssid_181 if value else ssid_098, "value": value}


@app.get("/devices/{device_id:path}/read_value")
async def read_value(
    device_id: str,
    name: str = Query(..., description="Path TR-069 completo"),
    _: str = Depends(get_api_key),
) -> dict:
    doc = await fetch_device_doc(device_id)
    value = extract_value_from_path(doc, name)
    return {"device": device_id, "parameter": name, "value": value}


# ---------------------------------------------------------------------------
# Métricas (datas ISO)


async def _compute_overview(window_online_sec: int, window_24h_sec: int) -> dict:
    now = datetime.utcnow()
    t_online = _iso(now - timedelta(seconds=window_online_sec))
    t_24h = _iso(now - timedelta(seconds=window_24h_sec))
    total_devices = await nbi_count({})
    online_now = await nbi_count({"_lastInform": {"$gte": t_online}})
    active_24h = await nbi_count({"_lastInform": {"$gte": t_24h}})
    offline_24h = max(total_devices - active_24h, 0)
    return {
        "generated_at": _iso(now),
        "total_devices": total_devices,
        "online_now": online_now,
        "active_24h": active_24h,
        "offline_24h": offline_24h,
        "windows": {"online_sec": window_online_sec, "active_24h_sec": window_24h_sec},
    }


@app.get("/metrics/overview")
async def metrics_overview(
    window_online_sec: int = 600,
    window_24h_sec: int = 86400,
    _: str = Depends(get_api_key),
) -> dict:
    return await _compute_overview(window_online_sec, window_24h_sec)


@app.get("/metrics/distribution")
async def metrics_distribution(
    sample_limit: int = 2000,
    _: str = Depends(get_api_key),
) -> dict:
    proj = [
        "InternetGatewayDevice.DeviceInfo.ProductClass",
        "InternetGatewayDevice.DeviceInfo.SoftwareVersion",
        "Device.WiFi.SSID.1.SSID",
    ]
    docs = await nbi_get_devices({}, projection=proj, limit=sample_limit, skip=0)

    def _val(doc, path: str):
        return extract_value_from_path(doc, path)

    pc: Dict[str, int] = {}
    sv: Dict[str, int] = {}
    for d in docs:
        pcv = _val(d, "InternetGatewayDevice.DeviceInfo.ProductClass") or "UNKNOWN"
        svv = _val(d, "InternetGatewayDevice.DeviceInfo.SoftwareVersion") \
              or _val(d, "Device.DeviceInfo.SoftwareVersion") or "UNKNOWN"
        pc[pcv] = pc.get(pcv, 0) + 1
        sv[svv] = sv.get(svv, 0) + 1
    return {"product_class": pc, "software_version": sv, "sampled": len(docs)}


@app.get("/metrics/last-informs")
async def metrics_last_informs(
    n: int = 50,
    _: str = Depends(get_api_key),
) -> List[dict]:
    proj = [
        "_id",
        "_lastInform",
        "InternetGatewayDevice.DeviceInfo.ProductClass",
        "InternetGatewayDevice.DeviceInfo.SoftwareVersion",
        "Device.DeviceInfo.SoftwareVersion",
    ]
    docs = await nbi_get_devices({}, projection=proj, limit=n, skip=0, sort={"_lastInform": -1})

    def _val(doc, path: str):
        return extract_value_from_path(doc, path)

    out: List[dict] = []
    for d in docs:
        out.append({
            "device_id": d.get("_id"),
            "last_inform": d.get("_lastInform"),
            "product_class": _val(d, "InternetGatewayDevice.DeviceInfo.ProductClass"),
            "software_version": _val(d, "InternetGatewayDevice.DeviceInfo.SoftwareVersion")
                                  or _val(d, "Device.DeviceInfo.SoftwareVersion"),
        })
    return out


# ---------------------------------------------------------------------------
# SSE (overview ao vivo)


@app.get("/metrics/stream")
async def metrics_stream(
    request: Request,
    token: str,
    interval: int = 5,
    window_online_sec: int = 600,
    window_24h_sec: int = 86400,
):
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    async def event_gen():
        yield {"event": "overview", "data": json.dumps(await _compute_overview(window_online_sec, window_24h_sec))}
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(max(1, int(interval)))
            payload = await _compute_overview(window_online_sec, window_24h_sec)
            yield {"event": "overview", "data": json.dumps(payload)}
    return EventSourceResponse(event_gen(), ping=15)


# ---------------------------------------------------------------------------
# Lista de devices


@app.get("/devices/list")
async def devices_list(
    page: int = 1,
    page_size: int = 25,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    product_class: Optional[str] = None,
    online_within_sec: int = 600,
    only_online: bool = False,
    sort_by: str = "_lastInform",
    order: str = "desc",
    _: str = Depends(get_api_key),
) -> dict:
    now = datetime.utcnow()
    online_cut = _iso(now - timedelta(seconds=online_within_sec))

    q: Dict[str, Any] = {}
    if search:
        q["_id"] = {"$regex": search, "$options": "i"}
    if tag:
        q["_tags"] = tag
    if product_class:
        q["InternetGatewayDevice.DeviceInfo.ProductClass._value"] = product_class
    if only_online:
        q["_lastInform"] = {"$gte": online_cut}

    total = await nbi_count(q)

    limit = max(1, min(500, page_size))
    skip = max(0, (max(1, page) - 1) * limit)
    sort_dict = {sort_by: -1 if order.lower() == "desc" else 1}

    proj = [
        "_id",
        "_lastInform",
        "InternetGatewayDevice.DeviceInfo.ProductClass",
        "InternetGatewayDevice.DeviceInfo.SoftwareVersion",
        "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID",
        "Device.WiFi.SSID.1.SSID",
    ]
    docs = await nbi_get_devices(q, projection=proj, limit=limit, skip=skip, sort=sort_dict)

    def _val(doc, path: str):
        return extract_value_from_path(doc, path)

    items = []
    for d in docs:
        li = d.get("_lastInform")
        is_online = bool(li and li >= online_cut)
        ssid = _val(d, "Device.WiFi.SSID.1.SSID") or _val(d, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID")
        items.append({
            "device_id": d.get("_id"),
            "last_inform": li,
            "online": is_online,
            "product_class": _val(d, "InternetGatewayDevice.DeviceInfo.ProductClass"),
            "software_version": _val(d, "InternetGatewayDevice.DeviceInfo.SoftwareVersion")
                                or _val(d, "Device.DeviceInfo.SoftwareVersion"),
            "ssid": ssid,
        })

    total_pages = (total + limit - 1) // limit
    return {
        "generated_at": _iso(now),
        "page": page,
        "page_size": limit,
        "total": total,
        "total_pages": total_pages,
        "items": items,
        "online_cut": online_cut,
    }
PY

cat > backend/Dockerfile.backend <<'DOCK'
FROM python:3.11-slim
WORKDIR /app
COPY backend/genieacs_backend_mvp.py .
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx sse-starlette
ENV GENIEACS_NBI_URL=http://genieacs:7557
CMD ["uvicorn", "genieacs_backend_mvp:app", "--host", "0.0.0.0", "--port", "8000"]
DOCK

echo "[5/7] Criando .env do GenieACS (opcional)..."
if [ ! -f .env ]; then
  cat > .env <<'ENV'
# Variáveis extras do GenieACS (opcional)
ENV
fi

echo "[6/7] Gerando API key do backend (.backend.env)..."
if [ ! -f .backend.env ]; then
  KEY=$(openssl rand -hex 24)
  echo "ACS_API_KEY=${KEY}" > .backend.env
  echo "FRONTEND_ORIGINS=http://localhost:1234,http://127.0.0.1:1234" >> .backend.env
  echo "API key gerada: ${KEY}"
else
  echo ".backend.env já existe; mantendo."
fi

echo "[7/7] Build e UP..."
docker compose build backend
docker compose up -d --remove-orphans

echo "----------------------------------------------------"
echo "GenieACS UI      : http://127.0.0.1:3000 (via túnel SSH)"
echo "GenieACS NBI     : http://127.0.0.1:7557 (loopback)"
echo "Backend FastAPI  : http://127.0.0.1:8000 (loopback)"
echo "CWMP público     : porta 7547/TCP"
echo "STUN/ConnReq     : porta 3478/UDP"
echo
echo "Dica de túnel SSH a partir da sua máquina local:"
echo "ssh -N -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 user@SEU_IP_VPS"
echo
echo "Após subir:"
echo "  - GenieACS → Admin → Config: crie 'cwmp.udpConnectionRequestPort' = 3478"
echo "  - EX141: habilite STUN → servidor=IP_DA_VPS, porta=3478"
echo "  - Teste backend: curl -s http://127.0.0.1:8000/health"
echo "----------------------------------------------------"
