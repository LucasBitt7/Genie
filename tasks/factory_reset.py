# -*- coding: utf-8 -*-
"""
factory_reset_definitivo.py
Objetivo: reset de fábrica "definitivo" e a UI do GenieACS refletindo os valores de fábrica.
Fluxo:
  1) Envia APENAS factory reset (com Connection Request).
  2) Aguarda o reboot (_lastBoot/_lastInform no NBI).
  3) Faz UMA leitura (getParameterValues) de parâmetros-chave (SSID/PPP) para atualizar a UI.
     -> GPV é leitura, não altera config. Serve para a UI mostrar o estado de fábrica.
"""

import os
import time
import json
import urllib.parse
import requests
import acs_client as acs

# =========================
# VARIÁVEIS (edite conforme seu ambiente)
# =========================
DEVICE = os.getenv("DEVICE", "202BC1-BM632w-000102")     # ID do CPE no ACS
NBI_URL = os.getenv("NBI_URL", "http://localhost:7557")  # URL do NBI (porta 7557)

# Tempos (segundos)
POLL_INTERVAL_SEC   = int(os.getenv("POLL_INTERVAL_SEC", "5"))     # intervalo entre checagens
TIMEOUT_TOTAL_SEC   = int(os.getenv("TIMEOUT_TOTAL_SEC", "600"))   # tempo máx aguardando reboot (10 min)
WAIT_STABILIZE_SEC  = int(os.getenv("WAIT_STABILIZE_SEC", "15"))   # espera extra após reboot

# Quais parâmetros vamos "refrescar" no ACS para a UI mostrar o estado de fábrica
# (ajuste conforme seu CPE; abaixo cobre SSID 2.4/5G e PPPoE)
REFRESH_PARAMS = [
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID",
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Username",
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.Password",
]

# Opcional: parâmetro "inofensivo" para cutucar CR caso a detecção demore
PING_PARAM = os.getenv("PING_PARAM", "InternetGatewayDevice.DeviceInfo.SerialNumber")
PING_AFTER_SEC = int(os.getenv("PING_AFTER_SEC", "45"))  # após quantos segundos sem sinal de reboot tentar um GPV só de leitura

# =========================
# Helpers (APENAS leitura no NBI; não disparam tasks)
# =========================
def _nbi_get_projection(fields):
    """Busca apenas alguns campos do doc do device no NBI (não dispara task)."""
    q = urllib.parse.urlencode({
        "query": json.dumps({"_id": DEVICE}),
        "projection": ",".join(fields)
    })
    r = requests.get(f"{NBI_URL}/devices/?{q}", timeout=10)
    r.raise_for_status()
    arr = r.json() or []
    if not arr:
        raise RuntimeError("Device não encontrado no ACS")
    return arr[0]

def _nbi_get_full():
    """Busca o documento completo do device no NBI (não dispara task)."""
    q = urllib.parse.urlencode({"query": json.dumps({"_id": DEVICE})})
    r = requests.get(f"{NBI_URL}/devices/?{q}", timeout=15)
    r.raise_for_status()
    arr = r.json() or []
    if not arr:
        raise RuntimeError("Device não encontrado no ACS")
    return arr[0]

def _extract_value(doc, dotted_path):
    """Percorre o doc e retorna _value quando existir (mesma visão da UI)."""
    cur = doc
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    if isinstance(cur, dict) and "_value" in cur:
        return cur["_value"]
    return cur

def last_boot():
    return _nbi_get_projection(["_lastBoot"]).get("_lastBoot")

def last_inform():
    return _nbi_get_projection(["_lastInform"]).get("_lastInform")

# =========================
# Execução
# =========================
if __name__ == "__main__":
    print(f"[1/4] Enviando FACTORY RESET (única task) com Connection Request → {DEVICE}")
    # ÚNICA task "de ação": factory reset.
    acs.factory_reset(DEVICE, connection_request=True)

    print("[2/4] Aguardando reboot do CPE…")
    t0_boot   = last_boot()
    t0_inform = last_inform()
    deadline = time.time() + TIMEOUT_TOTAL_SEC

    poke_sent = False
    reboot_detectado = False

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SEC)

        tb, ti = None, None
        try: tb = last_boot()
        except: pass
        try: ti = last_inform()
        except: pass

        # Preferência: mudança em _lastBoot
        if t0_boot and tb and tb != t0_boot:
            reboot_detectado = True
            print("   → reboot detectado por _lastBoot")
            break

        # Fallback: mudança em _lastInform
        if t0_inform and ti and ti != t0_inform:
            reboot_detectado = True
            print("   → mudança detectada em _lastInform")
            break

        # Se demorou demais sem sinal, "cutuca" com um GPV inofensivo (só leitura) p/ tentar novo CR
        if not poke_sent and (time.time() >= (deadline - TIMEOUT_TOTAL_SEC + PING_AFTER_SEC)):
            try:
                print("   → forçando uma leitura (GPV) do SerialNumber para estimular CR…")
                acs.get_params(DEVICE, [PING_PARAM], connection_request=True)
                poke_sent = True
            except Exception as e:
                print(f"   (aviso) falha ao forçar GPV: {e}")

    if not reboot_detectado:
        raise RuntimeError("Timeout aguardando reboot após factory reset.")

    print(f"[3/4] Reboot detectado. Aguardando estabilizar serviços ({WAIT_STABILIZE_SEC}s)…")
    time.sleep(WAIT_STABILIZE_SEC)

    # ---- ATUALIZAÇÃO DA UI (apenas leitura) ----
    # Para a UI refletir o estado de fábrica, pedimos UMA leitura dos parâmetros
    # que você quer ver atualizados (SSID/PPP). Isso não altera config do CPE.
    print("[4/4] Fazendo UMA leitura (GPV) de SSID/PPP para a UI refletir o estado de fábrica…")
    try:
        acs.get_params(DEVICE, REFRESH_PARAMS, connection_request=True)
    except Exception as e:
        print(f"   (aviso) leitura GPV falhou: {e}")

    # Mostra na tela o que a UI deve passar a exibir
    doc = _nbi_get_full()
    for p in REFRESH_PARAMS:
        print(f"   {p} = {repr(_extract_value(doc, p))}")

    print("✔ Reset de fábrica concluído e UI atualizada por leitura (sem alterar config adicional).")
