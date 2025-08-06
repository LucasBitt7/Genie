"""
fetch_metrics.py – obtém parâmetros de desempenho e salva em metrics.csv
"""

import csv, time, acs_client as acs

DEVICES = [
    "202BC1-BM632w-000100",
    "202BC1-BM632w-000101",
]

PARAMS = [
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1."
    "WANPPPConnection.1.Stats.ByteRateReceived",
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1."
    "WANPPPConnection.1.Stats.ByteRateSent"
]

rows = []
for did in DEVICES:
    task = acs.get_params(did, PARAMS, connection_request=False)
    rows.append({"device": did, "task_id": task["_id"], "timestamp": task["timestamp"]})

# aguarda próxima inform (simulador) e exporta CSV
time.sleep(40)

with open("metrics.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print("CSV salvo em metrics.csv")
