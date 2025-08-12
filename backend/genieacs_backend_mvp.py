# -*- coding: utf-8 -*-
"""
GenieACS MVP Backend (v0.5.2)

- CORS + OPTIONS explícito (preflight OK).
- Endpoints de negócio (wifi/pppoe/reboot/factory_reset/parameters).
- Métricas (/metrics/*) com datas ISO.
- SSE (/metrics/stream) para overview em tempo real.
- /devices/list com paginação/filtros/sort.
- sort do NBI enviado em JSON válido (ex.: {"_lastInform": -1}).
- extract_value_from_path SEMPRE devolve ESCALAR (nunca dict/list) → evita quebra no frontend.
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
    key = os.getenv("ACS_API_KEY")
    if key:
        return key
    path = os.getenv("ACS_API_KEY_FILE")
    if path:
        val = _read_file_if_exists(path)
        if val:
            return val
    key = os.getenv("GENIEACS_API_KEY")
    if key:
        return key
    path = os.getenv("GENIEACS_API_KEY_FILE")
    if path:
        val = _read_file_if_exists(path)
        if val:
            return val
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
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

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
    version="0.5.2",
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
# Helpers NBI

async def send_task(device_id: str, task_body: dict, connection_request: bool = False, timeout: Optional[int] = None) -> dict:
    url = f"{NBI_URL}/devices/{device_id}/tasks"
    params: Dict[str, str] = {}
    if connection_request:
        params["connection_request"] = ""
        if timeout and timeout > 0:
            params["timeout"] = str(timeout)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, params=params, json=task_body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if resp.status_code not in (200, 202):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()

async def fetch_device_doc(device_id: str) -> Dict[str, Any]:
    url = f"{NBI_URL}/devices"
    params = {"query": json.dumps({"_id": device_id})}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    arr = resp.json() or []
    if not arr:
        raise HTTPException(status_code=404, detail="Device not found")
    return arr[0]

def _normalize_sort(sort: Union[str, Dict[str, int], None]) -> Optional[str]:
    """
    Converte sort em JSON aceito pelo NBI.
    - "_lastInform:-1" → {"_lastInform": -1}
    - dict → json.dumps(dict)
    """
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
    params: Dict[str, str] = {
        "query": json.dumps(query),
        "limit": str(limit),
        "skip": str(skip),
    }
    if projection:
        params["projection"] = ",".join(projection)
    s = _normalize_sort(sort)
    if s:
        params["sort"] = s
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(f"{NBI_URL}/devices", params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json() or []

async def nbi_count(query: dict) -> int:
    params = {"query": json.dumps(query), "projection": "_id"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{NBI_URL}/devices", params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    total = r.headers.get("X-Total-Count") or r.headers.get("x-total-count")
    if total:
        try:
            return int(total)
        except Exception:
            pass
    params["limit"] = "10000"
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(f"{NBI_URL}/devices", params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    arr = r.json() or []
    return len(arr)

def extract_value_from_path(doc: Dict[str, Any], dotted_path: str) -> Any:
    """
    Caminha pelo documento.
    - Se chegar a um dict com "_value": retorna esse valor **se for escalar**.
    - Se o nó final for container (dict/list) ou "_value" não for escalar: retorna None.
    - Nunca retorna dict/list para o frontend.
    """
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

def resolve_wifi_params(doc: Dict[str, Any], wlan_index: int) -> Dict[str, str]:
    base = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{wlan_index}"
    ssid = f"{base}.SSID"
    kp = f"{base}.PreSharedKey.1.KeyPassphrase"
    ps = f"{base}.PreSharedKey.1.PreSharedKey"
    has_kp = extract_value_from_path(doc, kp) is not None or (kp in str(doc))
    has_ps = extract_value_from_path(doc, ps) is not None or (ps in str(doc))
    pwd = kp if has_kp else ps if has_ps else kp
    return {"parameter_ssid": ssid, "parameter_password": pwd}

# ---------------------------------------------------------------------------
# OPTIONS (CORS)

@app.options("/devices/{device_id:path}/wifi")
def _opt_wifi(device_id: str): return Response(status_code=200)

@app.options("/devices/{device_id:path}/pppoe")
def _opt_pppoe(device_id: str): return Response(status_code=200)

@app.options("/devices/{device_id:path}/reboot")
def _opt_reboot(device_id: str): return Response(status_code=200)

@app.options("/devices/{device_id:path}/factory_reset")
def _opt_factory(device_id: str): return Response(status_code=200)

@app.options("/devices/{device_id:path}/parameters")
def _opt_params(device_id: str): return Response(status_code=200)

@app.options("/{full_path:path}")
def _opt_catch_all(full_path: str): return Response(status_code=200)

# ---------------------------------------------------------------------------
# Business

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
    task_body = {"name": "reboot"}
    return await send_task(device_id, task_body, connection_request, timeout=cr_timeout)

@app.post("/devices/{device_id:path}/factory_reset")
async def factory_reset(
    device_id: str,
    connection_request: bool = True,
    cr_timeout: int = 10,
    _: str = Depends(get_api_key),
) -> dict:
    task_body = {"name": "factoryReset"}
    return await send_task(device_id, task_body, connection_request, timeout=cr_timeout)

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

# ---------------------------------------------------------------------------
# Leitura unitária

@app.get("/devices/{device_id:path}/ssid")
async def read_ssid(
    device_id: str,
    wlan_index: int = 1,
    _: str = Depends(get_api_key),
) -> dict:
    ssid_path = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{wlan_index}.SSID"
    doc = await fetch_device_doc(device_id)
    value = extract_value_from_path(doc, ssid_path)
    return {"device": device_id, "parameter": ssid_path, "value": value}

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
    ]
    docs = await nbi_get_devices({}, projection=proj, limit=sample_limit, skip=0)

    def _val(doc, path: str):
        return extract_value_from_path(doc, path)

    pc: Dict[str, int] = {}
    sv: Dict[str, int] = {}
    for d in docs:
        pcv = _val(d, "InternetGatewayDevice.DeviceInfo.ProductClass") or "UNKNOWN"
        svv = _val(d, "InternetGatewayDevice.DeviceInfo.SoftwareVersion") or "UNKNOWN"
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
            "software_version": _val(d, "InternetGatewayDevice.DeviceInfo.SoftwareVersion"),
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
    ]
    docs = await nbi_get_devices(q, projection=proj, limit=limit, skip=skip, sort=sort_dict)

    def _val(doc, path: str):
        return extract_value_from_path(doc, path)

    items = []
    for d in docs:
        li = d.get("_lastInform")
        is_online = bool(li and li >= online_cut)  # ISO string
        items.append({
            "device_id": d.get("_id"),
            "last_inform": li,
            "online": is_online,
            "product_class": _val(d, "InternetGatewayDevice.DeviceInfo.ProductClass"),
            "software_version": _val(d, "InternetGatewayDevice.DeviceInfo.SoftwareVersion"),
            "ssid": _val(d, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID"),
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
