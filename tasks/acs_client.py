"""
acs_client.py
Pequena biblioteca que encapsula chamadas ao backend FastAPI (genieacs_backend_mvp).
"""

from typing import List, Optional
import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---------------------------------------------------------------------
# Config
BACKEND_URL: str = os.getenv("ACS_BACKEND_URL", "http://localhost:8000")
API_KEY: str = os.getenv("ACS_API_KEY")
if not API_KEY:
    raise RuntimeError("ACS_API_KEY environment variable must be set")


# ---------------------------------------------------------------------
# Funções utilitárias
def _post(endpoint: str, payload: dict, params: Optional[dict] = None) -> dict:
    """
    Envia POST ao backend e devolve JSON (levanta exceção para HTTP≠2xx).
    """
    url = f"{BACKEND_URL}{endpoint}"
    resp = requests.post(
        url, json=payload, params=params, headers={"X-API-Key": API_KEY}
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------
# Wrappers de task
def wifi(device_id: str, ssid: str, password: str,
         connection_request: bool = False) -> dict:
    """
    Altera SSID e senha Wi-Fi no CPE.
    """
    return _post(f"/devices/{device_id}/wifi",
                 {"ssid": ssid, "password": password},
                 {"connection_request": str(connection_request).lower()})


def pppoe(device_id: str, username: str, password: str,
          enable: bool = True,
          connection_request: bool = False) -> dict:
    """
    Atualiza credenciais PPPoE; por padrão já habilita a interface.
    """
    return _post(f"/devices/{device_id}/pppoe",
                 {"username": username, "password": password},
                 {"enable": str(enable).lower(),
                  "connection_request": str(connection_request).lower()})


def reboot(device_id: str, connection_request: bool = False) -> dict:
    """
    Reinicia o CPE.
    """
    return _post(f"/devices/{device_id}/reboot", {},
                 {"connection_request": str(connection_request).lower()})


def factory_reset(device_id: str, connection_request: bool = False) -> dict:
    """
    Restaura configurações de fábrica do CPE.
    """
    return _post(f"/devices/{device_id}/factory_reset", {},
                 {"connection_request": str(connection_request).lower()})


def get_params(device_id: str, names: List[str],
               connection_request: bool = False) -> dict:
    """
    Solicita valores atuais de parâmetros TR-069.
    """
    return _post(f"/devices/{device_id}/parameters",
                 {"parameter_names": names},
                 {"connection_request": str(connection_request).lower()})
