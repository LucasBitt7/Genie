# file: exemplo_batch.py
import time
import acs_client as acs

DEVICE = "202BC1-BM632w-000102"

# muda Wi-Fi e reinicia
acs.wifi(DEVICE, ssid="kkkkk", password="senhaNova")
acs.reboot(DEVICE)

# espera 60 s e confirma (força leitura via getParameterValues)
time.sleep(60)
print(acs.get_params(DEVICE, [
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID"
]))
