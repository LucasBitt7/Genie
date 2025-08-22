/* global log:false, declare:false, clear:false, commit:false, args:false */

/**
 * Provision para EX141 (TR-181 + IPv6)
 * - Atualiza/descobre: Device., Device.WiFi., Device.IP., Device.DHCPv6.
 * - Lê e, se pedido via args, ajusta PeriodicInform.
 * - (Opcional) STUN (pode falhar em alguns firmwares; prefira GUI se der 9007).
 *
 * Args esperados no preset:
 *   interval:        inteiro (segundos) – se presente, força InformEnable=true e Interval=interval
 *   setPeriodicTime: boolean – se true, realinha PeriodicInformTime para agora (UTC)
 *   withStun:        boolean – se true, tenta habilitar STUN
 *   stunServer:      string  – host do STUN (ex.: "seu.ip.publico" ou FQDN)
 *   stunPort:        inteiro – porta STUN (padrão 3478)
 *   stunKeepalive:   inteiro – keepalive (padrão 30s)
 */

(function () {
  const now = Date.now();

  // 1) “Descobrir”/sincronizar subárvores principais (TR-181)
  // path: now => força refresh/rediscovery dessa subtree.
  declare("Device.",         { path: now });
  declare("Device.WiFi.",    { path: now });
  declare("Device.IP.",      { path: now });
  declare("Device.DHCPv6.",  { path: now });

  // 2) LER (e cachear fresco) os itens de ManagementServer que nos interessam
  declare("Device.ManagementServer.PeriodicInformEnable",        { value: now });
  declare("Device.ManagementServer.PeriodicInformInterval",      { value: now });
  declare("Device.ManagementServer.PeriodicInformTime",          { value: now });
  declare("Device.ManagementServer.ConnectionRequestURL",        { value: now });
  declare("Device.ManagementServer.UDPConnectionRequestAddress", { value: now });
  declare("Device.ManagementServer.STUNEnable",                  { value: now });
  declare("Device.ManagementServer.STUNServerAddress",           { value: now });
  declare("Device.ManagementServer.STUNServerPort",              { value: now });
  declare("Device.ManagementServer.STUNMinimumKeepAlivePeriod",  { value: now });

  // 3) LER SSIDs e IPs (TR-181) — usa curingas para não quebrar se não existir
  declare("Device.WiFi.SSID.*.SSID",                               { value: now });
  declare("Device.IP.Interface.*.IPv4Address.*.IPAddress",         { value: now });
  declare("Device.IP.IPv6Capable",                                  { value: now });
  declare("Device.IP.IPv6Enable",                                   { value: now });
  declare("Device.DHCPv6.Client.*.Enable",                          { value: now });
  declare("Device.DHCPv6.Client.*.Status",                          { value: now });
  declare("Device.DHCPv6.Client.*.RequestAddresses",                { value: now });
  declare("Device.DHCPv6.Client.*.RequestPrefixes",                 { value: now });
  declare("Device.IP.Interface.*.IPv6Address.*.IPAddress",          { value: now });
  declare("Device.IP.Interface.*.IPv6Prefix.*.Prefix",              { value: now });

  // 4) (Opcional) Ajuste de Periodic Inform (idempotente)
  if (args && args.interval) {
    declare("Device.ManagementServer.PeriodicInformEnable",   null, { value: true });
    declare("Device.ManagementServer.PeriodicInformInterval", null, { value: args.interval });
    if (args.setPeriodicTime) {
      // Para datetime em TR-069: [valor, "xsd:dateTime"]
      declare("Device.ManagementServer.PeriodicInformTime", null, { value: [new Date().toISOString(), "xsd:dateTime"] });
    }
  }

  // 5) (Opcional) Tentar habilitar STUN via ACS (alguns firmwares podem recusar: fault 9007)
  if (args && args.withStun) {
    declare("Device.ManagementServer.STUNEnable", null, { value: true });
    if (args.stunServer)    declare("Device.ManagementServer.STUNServerAddress",        null, { value: args.stunServer });
    if (args.stunPort)      declare("Device.ManagementServer.STUNServerPort",           null, { value: args.stunPort });
    if (args.stunKeepalive) declare("Device.ManagementServer.STUNMinimumKeepAlivePeriod", null, { value: args.stunKeepalive });
  }

  // commit é implícito, mas pode ser chamado se quiser ordenar fases.
  // commit();
})();
