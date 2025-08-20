#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genieacs_ex141_bootstrap.py

Automação via NBI (porta 7557) do GenieACS para CPEs TP-Link EX141:
- Refresh TR-181 (Device., Device.WiFi., Device.IP.)
- Get de SSID/IP + ManagementServer (PeriodicInform*, CR/UDP, STUN*)
- Ajuste opcional do Periodic Inform (idempotente)
- Tentativa opcional de configurar STUN via ACS (alguns firmwares recusam)

OBS: O NBI agenda tarefas e retorna ACK imediato; os valores aparecem no próximo Inform
ou imediatamente se houver Connection Request (UDP CR) funcional.

pip install requests

python3 genieacs_ex141_bootstrap.py \
  --nbi http://127.0.0.1:7557 \
  --device 40ED00-EX141-22353Q1007438 \
  --interval 60 --set-periodic-time
"""

import argparse
import datetime as dt
import json
import os
import sys
from typing import List, Tuple

import requests


def jprint(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))


def post_task(nbi: str, dev_id: str, payload: dict, use_connection_request: bool = False):
    """
    Envia uma tarefa para /devices/<id>/tasks.

    Args:
        nbi: URL base do NBI (ex.: http://127.0.0.1:7557)
        dev_id: Device ID no GenieACS (ex.: 40ED00-EX141-22353Q1007438)
        payload: dict com {"name": "...", ...}
        use_connection_request: se True, adiciona ?connection_request (requer UDP CR funcional)
    """
    url = f"{nbi.rstrip('/')}/devices/{dev_id}/tasks"
    if use_connection_request:
        url += "?connection_request"
    r = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=15)
    r.raise_for_status()
    return r.json()


def set_params(nbi: str, dev_id: str, params: List[Tuple[str, object, str]], use_cr: bool = False):
    """Agenda setParameterValues com lista [(param, valor, xsd_type), ...]."""
    payload = {"name": "setParameterValues", "parameterValues": [[p, v, t] for (p, v, t) in params]}
    return post_task(nbi, dev_id, payload, use_cr)


def get_params(nbi: str, dev_id: str, names: List[str], use_cr: bool = False):
    """Agenda getParameterValues."""
    payload = {"name": "getParameterValues", "parameterNames": list(names)}
    return post_task(nbi, dev_id, payload, use_cr)


def refresh_object(nbi: str, dev_id: str, path: str, use_cr: bool = False):
    """Agenda refreshObject de um caminho (ex.: Device.WiFi.)."""
    payload = {"name": "refreshObject", "objectName": path}
    return post_task(nbi, dev_id, payload, use_cr)


def discovery_ex141_tr181(nbi: str, dev_id: str, use_cr: bool = False):
    """Descoberta focada no TR-181 (EX141)."""
    out = []
    out.append(refresh_object(nbi, dev_id, "Device.", use_cr))
    out.append(refresh_object(nbi, dev_id, "Device.WiFi.", use_cr))
    out.append(refresh_object(nbi, dev_id, "Device.IP.", use_cr))

    # ManagementServer (depuração: Inform/CR/UDP/STUN)
    out.append(get_params(nbi, dev_id, [
        "Device.ManagementServer.PeriodicInformEnable",
        "Device.ManagementServer.PeriodicInformInterval",
        "Device.ManagementServer.PeriodicInformTime",
        "Device.ManagementServer.ConnectionRequestURL",
        "Device.ManagementServer.UDPConnectionRequestAddress",
        "Device.ManagementServer.STUNEnable",
        "Device.ManagementServer.STUNServerAddress",
        "Device.ManagementServer.STUNServerPort",
        "Device.ManagementServer.STUNMinimumKeepAlivePeriod"
    ], use_cr))

    # SSIDs e IPs IPv4 (índices comuns; se não existir, ignore)
    out.append(get_params(nbi, dev_id, [
        "Device.WiFi.SSID.1.SSID",
        "Device.WiFi.SSID.2.SSID",
        "Device.IP.Interface.1.IPv4Address.1.IPAddress",
        "Device.IP.Interface.2.IPv4Address.1.IPAddress",
        "Device.IP.Interface.3.IPv4Address.1.IPAddress",
        "Device.IP.Interface.4.IPv4Address.1.IPAddress",
        "Device.IP.Interface.5.IPv4Address.1.IPAddress"
    ], use_cr))
    return out


def ensure_periodic_inform(nbi: str, dev_id: str, interval: int = 60, set_time: bool = True, use_cr: bool = False):
    """Garante PeriodicInformEnable=true / Interval (idempotente)."""
    out = []
    out.append(set_params(nbi, dev_id, [
        ("Device.ManagementServer.PeriodicInformEnable", True, "xsd:boolean"),
        ("Device.ManagementServer.PeriodicInformInterval", int(interval), "xsd:unsignedInt"),
    ], use_cr))
    if set_time:
        now_utc = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        out.append(set_params(nbi, dev_id, [
            ("Device.ManagementServer.PeriodicInformTime", now_utc, "xsd:dateTime"),
        ], use_cr))
    return out


def maybe_set_stun(nbi: str, dev_id: str, server: str = "stun.cloudflare.com", port: int = 3478,
                   keepalive: int = 30, use_cr: bool = False):
    """
    Tenta configurar STUN via ACS (pode falhar com 9007; firmware pode exigir GUI).
    """
    return set_params(nbi, dev_id, [
        ("Device.ManagementServer.STUNEnable", True, "xsd:boolean"),
        ("Device.ManagementServer.STUNServerAddress", server, "xsd:string"),
        ("Device.ManagementServer.STUNServerPort", int(port), "xsd:unsignedInt"),
        ("Device.ManagementServer.STUNMinimumKeepAlivePeriod", int(keepalive), "xsd:unsignedInt"),
    ], use_cr)


def main():
    ap = argparse.ArgumentParser(description="Automação GenieACS para EX141 (TR-181, Inform, SSID/IP, UDP CR/STUN opcional).")
    ap.add_argument("--nbi", default=os.environ.get("ACS_NBI", "http://127.0.0.1:7557"),
                    help="URL do NBI do GenieACS (ex.: http://127.0.0.1:7557)")
    ap.add_argument("--device", required=True, help="Device ID no GenieACS (ex.: 40ED00-EX141-22353Q1007438)")
    ap.add_argument("--interval", type=int, default=None, help="PeriodicInformInterval desejado (omita se já está ok).")
    ap.add_argument("--set-periodic-time", action="store_true", help="Realinhar PeriodicInformTime para agora (UTC).")
    ap.add_argument("--with-stun", action="store_true", help="Tenta habilitar STUN via ACS (pode falhar com 9007).")
    ap.add_argument("--stun-server", default="stun.cloudflare.com", help="Host STUN (se --with-stun).")
    ap.add_argument("--stun-port", type=int, default=3478, help="Porta STUN (se --with-stun).")
    ap.add_argument("--stun-keepalive", type=int, default=30, help="KeepAlive STUN em segundos (se --with-stun).")
    ap.add_argument("--use-connection-request", action="store_true",
                    help="Usa ?connection_request nos tasks (requer UDP CR funcional).")
    args = ap.parse_args()

    outputs = []

    print(f"[i] NBI    = {args.nbi}")
    print(f"[i] Device = {args.device}")
    print(f"[i] CR     = {'ON' if args.use_connection_request else 'OFF'}")

    print("[*] Discovery TR-181...")
    outputs += discovery_ex141_tr181(args.nbi, args.device, args.use_connection_request)

    if args.interval is not None:
        print(f"[*] Garantindo PeriodicInform = {args.interval}s ...")
        outputs += ensure_periodic_inform(args.nbi, args.device, args.interval, args.set_periodic_time,
                                          args.use_connection_request)

    if args.with_stun:
        print("[*] Tentando habilitar STUN via ACS...")
        try:
            outputs.append(maybe_set_stun(args.nbi, args.device, args.stun_server,
                                          args.stun_port, args.stun_keepalive, args.use_connection_request))
        except requests.HTTPError as e:
            print("[!] STUN via ACS falhou (9007 comum). Habilite pela GUI do CPE se necessário.")
            print(f"[!] HTTPError: {e}")

    print("\n=== ACKs do NBI ===")
    for o in outputs:
        jprint(o)

    print("\nOK. Valores devem aparecer após o próximo Inform (ou imediato se UDP CR estiver funcional).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException as e:
        print(f"[ERRO] Falha HTTP/NBI: {e}")
        sys.exit(2)
