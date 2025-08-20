#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GenieACS EX141 bootstrap (TR-181 + IPv6):
- Refresh: Device., Device.WiFi., Device.IP., DHCPv6.
- Get: ManagementServer (Inform/CR/STUN), SSID, IPv4, IPv6 e Prefixos.
- Ajuste opcional: Periodic Inform.
- STUN opcional (pode falhar com 9007; faça pela GUI se necessário).
pip install requests

python3 genieacs_ex141_bootstrap.py \
  --nbi http://127.0.0.1:7557 \
  --device 40ED00-EX141-22353Q1007438
  ou 
  python3 genieacs_ex141_bootstrap.py \
  --nbi http://127.0.0.1:7557 \
  --device 40ED00-EX141-22353Q1007438 \
  --use-connection-request
"""
import argparse, datetime as dt, json, os, sys
from typing import List, Tuple
import requests

def jprint(x): 
    print(json.dumps(x, ensure_ascii=False, indent=2, sort_keys=True))

def post_task(nbi, dev, payload, cr=False):
    """
    Envia uma tarefa para /devices/<id>/tasks.
    Se cr=True, adiciona '?connection_request' para tentar execução imediata.
    """
    url = f"{nbi.rstrip('/')}/devices/{dev}/tasks"
    if cr:
        url += "?connection_request"  # <- ativa Connection Request imediato (se houver UDP/HTTP CR funcional)
    r = requests.post(url, headers={"Content-Type":"application/json"},
                      data=json.dumps(payload), timeout=15)
    r.raise_for_status()
    return r.json()

def set_params(nbi, dev, params, cr=False):
    """params = [(param_name, value, xsd_type), ...]"""
    payload = {"name":"setParameterValues",
               "parameterValues":[[p, v, t] for (p, v, t) in params]}
    return post_task(nbi, dev, payload, cr)

def get_params(nbi, dev, names, cr=False):
    payload = {"name":"getParameterValues", "parameterNames": list(names)}
    return post_task(nbi, dev, payload, cr)

def refresh(nbi, dev, path, cr=False):
    payload = {"name":"refreshObject","objectName": path}
    return post_task(nbi, dev, payload, cr)

def discovery_tr181_ipv6(nbi, dev, cr=False):
    """
    Descoberta focada no TR-181, incluindo IPv6.
    Se cr=True, tenta execução imediata via Connection Request.
    """
    out = []
    # Subtrees
    for p in ("Device.", "Device.WiFi.", "Device.IP.", "Device.DHCPv6."):
        out.append(refresh(nbi, dev, p, cr))
    # ManagementServer (Inform/CR/STUN)
    out.append(get_params(nbi, dev, [
        "Device.ManagementServer.PeriodicInformEnable",
        "Device.ManagementServer.PeriodicInformInterval",
        "Device.ManagementServer.PeriodicInformTime",
        "Device.ManagementServer.ConnectionRequestURL",
        "Device.ManagementServer.UDPConnectionRequestAddress",
        "Device.ManagementServer.STUNEnable",
        "Device.ManagementServer.STUNServerAddress",
        "Device.ManagementServer.STUNServerPort",
        "Device.ManagementServer.STUNMinimumKeepAlivePeriod"
    ], cr))
    # Wi-Fi + IPv4
    out.append(get_params(nbi, dev, [
        "Device.WiFi.SSID.1.SSID", "Device.WiFi.SSID.2.SSID",
        "Device.IP.Interface.1.IPv4Address.1.IPAddress",
        "Device.IP.Interface.2.IPv4Address.1.IPAddress",
        "Device.IP.Interface.3.IPv4Address.1.IPAddress",
        "Device.IP.Interface.4.IPv4Address.1.IPAddress",
        "Device.IP.Interface.5.IPv4Address.1.IPAddress"
    ], cr))
    # IPv6 (endereços/prefixos e sinalizadores)
    out.append(get_params(nbi, dev, [
        "Device.IP.IPv6Capable",
        "Device.IP.IPv6Enable",
        "Device.DHCPv6.Client.1.Enable",
        "Device.DHCPv6.Client.1.Status",
        "Device.DHCPv6.Client.1.RequestAddresses",
        "Device.DHCPv6.Client.1.RequestPrefixes",
        "Device.IP.Interface.1.IPv6Address.1.IPAddress",
        "Device.IP.Interface.2.IPv6Address.1.IPAddress",
        "Device.IP.Interface.3.IPv6Address.1.IPAddress",
        "Device.IP.Interface.4.IPv6Address.1.IPAddress",
        "Device.IP.Interface.5.IPv6Address.1.IPAddress",
        "Device.IP.Interface.1.IPv6Prefix.1.Prefix",
        "Device.IP.Interface.2.IPv6Prefix.1.Prefix"
    ], cr))
    return out

def ensure_inform(nbi, dev, interval=60, set_time=True, cr=False):
    """Garante Inform habilitado e intervalo (idempotente)."""
    out = []
    out.append(set_params(nbi, dev, [
        ("Device.ManagementServer.PeriodicInformEnable", True, "xsd:boolean"),
        ("Device.ManagementServer.PeriodicInformInterval", int(interval), "xsd:unsignedInt"),
    ], cr))
    if set_time:
        now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        out.append(set_params(nbi, dev, [
            ("Device.ManagementServer.PeriodicInformTime", now, "xsd:dateTime"),
        ], cr))
    return out

def maybe_stun(nbi, dev, server="stun.cloudflare.com", port=3478, keep=30, cr=False):
    """Tenta configurar STUN pelo ACS (pode falhar com 9007 em alguns firmwares)."""
    return set_params(nbi, dev, [
        ("Device.ManagementServer.STUNEnable", True, "xsd:boolean"),
        ("Device.ManagementServer.STUNServerAddress", server, "xsd:string"),
        ("Device.ManagementServer.STUNServerPort", int(port), "xsd:unsignedInt"),
        ("Device.ManagementServer.STUNMinimumKeepAlivePeriod", int(keep), "xsd:unsignedInt"),
    ], cr)

def main():
    ap = argparse.ArgumentParser(description="GenieACS EX141 (IPv6 incluído) — discovery + ajustes")
    ap.add_argument("--nbi", default=os.environ.get("ACS_NBI","http://127.0.0.1:7557"))
    ap.add_argument("--device", required=True)
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--set-periodic-time", action="store_true")
    ap.add_argument("--with-stun", action="store_true")
    ap.add_argument("--stun-server", default="stun.cloudflare.com")
    ap.add_argument("--stun-port", type=int, default=3478)
    ap.add_argument("--stun-keepalive", type=int, default=30)
    ap.add_argument("--use-connection-request", action="store_true")
    a = ap.parse_args()

    outs = []
    print(f"[i] NBI={a.nbi}  DEV={a.device}  CR={'ON' if a.use_connection_request else 'OFF'}")
    print("[*] Discovery TR-181 + IPv6...")
    outs += discovery_tr181_ipv6(a.nbi, a.device, a.use_connection_request)

    if a.interval is not None:
        print(f"[*] Ajustando PeriodicInform={a.interval}s ...")
        outs += ensure_inform(a.nbi, a.device, a.interval, a.set_periodic_time, a.use_connection_request)

    if a.with_stun:
        print("[*] Tentando STUN via ACS...")
        try:
            outs.append(maybe_stun(a.nbi, a.device, a.stun_server, a.stun_port, a.stun_keepalive, a.use_connection_request))
        except requests.HTTPError as e:
            print("[!] STUN via ACS pode falhar (9007). Habilite na GUI do CPE se necessário.")
            print(f"[!] {e}")

    print("\n=== ACKs do NBI ===")
    for o in outs:
        jprint(o)
    print("\nOK. Veja os valores após o próximo Inform (ou imediato se UDP/HTTP CR estiver ativo).")
    return 0

if __name__=="__main__":
    try:
        sys.exit(main())
    except requests.RequestException as e:
        print(f"[ERRO] HTTP/NBI: {e}")
        sys.exit(2)
