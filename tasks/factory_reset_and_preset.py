"""
factory_reset_and_apply.py
1. Factory reset
2. Espera o dispositivo voltar (loop consulta devices)
3. Dispara Connection Request para aplicar a task do preset
"""

import time, acs_client as acs
import requests, urllib.parse, json

DEVICE = "202BC1-BM632w-000100"
NBI    = "http://localhost:7557"

print("Enviando factory reset…")
acs.factory_reset(DEVICE, connection_request=False)

# aguarda CPE rebootar (detecta novo Inform pelo campo _lastInform)
def last_inform():
    q = urllib.parse.urlencode({
        "query": json.dumps({"_id": DEVICE}),
        "projection": "_lastInform"
    })
    r = requests.get(f"{NBI}/devices/?{q}", timeout=5).json()
    return r[0]["_lastInform"]

t0 = last_inform()
print("Aguardando boot… (~60 s)")
while True:
    time.sleep(10)
    if last_inform() != t0:
        break
print("CPE voltou; disparando Connection Request para aplicar preset")
acs.reboot(DEVICE, connection_request=True)   # CR sem reboot real no sim
