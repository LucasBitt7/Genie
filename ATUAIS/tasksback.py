# -*- coding: utf-8 -*-
"""
GenieACS MVP Backend (v0.8.0)

Segurança:
- API Key via "X-API-Key" OU "Authorization: Bearer <token>".
- CORS configurável, NBI atrás de rede Docker.
- Timeouts, respostas enxutas e sem dados sensíveis por acidente.

Funcional (compatível com EX141, TR-098; tenta TR-181 quando disponível):
- /devices/list  → lista enriquecida (modelo, firmware, IP "melhor esforço", SSID, tags, online).
- /devices/detail/{id} → visão normalizada por CPE (vendor, modelo, firmware, IP WAN/LAN, SSID 2G/5G, STUN, PIN, etc.).
- /devices/{id}/(wifi|pppoe|reboot|factory_reset|parameters|connreq|ssid|read_value)  → iguais ao v0.6.
- /metrics/(overview|last-informs|distribution|stream) → iguais ao v0.6, com pequenas melhorias.
"""

from typing import List, Optional, Any, Dict, Iterable, Union, Tuple
import os, json, asyncio, httpx, re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Security, status, Request, Query, Header
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

def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

# ---------------------------------------------------------------------------
# App + CORS

app = FastAPI(
    title="GenieACS MVP Backend",
    description="API mínima e robusta para encapsular tarefas do NBI do GenieACS.",
    version="0.8.0",
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
# Auth (aceita X-API-Key OU Authorization: Bearer)

def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    m = re.match(r"^\s*Bearer\s+(.+)\s*$", auth_header, re.I)
    return m.group(1) if m else None

def get_api_key(
    request: Request,
    api_key_header: Optional[str] = Security(api_key_scheme),
    authorization: Optional[str] = Header(default=None),
) -> str:
    if request.method == "OPTIONS":
        return ""
    tok = api_key_header or _extract_bearer(authorization)
    if tok == API_KEY:
        return tok or ""
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing API Key")

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

def _get_node(doc: Dict[str, Any], dotted_path: str) -> Optional[dict]:
    cur: Any = doc
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur if isinstance(cur, dict) else None

def _iter_idx(node: Optional[dict]) -> List[str]:
    if not isinstance(node, dict):
        return []
    return [k for k in node.keys() if k.isdigit()]

def _has_value(doc: Dict[str, Any], path: str) -> bool:
    return extract_value_from_path(doc, path) is not None

# ---------------------------------------------------------------------------
# TR-181 helpers (band mapping) + TR-098 fallbacks

def map_tr181_by_band(doc: Dict[str, Any]) -> Dict[str, Tuple[str, str, str]]:
    """
    Retorna {"2.4GHz": (ssid_i, ap_k, radio_j), "5GHz": (...)} quando possível.
    """
    m: Dict[str, Tuple[str, str, str]] = {}
    wifi = _get_node(doc, "Device.WiFi")
    if not wifi:
        return m
    radios = _get_node(wifi, "Radio")
    ssids = _get_node(wifi, "SSID")
    aps = _get_node(wifi, "AccessPoint")
    if not (radios and ssids and aps):
        return m

    radio_band: Dict[str, str] = {}
    for r in _iter_idx(radios):
        band = extract_value_from_path(doc, f"Device.WiFi.Radio.{r}.OperatingFrequencyBand")
        if isinstance(band, str):
            radio_band[r] = band

    ssid_radio: Dict[str, str] = {}
    for i in _iter_idx(ssids):
        ll = extract_value_from_path(doc, f"Device.WiFi.SSID.{i}.LowerLayers")
        if isinstance(ll, str):
            m2 = re.search(r"Device\.WiFi\.Radio\.(\d+)", ll)
            if m2:
                ssid_radio[i] = m2.group(1)

    ap_ssid: Dict[str, str] = {}
    for k in _iter_idx(aps):
        ref = extract_value_from_path(doc, f"Device.WiFi.AccessPoint.{k}.SSIDReference")
        if isinstance(ref, str):
            m3 = re.search(r"Device\.WiFi\.SSID\.(\d+)", ref)
            if m3:
                ap_ssid[k] = m3.group(1)

    for ap_k, ssid_i in ap_ssid.items():
        r = ssid_radio.get(ssid_i)
        b = radio_band.get(r or "")
        if b in ("2.4GHz", "5GHz"):
            m[b] = (ssid_i, ap_k, r or "")
    return m

# ====== ALTERADO: detecção TR-098 esperta p/ 2.4G/5G (índices corretos) ======
def resolve_wifi_params_tr098(doc: Dict[str, Any], band: str) -> Tuple[str, str]:
    """
    Resolve SSID/Password TR-098 escolhendo o índice certo.
    No EX141 (TP-Link), 2.4G costuma ser ".1" e 5G ".3".
    Heurística:
      1) Procura X_TP_Band compatível com a banda (quando existir)
      2) Procura Standard (11b/g/n ≈ 2.4G; 11a/ac/ax ≈ 5G)
      3) Fallback: 1 para 2.4G; 3 para 5G se existir, senão 2
    """
    wl = _get_node(doc, "InternetGatewayDevice.LANDevice.1.WLANConfiguration")
    idxs = _iter_idx(wl)
    target_idx: Optional[str] = None

    # 1) X_TP_Band
    for i in idxs:
        b = extract_value_from_path(doc, f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{i}.X_TP_Band")
        if not isinstance(b, str):
            continue
        bl = b.lower()
        if band == "2.4GHz" and ("2.4" in bl or "24" in bl):
            target_idx = i; break
        if band == "5GHz" and ("5g" in bl or bl.strip() == "5" or " 5" in bl):
            target_idx = i; break

    # 2) Standard
    if not target_idx:
        for i in idxs:
            std = extract_value_from_path(doc, f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{i}.Standard")
            if not isinstance(std, str):
                continue
            s = std.lower()
            if band == "2.4GHz" and re.search(r"\b11(b|g|n)\b", s):
                target_idx = i; break
            if band == "5GHz" and re.search(r"\b11(a|ac|ax)\b", s):
                target_idx = i; break

    # 3) Defaults seguros
    if not target_idx:
        if band == "2.4GHz":
            target_idx = "1"
        else:
            # Preferir 3 se existir, senão 2
            target_idx = "3" if _has_value(doc, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.3.SSID") else "2"

    base = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{target_idx}"
    ssid = f"{base}.SSID"
    # Password: preferir KeyPassphrase; se não existir, usar PreSharedKey
    kp = f"{base}.PreSharedKey.1.KeyPassphrase"
    ps = f"{base}.PreSharedKey.1.PreSharedKey"
    pwd = kp if _has_value(doc, kp) or not _has_value(doc, ps) else ps
    return ssid, pwd
# ==============================================================================

def resolve_wifi_params_tr181(doc: Dict[str, Any], band: str) -> Optional[Tuple[str, str]]:
    mapping = map_tr181_by_band(doc)
    if band not in mapping:
        return None
    ssid_i, ap_k, _radio = mapping[band]
    ssid_path = f"Device.WiFi.SSID.{ssid_i}.SSID"
    pass_a = f"Device.WiFi.AccessPoint.{ap_k}.Security.KeyPassphrase"
    pass_b = f"Device.WiFi.AccessPoint.{ap_k}.Security.PreSharedKey"
    pwd = pass_a if _has_value(doc, pass_a) or not _has_value(doc, pass_b) else pass_b
    return ssid_path, pwd

def resolve_wifi_params(doc: Dict[str, Any], band: str) -> Tuple[str, str]:
    r = resolve_wifi_params_tr181(doc, band)
    if r:
        return r
    return resolve_wifi_params_tr098(doc, band)

# ---------------------------------------------------------------------------
# IP resolvers (melhor-esforço)

def resolve_wan_ipv4(doc: Dict[str, Any]) -> Optional[str]:
    # TR-181: Device.IP.Interface.N.IPv4Address.1.IPAddress (preferindo interfaces "Up")
    iface = _get_node(doc, "Device.IP.Interface")
    if iface:
        for i in _iter_idx(iface):
            en = extract_value_from_path(doc, f"Device.IP.Interface.{i}.Status")
            addr = extract_value_from_path(doc, f"Device.IP.Interface.{i}.IPv4Address.1.IPAddress")
            if (en in ("Up","UP","Enabled",True)) and isinstance(addr, str) and addr:
                return addr
    # TR-098: WANIPConnection / WANPPPConnection
    for p in (
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress",
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANIPConnection.1.ExternalIPAddress",
        "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress",
    ):
        v = extract_value_from_path(doc, p)
        if isinstance(v, str) and v:
            return v
    # ConnectionRequestURL como fallback (pega host)
    cr = extract_value_from_path(doc, "InternetGatewayDevice.ManagementServer.ConnectionRequestURL") or \
         extract_value_from_path(doc, "Device.ManagementServer.ConnectionRequestURL")
    if isinstance(cr, str):
        try:
            host = urlparse(cr).hostname
            if host: return host
        except Exception:
            pass
    return None

def resolve_lan_ipv4(doc: Dict[str, Any]) -> Optional[str]:
    for p in (
        "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPInterface.1.IPInterfaceIPAddress",
        "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPInterface.1.IPAddress",
        "Device.LAN.IPAddress",
        "Device.IP.Interface.1.IPv4Address.1.IPAddress",
    ):
        v = extract_value_from_path(doc, p)
        if isinstance(v, str) and v:
            return v
    return None

def resolve_vendor_model_fw(doc: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    vendor = extract_value_from_path(doc, "InternetGatewayDevice.DeviceInfo.Manufacturer") or \
             extract_value_from_path(doc, "Device.DeviceInfo.Manufacturer")
    model = extract_value_from_path(doc, "InternetGatewayDevice.DeviceInfo.ProductClass") or \
            extract_value_from_path(doc, "Device.DeviceInfo.ProductClass") or \
            extract_value_from_path(doc, "Device.DeviceInfo.ModelName")
    fw = extract_value_from_path(doc, "InternetGatewayDevice.DeviceInfo.SoftwareVersion") or \
         extract_value_from_path(doc, "Device.DeviceInfo.SoftwareVersion")
    serial = extract_value_from_path(doc, "InternetGatewayDevice.DeviceInfo.SerialNumber") or \
             extract_value_from_path(doc, "Device.DeviceInfo.SerialNumber")
    return vendor, model, fw, serial

def resolve_ssids(doc: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    # TR-181 preferido
    m = map_tr181_by_band(doc)
    s24 = extract_value_from_path(doc, f"Device.WiFi.SSID.{m.get('2.4GHz', ('', '', ''))[0]}.SSID") if '2.4GHz' in m else None
    s5  = extract_value_from_path(doc, f"Device.WiFi.SSID.{m.get('5GHz', ('', '', ''))[0]}.SSID") if '5GHz' in m else None
    # TR-098 fallback
    if not s24:
        s24 = extract_value_from_path(doc, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID")
    if not s5:
        # tentar 3 antes de 2 (TP-Link)
        s5 = extract_value_from_path(doc, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.3.SSID") or \
             extract_value_from_path(doc, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID")
    return s24, s5

def pick_subscriber_from_tags(doc: Dict[str, Any]) -> Optional[str]:
    tags = doc.get("_tags")
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and t.startswith("sub:"):
                return t.split(":",1)[1] or None
    return None

# ---------------------------------------------------------------------------
# Models

class WifiCredentials(BaseModel):
    ssid: str
    password: str

class PPPoECredentials(BaseModel):
    username: str
    password: str

class ParameterRequest(BaseModel):
    parameter_names: List[str]

# ---------------------------------------------------------------------------
# Health & OPTIONS

@app.get("/health")
def health(): return {"ok": True, "nbi": NBI_URL, "version": "0.8.0", "now": _iso(datetime.utcnow())}

@app.options("/{full_path:path}")
def _opt_any(full_path: str): return Response(status_code=200)

# ---------------------------------------------------------------------------
# Core business (v0.6 compat)

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
    # Descoberta automática apenas se não vier override
    if not (parameter_ssid and parameter_password):
        band = "2.4GHz" if str(wlan_index) == "1" else "5GHz"
        ssid_path, pwd_path = resolve_wifi_params(doc, band)
    else:
        ssid_path, pwd_path = parameter_ssid, parameter_password
    task_body = {
        "name": "setParameterValues",
        "parameterValues": [
            [ssid_path, credentials.ssid, "xsd:string"],
            [pwd_path, credentials.password, "xsd:string"],
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
async def reboot_device(device_id: str, connection_request: bool = True, cr_timeout: int = 10, _: str = Depends(get_api_key)) -> dict:
    return await send_task(device_id, {"name": "reboot"}, connection_request, timeout=cr_timeout)

@app.post("/devices/{device_id:path}/factory_reset")
async def factory_reset(device_id: str, connection_request: bool = True, cr_timeout: int = 10, _: str = Depends(get_api_key)) -> dict:
    return await send_task(device_id, {"name": "factoryReset"}, connection_request, timeout=cr_timeout)

@app.post("/devices/{device_id:path}/parameters")
async def get_parameters(device_id: str, request: ParameterRequest, connection_request: bool = True, cr_timeout: int = 10, _: str = Depends(get_api_key)) -> dict:
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
        band = "2.4GHz" if str(wlan_index) == "1" else "5GHz"
        ssid_path, pwd_path = resolve_wifi_params(doc, band)
    else:
        ssid_path, pwd_path = parameter_ssid, parameter_password
    task_wifi = {"name": "setParameterValues", "parameterValues": [[ssid_path, credentials.ssid, "xsd:string"], [pwd_path, credentials.password, "xsd:string"]]}
    wifi_task = await send_task(device_id, task_wifi, connection_request, timeout=cr_timeout)
    reboot_task = await send_task(device_id, {"name": "reboot"}, connection_request=False)
    return {"wifi_task": wifi_task, "reboot_task": reboot_task, "note": "Wi-Fi aplicado e reboot agendado."}

@app.post("/devices/{device_id:path}/connreq")
async def connreq(device_id: str, cr_timeout: int = 10, _: str = Depends(get_api_key)) -> dict:
    body = {"name": "getParameterValues", "parameterNames": ["Device.DeviceInfo.SoftwareVersion"]}
    return await send_task(device_id, body, connection_request=True, timeout=cr_timeout)

@app.get("/devices/{device_id:path}/ssid")
async def read_ssid(device_id: str, wlan_index: int = 1, _: str = Depends(get_api_key)) -> dict:
    ssid_181 = f"Device.WiFi.SSID.{wlan_index}.SSID"
    ssid_098 = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{wlan_index}.SSID"
    doc = await fetch_device_doc(device_id)
    value = extract_value_from_path(doc, ssid_181) or extract_value_from_path(doc, ssid_098)
    return {"device": device_id, "parameter": ssid_181 if value else ssid_098, "value": value}

@app.get("/devices/{device_id:path}/read_value")
async def read_value(device_id: str, name: str = Query(..., description="Path TR-069 completo"), _: str = Depends(get_api_key)) -> dict:
    doc = await fetch_device_doc(device_id)
    value = extract_value_from_path(doc, name)
    return {"device": device_id, "parameter": name, "value": value}

# ---------------------------------------------------------------------------
# Métricas (como v0.6)

async def nbi_get_devices(query: dict, projection: Iterable[str] = (), limit: int = 1000, skip: int = 0, sort: Union[str, Dict[str, int], None] = None) -> List[dict]:
    params: Dict[str, str] = {"query": json.dumps(query), "limit": str(limit), "skip": str(skip)}
    if projection:
        params["projection"] = ",".join(projection)
    if sort:
        params["sort"] = json.dumps(sort) if isinstance(sort, dict) else str(sort)
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
        try: return int(total)
        except Exception: pass
    params["limit"] = "10000"
    resp = await _cli().get("/devices", params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return len(resp.json() or [])

async def _compute_overview(window_online_sec: int, window_24h_sec: int) -> dict:
    now = datetime.utcnow()
    t_online = _iso(now - timedelta(seconds=window_online_sec))
    t_24h = _iso(now - timedelta(seconds=window_24h_sec))
    total_devices = await nbi_count({})
    online_now = await nbi_count({"_lastInform": {"$gte": t_online}})
    active_24h = await nbi_count({"_lastInform": {"$gte": t_24h}})
    offline_24h = max(total_devices - active_24h, 0)
    return {"generated_at": _iso(now), "total_devices": total_devices, "online_now": online_now, "active_24h": active_24h, "offline_24h": offline_24h,
            "windows": {"online_sec": window_online_sec, "active_24h_sec": window_24h_sec}}

@app.get("/metrics/overview")
async def metrics_overview(window_online_sec: int = 600, window_24h_sec: int = 86400, _: str = Depends(get_api_key)) -> dict:
    return await _compute_overview(window_online_sec, window_24h_sec)

@app.get("/metrics/distribution")
async def metrics_distribution(sample_limit: int = 2000, _: str = Depends(get_api_key)) -> dict:
    proj = ["InternetGatewayDevice.DeviceInfo.ProductClass", "InternetGatewayDevice.DeviceInfo.SoftwareVersion", "Device.DeviceInfo.SoftwareVersion"]
    docs = await nbi_get_devices({}, projection=proj, limit=sample_limit, skip=0)
    def _v(d,p): return extract_value_from_path(d,p)
    pc, sv = {}, {}
    for d in docs:
        pcv = _v(d,"InternetGatewayDevice.DeviceInfo.ProductClass") or "UNKNOWN"
        svv = _v(d,"InternetGatewayDevice.DeviceInfo.SoftwareVersion") or _v(d,"Device.DeviceInfo.SoftwareVersion") or "UNKNOWN"
        pc[pcv] = pc.get(pcv,0)+1
        sv[svv] = sv.get(svv,0)+1
    return {"product_class": pc, "software_version": sv, "sampled": len(docs)}

@app.get("/metrics/last-informs")
async def metrics_last_informs(n: int = 50, _: str = Depends(get_api_key)) -> List[dict]:
    proj = ["_id","_lastInform","InternetGatewayDevice.DeviceInfo.ProductClass","InternetGatewayDevice.DeviceInfo.SoftwareVersion","Device.DeviceInfo.SoftwareVersion"]
    docs = await nbi_get_devices({}, projection=proj, limit=n, skip=0, sort={"_lastInform": -1})
    def _v(d,p): return extract_value_from_path(d,p)
    out: List[dict] = []
    for d in docs:
        out.append({"device_id": d.get("_id"), "last_inform": d.get("_lastInform"),
                    "product_class": _v(d,"InternetGatewayDevice.DeviceInfo.ProductClass"),
                    "software_version": _v(d,"InternetGatewayDevice.DeviceInfo.SoftwareVersion") or _v(d,"Device.DeviceInfo.SoftwareVersion")})
    return out

@app.get("/metrics/stream")
async def metrics_stream(request: Request, token: str, interval: int = 5, window_online_sec: int = 600, window_24h_sec: int = 86400):
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    async def event_gen():
        yield {"event": "overview", "data": json.dumps(await _compute_overview(window_online_sec, window_24h_sec))}
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(max(1, int(interval)))
            yield {"event": "overview", "data": json.dumps(await _compute_overview(window_online_sec, window_24h_sec))}
    return EventSourceResponse(event_gen(), ping=15)

# ---------------------------------------------------------------------------
# Lista de devices ENRIQUECIDA + Detalhe

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
        # busca por _id, ProductClass e SoftwareVersion
        q["$or"] = [
            {"_id": {"$regex": search, "$options": "i"}},
            {"InternetGatewayDevice.DeviceInfo.ProductClass._value": {"$regex": search, "$options": "i"}},
            {"InternetGatewayDevice.DeviceInfo.SoftwareVersion._value": {"$regex": search, "$options": "i"}},
        ]
    if tag:
        q["_tags"] = tag
    if product_class:
        q["InternetGatewayDevice.DeviceInfo.ProductClass._value"] = product_class
    if only_online:
        q["_lastInform"] = {"$gte": online_cut}

    total = await nbi_count(q)
    limit = max(1, min(500, page_size))
    skip = max(0, (max(1, page) - 1) * limit)

    sort_field_map = {
        "_lastInform": "_lastInform",
        "product_class": "InternetGatewayDevice.DeviceInfo.ProductClass._value",
        "software_version": "InternetGatewayDevice.DeviceInfo.SoftwareVersion._value",
    }
    sf = sort_field_map.get(sort_by, "_lastInform")
    sort_dict = {sf: -1 if order.lower() == "desc" else 1}

    proj = [
        "_id","_lastInform","_tags",
        "InternetGatewayDevice.DeviceInfo.ProductClass",
        "InternetGatewayDevice.DeviceInfo.SoftwareVersion",
        "Device.DeviceInfo.SoftwareVersion",
        "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID","Device.WiFi.SSID.1.SSID",
        "InternetGatewayDevice.ManagementServer.ConnectionRequestURL","Device.ManagementServer.ConnectionRequestURL",
        "Device.IP.Interface",
        "InternetGatewayDevice.WANDevice",
        "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement",
    ]
    docs = await nbi_get_devices(q, projection=proj, limit=limit, skip=skip, sort=sort_dict)
    def _v(d,p): return extract_value_from_path(d,p)

    items = []
    for d in docs:
        li = d.get("_lastInform")
        is_online = bool(li and li >= online_cut)
        vendor, model, fw, serial = resolve_vendor_model_fw(d)
        ssid = _v(d,"Device.WiFi.SSID.1.SSID") or _v(d,"InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID")
        ip_wan = resolve_wan_ipv4(d)
        ip_lan = resolve_lan_ipv4(d)
        sub = pick_subscriber_from_tags(d)
        items.append({
            "device_id": d.get("_id"),
            "serial_number": serial or d.get("_id"),
            "vendor": vendor,
            "product_class": model or "UNKNOWN",
            "software_version": fw,
            "last_inform": li,
            "online": is_online,
            "ssid": ssid,
            "ip": ip_wan or ip_lan or "—",
            "ip_wan": ip_wan,
            "ip_lan": ip_lan,
            "subscriber": sub,
            "tags": d.get("_tags") or [],
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

@app.get("/devices/detail/{device_id:path}")
async def device_detail(device_id: str, _: str = Depends(get_api_key)) -> dict:
    d = await fetch_device_doc(device_id)
    vendor, model, fw, serial = resolve_vendor_model_fw(d)
    ip_wan = resolve_wan_ipv4(d)
    ip_lan = resolve_lan_ipv4(d)
    s24, s5 = resolve_ssids(d)
    cr_url = extract_value_from_path(d, "InternetGatewayDevice.ManagementServer.ConnectionRequestURL") or \
             extract_value_from_path(d, "Device.ManagementServer.ConnectionRequestURL")
    stun_enable = extract_value_from_path(d, "InternetGatewayDevice.ManagementServer.STUNEnable") or \
                  extract_value_from_path(d, "Device.ManagementServer.STUNEnable")
    pii = extract_value_from_path(d, "InternetGatewayDevice.ManagementServer.PeriodicInformInterval") or \
          extract_value_from_path(d, "Device.ManagementServer.PeriodicInformInterval")
    return {
        "device_id": device_id,
        "serial_number": serial or device_id,
        "vendor": vendor,
        "product_class": model or "UNKNOWN",
        "software_version": fw,
        "last_inform": d.get("_lastInform"),
        "tags": d.get("_tags") or [],
        "subscriber": pick_subscriber_from_tags(d),
        "ip": {"wan_ipv4": ip_wan, "lan_ipv4": ip_lan},
        "wifi": {"ssid_24": s24, "ssid_5": s5},
        "mgmt": {"conn_req_url": cr_url, "stun_enable": bool(stun_enable), "periodic_inform_interval": pii},
    }
