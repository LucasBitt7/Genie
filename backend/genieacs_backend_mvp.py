# -*- coding: utf-8 -*-
"""
GenieACS MVP Backend (v0.3.0)

- CORS + rotas OPTIONS explícitas (preflight OK).
- Compatível com ACS_API_KEY e legado GENIEACS_API_KEY.
- device_id usa conversor :path.
- /wifi: auto-detecta o parâmetro de senha (KeyPassphrase vs PreSharedKey).
- /wifi_and_reboot: aplica Wi-Fi e agenda reboot (com opção de connection request).
- /ssid e /read_value: leem valores do ACS corretamente (campo _value).
"""

from typing import List, Optional, Any, Dict
import os
import json
import httpx

from fastapi import Depends, FastAPI, HTTPException, Security, status, Request, Header, Query
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configurações principais

NBI_URL: str = os.getenv("GENIEACS_NBI_URL", "http://localhost:7557")

def _read_file_if_exists(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def load_api_key() -> str:
    """
    Ordem de carga:
      1) ACS_API_KEY
      2) ACS_API_KEY_FILE
      3) GENIEACS_API_KEY (legado)
      4) GENIEACS_API_KEY_FILE (legado)
    """
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

DEFAULT_FRONT_ORIGINS = ["http://localhost:1234"]
_env = os.getenv("FRONTEND_ORIGINS")
ALLOWED_ORIGINS = [o.strip() for o in _env.split(",")] if _env else DEFAULT_FRONT_ORIGINS

def get_api_key(request: Request, api_key_header: Optional[str] = Security(api_key_scheme)) -> str:
    # Libera preflight OPTIONS sem exigir header
    if request.method == "OPTIONS":
        return ""
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing API Key")

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
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],     # inclui OPTIONS
    allow_headers=["*"],     # Content-Type, X-API-Key etc.
    expose_headers=["*"],
    max_age=86400,
)

# ---------------------------------------------------------------------------
# Helpers NBI / leitura

async def send_task(device_id: str, task_body: dict, connection_request: bool = False, timeout: Optional[int] = None) -> dict:
    """
    Cria uma task no NBI (/devices/{id}/tasks).
    Se connection_request=True, adiciona ?connection_request e, opcionalmente, ?timeout=n.
    """
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
    """Lê o documento do device no ACS (NBI /devices?query={_id:...})."""
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

def extract_value_from_path(doc: Dict[str, Any], dotted_path: str) -> Any:
    """Percorre o doc seguindo o caminho e retorna o campo `_value` quando presente."""
    cur: Any = doc
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    if isinstance(cur, dict) and "_value" in cur:
        return cur["_value"]
    return cur

def resolve_wifi_params(doc: Dict[str, Any], wlan_index: int) -> Dict[str, str]:
    """
    Decide qual parâmetro de senha usar para o Wi-Fi daquele device.
    Preferência:
      1) ...PreSharedKey.1.KeyPassphrase  (se existir no doc)
      2) ...PreSharedKey.1.PreSharedKey   (se existir no doc)
      3) fallback para KeyPassphrase (muitos CPEs aceitam essa forma)
    """
    base = f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{wlan_index}"
    ssid = f"{base}.SSID"

    kp = f"{base}.PreSharedKey.1.KeyPassphrase"
    ps = f"{base}.PreSharedKey.1.PreSharedKey"

    has_kp = extract_value_from_path(doc, kp) is not None or (kp in str(doc))
    has_ps = extract_value_from_path(doc, ps) is not None or (ps in str(doc))

    if has_kp:
        pwd = kp
    elif has_ps:
        pwd = ps
    else:
        # Fallback pragmático: muitos vendors aceitam KeyPassphrase
        pwd = kp
    return {"parameter_ssid": ssid, "parameter_password": pwd}

# ---------------------------------------------------------------------------
# Rotas OPTIONS explícitas (CORS preflight)

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
# Endpoints de negócio

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
    """
    Altera SSID/senha.
    - Se `parameter_*` não forem informados, tenta detectar a senha correta (KeyPassphrase vs PreSharedKey).
    - `wlan_index`: índice da WLANConfiguration (1, 2, ...).
    - `connection_request` + `cr_timeout`: tenta execução imediata.
    """
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
    parameter_values = [
        [parameter_username, credentials.username, "xsd:string"],
        [parameter_password, credentials.password, "xsd:string"],
    ]
    if enable is not None:
        parameter_values.append([parameter_enable, enable, "xsd:boolean"])
    task_body = {"name": "setParameterValues", "parameterValues": parameter_values}
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
    """
    Aplica Wi-Fi e agenda reboot (como no seu script).
    """
    doc = await fetch_device_doc(device_id)
    if not (parameter_ssid and parameter_password):
        res = resolve_wifi_params(doc, wlan_index)
        parameter_ssid = parameter_ssid or res["parameter_ssid"]
        parameter_password = parameter_password or res["parameter_password"]

    # 1) muda Wi-Fi (tenta CR)
    task_wifi = {
        "name": "setParameterValues",
        "parameterValues": [
            [parameter_ssid, credentials.ssid, "xsd:string"],
            [parameter_password, credentials.password, "xsd:string"],
        ],
    }
    wifi_task = await send_task(device_id, task_wifi, connection_request, timeout=cr_timeout)

    # 2) agenda reboot (sem CR adicional)
    reboot_task = await send_task(device_id, {"name": "reboot"}, connection_request=False)

    return {
        "wifi_task": wifi_task,
        "reboot_task": reboot_task,
        "note": "Wi-Fi aplicado e reboot agendado. Se o CR falhar, o reboot forçará nova sessão."
    }

# ---------------------------------------------------------------------------
# Leitura de valores no ACS

@app.get("/devices/{device_id:path}/ssid")
async def read_ssid(
    device_id: str,
    wlan_index: int = 1,
    _: str = Depends(get_api_key),
) -> dict:
    """Lê do ACS o SSID atual (campo _value)."""
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
    """Lê do ACS o valor de qualquer parâmetro (por caminho)."""
    doc = await fetch_device_doc(device_id)
    value = extract_value_from_path(doc, name)
    return {"device": device_id, "parameter": name, "value": value}
