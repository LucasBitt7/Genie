"""
genieacs_backend_mvp.py
========================

Pequena API FastAPI que encapsula tarefas do GenieACS (NBI) para operações
comuns em CPEs: alterar Wi-Fi, atualizar PPPoE, reboot, factory reset e leitura
de parâmetros. Inclui CORS e suporte a preflight para evitar erros 405 nos
navegadores.
"""

from typing import List, Optional
import os
import httpx

from fastapi import Depends, FastAPI, HTTPException, Security, status, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Configurações principais

# URL do NBI do GenieACS (padrão: porta 7557 local ou serviço Docker)
NBI_URL: str = os.getenv("GENIEACS_NBI_URL", "http://localhost:7557")

# Autenticação por API Key (requere header X-API-Key em todas as rotas)
API_KEY: Optional[str] = os.getenv("GENIEACS_API_KEY")
if not API_KEY:
    raise RuntimeError("GENIEACS_API_KEY environment variable must be set")
API_KEY_NAME: str = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Lista de origens do frontend autorizadas no CORS
# Ajuste via FRONTEND_ORIGINS="http://localhost:1234,http://127.0.0.1:1234"
DEFAULT_FRONT_ORIGINS = ["http://localhost:1234"]
_env = os.getenv("FRONTEND_ORIGINS")
ALLOWED_ORIGINS = [o.strip() for o in _env.split(",")] if _env else DEFAULT_FRONT_ORIGINS


def get_api_key(api_key_header: str = Security(api_key_header)) -> str:
    """Valida a API Key recebida via header X-API-Key."""
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or missing API Key",
    )


# ---------------------------------------------------------------------------
# Modelos de dados (Pydantic)

class WifiCredentials(BaseModel):
    ssid: str
    password: str


class PPPoECredentials(BaseModel):
    username: str
    password: str


class ParameterRequest(BaseModel):
    parameter_names: List[str]


# ---------------------------------------------------------------------------
# Aplicação FastAPI + CORS

app = FastAPI(
    title="GenieACS MVP Backend",
    description=(
        "API mínima para encapsular tarefas do NBI do GenieACS. "
        "Todas as requisições devem incluir a chave de API no header `X-API-Key`."
    ),
    version="0.1.0",
)

# CORS: permite o front (ex.: http://localhost:1234) chamar o backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,   # ex.: ["http://localhost:1234"]
    allow_credentials=True,          # ok mesmo sem cookies, mantém compatibilidade
    allow_methods=["*"],             # inclui OPTIONS para o preflight
    allow_headers=["*"],             # permite Content-Type, X-API-Key etc.
    expose_headers=["*"],
    max_age=86400,                   # cache do preflight por 1 dia
)


# ---------------------------------------------------------------------------
# Função utilitária para enviar tasks ao NBI

async def send_task(device_id: str, task_body: dict, connection_request: bool = False) -> dict:
    """
    Envia uma task ao NBI do GenieACS e retorna o objeto de task criado.

    Args:
        device_id: ID do dispositivo no GenieACS.
        task_body: Dicionário no formato esperado pelo NBI, por ex.:
                   {"name": "reboot"} ou
                   {"name": "setParameterValues", "parameterValues": [...]}
        connection_request: Se True, inclui ?connection_request para execução imediata.

    Returns:
        dict: JSON retornado pelo NBI com _id, status etc.

    Raises:
        HTTPException: se o NBI responder com status != 200/202.
    """
    url = f"{NBI_URL}/devices/{device_id}/tasks"
    params = {} if not connection_request else {"connection_request": ""}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, params=params, json=task_body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if response.status_code not in (200, 202):
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()




@app.api_route("/devices/{device_id}/wifi", methods=["POST", "OPTIONS"])
async def change_wifi(
    device_id: str,
    request: Request,
    credentials: Optional[WifiCredentials] = None,
    parameter_ssid: str = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID",
    parameter_password: str = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.PreSharedKey",
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    if request.method == "OPTIONS":
        return Response(status_code=200)
    if credentials is None:
        raise HTTPException(status_code=400, detail="Missing Wi-Fi credentials")
    task_body = {
        "name": "setParameterValues",
        "parameterValues": [
            [parameter_ssid, credentials.ssid, "xsd:string"],
            [parameter_password, credentials.password, "xsd:string"],
        ],
    }
    return await send_task(device_id, task_body, connection_request)


@app.api_route("/devices/{device_id}/pppoe", methods=["POST", "OPTIONS"])
async def change_pppoe(
    device_id: str,
    request: Request,
    credentials: Optional[PPPoECredentials] = None,
    enable: Optional[bool] = True,
    parameter_username: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username",
    parameter_password: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Password",
    parameter_enable: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Enable",
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    if request.method == "OPTIONS":
        return Response(status_code=200)
    if credentials is None:
        raise HTTPException(status_code=400, detail="Missing PPPoE credentials")
    parameter_values = [
        [parameter_username, credentials.username, "xsd:string"],
        [parameter_password, credentials.password, "xsd:string"],
    ]
    if enable is not None:
        parameter_values.append([parameter_enable, enable, "xsd:boolean"])
    task_body = {"name": "setParameterValues", "parameterValues": parameter_values}
    return await send_task(device_id, task_body, connection_request)


@app.api_route("/devices/{device_id}/reboot", methods=["POST", "OPTIONS"])
async def reboot_device(
    device_id: str,
    request: Request,
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    if request.method == "OPTIONS":
        return Response(status_code=200)
    task_body = {"name": "reboot"}
    return await send_task(device_id, task_body, connection_request)


@app.api_route("/devices/{device_id}/factory_reset", methods=["POST", "OPTIONS"])
async def factory_reset(
    device_id: str,
    request: Request,
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    if request.method == "OPTIONS":
        return Response(status_code=200)
    task_body = {"name": "factoryReset"}
    return await send_task(device_id, task_body, connection_request)


@app.api_route("/devices/{device_id}/parameters", methods=["POST", "OPTIONS"])
async def get_parameters(
    device_id: str,
    request: Request,
    param_req: Optional[ParameterRequest] = None,
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    if request.method == "OPTIONS":
        return Response(status_code=200)
    if not param_req:
        raise HTTPException(status_code=400, detail="Missing parameter names")
    task_body = {
        "name": "getParameterValues",
        "parameterNames": param_req.parameter_names,
    }
    return await send_task(device_id, task_body, connection_request)
