"""
pppoe_update.py – altera credenciais PPPoE em lote
usage: python -m tasks.pppoe_update
"""

import acs_client as acs

DEVICES = [
    "202BC1-BM632w-000100",
    "202BC1-BM632w-000101",
    "202BC1-BM632w-000102",
]

NEW_USER = "cliente@provedor"
NEW_PASS = "senha1234"

for did in DEVICES:
    resp = acs.pppoe(did, username=NEW_USER, password=NEW_PASS,
                     enable=True, connection_request=False)
    print(f"{did}: task {_id := resp['_id']} enfileirada")
