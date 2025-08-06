"""
reboot_all.py – reinicia todos os devices presentes no ACS
"""

import json, urllib.parse, urllib.request
import acs_client as acs

NBI = "http://localhost:7557"

# 1) puxar lista de devices (somente _id)
query = urllib.parse.urlencode({
    "query": json.dumps({}),
    "projection": "_id"
})
with urllib.request.urlopen(f"{NBI}/devices/?{query}") as r:
    devices = [d["_id"] for d in json.load(r)]

print(f"Encontrados {len(devices)} devices → enviando reboot")
for did in devices:
    acs.reboot(did, connection_request=False)
    print("  ✔", did)
