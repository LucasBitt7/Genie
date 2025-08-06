"""
genieacs_backend_mvp.py
========================

This module exposes a small FastAPI application that abstracts some of the
common tasks you might want to perform on customer‑premises equipment (CPE)
using GenieACS’s northbound interface (NBI).  The objective is to provide a
simple REST API for an internet service provider (ISP) to perform day‑to‑day
operations such as changing a Wi‑Fi password, updating PPPoE credentials,
rebooting a device and resetting it to factory defaults.  Each of these
operations is implemented as a POST request that wraps the relevant
`POST /devices/<device_id>/tasks` call in GenieACS.  If a task should be
executed immediately, you can opt into sending a connection request by
setting the `connection_request` query parameter.

The code is deliberately small and easy to extend.  The environment
variable ``GENIEACS_NBI_URL`` controls where tasks are sent; by default it
assumes the NBI service is reachable on ``http://localhost:7557`` as it
would be when running inside the Docker Compose environment shown in the
question.

Variables are annotated and explained inline to make the code easy to follow
for engineers familiar with Python and REST APIs.

Usage example (run from the command line):

.. code-block:: bash

    uvicorn genieacs_backend_mvp:app --reload --host 0.0.0.0 --port 8000

Once running, you can issue a POST request to change the Wi‑Fi SSID and
password for a device identified by ``device_id``:

.. code-block:: bash

    curl -X POST http://localhost:8000/devices/ABC123/wifi \
      -H 'Content-Type: application/json' \
      -d '{"ssid":"MyNetwork","password":"secret"}'

Note that the API simply wraps the underlying GenieACS calls; it does not
validate that the parameter paths exist on the target device.  If the device
does not support a given parameter name (e.g. some vendors use
``KeyPassphrase`` while others use ``PreSharedKey.1.PreSharedKey``), the task
will fail.  You can override the default parameter names using the optional
function parameters documented below.
"""

import os
from typing import List, Optional

import requests
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Configuration
#
# The base URL for the GenieACS NBI component.  In the provided Docker
# Compose file the NBI service is exposed on host port 7557, so the default
# value of ``http://localhost:7557`` is correct when running this API on
# the same host.  You can override this by setting the GENIEACS_NBI_URL
# environment variable, e.g. ``export GENIEACS_NBI_URL=http://genieacs-nbi``.
NBI_URL: str = os.getenv("GENIEACS_NBI_URL", "http://localhost:7557")

# Simple API key authentication.  The expected key is read from the
# ``GENIEACS_API_KEY`` environment variable.  Requests must supply this key in
# the ``X-API-Key`` header to access the endpoints.  Using FastAPI's security
# utilities ensures the requirement is documented in the generated OpenAPI
# schema and interactive docs.
API_KEY: Optional[str] = os.getenv("GENIEACS_API_KEY")
if not API_KEY:
    raise RuntimeError("GENIEACS_API_KEY environment variable must be set")
API_KEY_NAME: str = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def get_api_key(api_key_header: str = Security(api_key_header)) -> str:
    """Validate the provided API key.

    Raises:
        HTTPException: If the key is missing or does not match the expected
            value.
    """

    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or missing API Key",
    )


# ---------------------------------------------------------------------------
# Data models
#
# Using Pydantic models enforces type checks on incoming JSON payloads and
# provides automatic documentation via FastAPI’s OpenAPI schema.

class WifiCredentials(BaseModel):
    """Schema for Wi‑Fi credentials.

    Attributes:
        ssid: New network name to assign to the CPE.
        password: New pre‑shared key (passphrase) to assign to the CPE.
    """

    ssid: str
    password: str


class PPPoECredentials(BaseModel):
    """Schema for PPPoE credentials.

    Attributes:
        username: PPPoE username to be configured on the CPE.
        password: PPPoE password to be configured on the CPE.
    """

    username: str
    password: str


class ParameterRequest(BaseModel):
    """Schema for requesting arbitrary parameter values.

    Attributes:
        parameter_names: A list of parameter paths to read.  Each path must
            conform to the TR‑069/USP dot notation (e.g.
            ``InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID``).
    """

    parameter_names: List[str]


# ---------------------------------------------------------------------------
# Application factory
#
# FastAPI automatically documents the endpoints and handles request parsing.
app = FastAPI(title="GenieACS MVP Backend",
              description=(
                  "A minimal API for wrapping GenieACS NBI tasks.  This service "
                  "allows callers to trigger common CPE operations via simple "
                  "HTTP endpoints.  All requests must include a valid API key "
                  "in the `X-API-Key` header."
              ),
              version="0.1.0")


def send_task(device_id: str, task_body: dict, connection_request: bool = False) -> dict:
    """Send a task to the GenieACS NBI and return the resulting task object.

    Args:
        device_id: The unique identifier of the CPE.  This is typically the
            serial number and model concatenated together; it appears in the
            GenieACS UI under the device page.  It must already exist in the
            GenieACS database.
        task_body: A dictionary that matches the GenieACS NBI task schema.  For
            example, ``{"name": "reboot"}`` or
            ``{"name": "setParameterValues", "parameterValues": [[...], ...]}``.
        connection_request: If True, include the ``connection_request``
            query parameter to instruct GenieACS to immediately send a
            Connection Request to the CPE.  If False, the task will be queued
            and processed the next time the CPE informs the ACS.

    Returns:
        The JSON response from GenieACS which includes details of the task,
        such as its MongoDB ``_id`` and status.

    Raises:
        HTTPException: If GenieACS responds with an error status code.
    """
    # Build the URL for posting tasks to a specific device
    url = f"{NBI_URL}/devices/{device_id}/tasks"
    # Query parameters are used to trigger the connection request.  When
    # ``connection_request`` is truthy, we send an empty parameter key; any
    # non‑empty value would be ignored by GenieACS.  See the API docs for
    # details【757314803093476†L155-L167】.
    params = {} if not connection_request else {"connection_request": ""}
    try:
        response = requests.post(url, params=params, json=task_body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Successful task insertion returns 200 (executed immediately) or 202
    # (queued).  Any other status code indicates a problem.
    if response.status_code not in (200, 202):
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )
    return response.json()


@app.post("/devices/{device_id}/wifi")
def change_wifi(
    device_id: str,
    credentials: WifiCredentials,
    parameter_ssid: str = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID",
    parameter_password: str = "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.PreSharedKey",
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    """Change the Wi‑Fi SSID and password for a given device.

    GenieACS allows you to set multiple parameters in one task via the
    ``setParameterValues`` operation【757314803093476†L406-L424】.  You can
    customise the parameter names if your CPE uses different paths (e.g.
    ``KeyPassphrase`` instead of ``PreSharedKey.1.PreSharedKey``).  The
    default parameter names correspond to the example in the official
    documentation for changing Wi‑Fi SSID and password【507113905048260†L1025-L1034】.

    Args:
        device_id: Device identifier as stored in GenieACS.
        credentials: Pydantic model containing the new SSID and password.
        parameter_ssid: Optional override for the SSID parameter path.
        parameter_password: Optional override for the passphrase parameter path.
        connection_request: Whether to trigger an immediate connection request.

    Returns:
        JSON representation of the created task.
    """
    task_body = {
        "name": "setParameterValues",
        "parameterValues": [
            [parameter_ssid, credentials.ssid, "xsd:string"],
            [parameter_password, credentials.password, "xsd:string"],
        ],
    }
    return send_task(device_id, task_body, connection_request)


@app.post("/devices/{device_id}/pppoe")
def change_pppoe(
    device_id: str,
    credentials: PPPoECredentials,
    enable: Optional[bool] = True,
    parameter_username: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username",
    parameter_password: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Password",
    parameter_enable: str = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Enable",
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    """Update PPPoE username and password on a CPE.

    This endpoint demonstrates how to set multiple WAN parameters at once.
    The default parameter names come from the TR‑069 specification and
    appear in device configuration guides【669472655843428†L64-L72】.

    Args:
        device_id: Device identifier as stored in GenieACS.
        credentials: Pydantic model containing the PPPoE username and password.
        enable: If provided, sets the Enable flag for the PPP connection.
        parameter_username: Override for the username parameter path.
        parameter_password: Override for the password parameter path.
        parameter_enable: Override for the enable parameter path.
        connection_request: Whether to trigger an immediate connection request.

    Returns:
        JSON representation of the created task.
    """
    parameter_values = [
        [parameter_username, credentials.username, "xsd:string"],
        [parameter_password, credentials.password, "xsd:string"],
    ]
    # Only include the enable parameter if explicitly passed (None means leave unchanged).
    if enable is not None:
        parameter_values.append([parameter_enable, enable, "xsd:boolean"])
    task_body = {
        "name": "setParameterValues",
        "parameterValues": parameter_values,
    }
    return send_task(device_id, task_body, connection_request)


@app.post("/devices/{device_id}/reboot")
def reboot_device(
    device_id: str,
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    """Reboot a CPE immediately or queue the operation.

    The ``reboot`` task takes no additional arguments【757314803093476†L441-L447】.

    Args:
        device_id: Device identifier as stored in GenieACS.
        connection_request: Whether to trigger an immediate connection request.

    Returns:
        JSON representation of the created task.
    """
    task_body = {"name": "reboot"}
    return send_task(device_id, task_body, connection_request)


@app.post("/devices/{device_id}/factory_reset")
def factory_reset(
    device_id: str,
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    """Reset a CPE to its factory defaults.

    The ``factoryReset`` task takes no additional arguments【757314803093476†L448-L453】.

    Args:
        device_id: Device identifier as stored in GenieACS.
        connection_request: Whether to trigger an immediate connection request.

    Returns:
        JSON representation of the created task.
    """
    task_body = {"name": "factoryReset"}
    return send_task(device_id, task_body, connection_request)


@app.post("/devices/{device_id}/parameters")
def get_parameters(
    device_id: str,
    request: ParameterRequest,
    connection_request: bool = True,
    _: str = Depends(get_api_key),
) -> dict:
    """Read one or more parameters from the CPE.

    Under the hood this uses the ``getParameterValues`` task which instructs
    the CPE to return the current values of the specified parameter paths
    【757314803093476†L368-L387】.  After the task is executed, the values can
    be retrieved by querying the device via ``GET /devices``.

    Args:
        device_id: Device identifier as stored in GenieACS.
        request: Body containing the list of parameter names to fetch.
        connection_request: Whether to trigger an immediate connection request.

    Returns:
        JSON representation of the created task.
    """
    task_body = {
        "name": "getParameterValues",
        "parameterNames": request.parameter_names,
    }
    return send_task(device_id, task_body, connection_request)
