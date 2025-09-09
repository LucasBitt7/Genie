import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Cpu,
  Menu,
  PlugZap,
  Search as SearchIcon,
  ServerCog,
  Settings,
  Users,
  Wifi,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import {
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  BarChart,
  Bar,
} from "recharts";

// =====================================================================
// CONFIG / API CLIENT
// =====================================================================

const API_BASE = (import.meta as any).env?.VITE_API_BASE || "/api";

function getApiKey(): string {
  return (
    (typeof window !== "undefined" && localStorage.getItem("GENIEACS_API_KEY")) ||
    (import.meta as any).env?.VITE_API_KEY ||
    ""
  );
}
function setApiKey(v: string) {
  if (typeof window !== "undefined") localStorage.setItem("GENIEACS_API_KEY", v);
}

type ApiOpts = RequestInit & { query?: Record<string, any> };

async function api<T>(path: string, opts: ApiOpts = {}): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (opts.query) {
    Object.entries(opts.query).forEach(([k, v]) => {
      if (v === undefined || v === null || v === "") return;
      url.searchParams.set(k, String(v));
    });
  }
  url.pathname = (API_BASE.replace(/\/+$/, "") + "/" + path.replace(/^\/+/, "")).replace(/\/{2,}/g, "/");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    "X-API-Key": getApiKey(),
    ...(opts.headers || {}),
  };
  const res = await fetch(url.toString(), { ...opts, headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  if (res.status === 204) return undefined as unknown as T;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? (await res.json()) as T : (await res.text()) as unknown as T;
}

// =====================================================================
// Tipos & Wrappers
// =====================================================================

export type DeviceStatus = "online" | "offline" | "provisioning" | "error";

export type Device = {
  id: string;
  serialNumber: string;
  model: string;
  ip: string;
  status: DeviceStatus;
  lastInform: string; // ISO
  subscriber?: string;
};

export type DeviceDetail = {
  device_id: string;
  serial_number: string;
  vendor?: string;
  product_class?: string;
  software_version?: string;
  last_inform?: string;
  tags: string[];
  subscriber?: string;
  ip: { wan_ipv4?: string | null; lan_ipv4?: string | null };
  wifi: { ssid_24?: string | null; ssid_5?: string | null };
  mgmt: { conn_req_url?: string | null; stun_enable: boolean; periodic_inform_interval?: number | null };
};

export type Paged<T> = { items: T[]; total: number; page: number; pageSize: number };

// Health
async function getHealth() {
  const r = await api<{ ok: boolean; version?: string }>("/health", {
    method: "GET",
    headers: { "X-API-Key": "" },
  });
  return { status: r.ok ? "ok" : "down", version: r.version, now: new Date().toISOString() };
}

// Lista de devices
function listDevices(params: {
  page?: number;
  pageSize?: number;
  q?: string;
  status?: DeviceStatus | "all";
  sort?: string; // "lastInform:desc" etc.
}) {
  const page = params.page ?? 1;
  const page_size = params.pageSize ?? 10;
  const only_online = params.status === "online";
  const order = params.sort?.endsWith(":asc") ? "asc" : "desc";
  return api<{
    items: Array<{
      device_id: string;
      serial_number?: string;
      product_class?: string;
      software_version?: string;
      last_inform?: string;
      online: boolean;
      ssid?: string;
      ip?: string;
      ip_wan?: string | null;
      ip_lan?: string | null;
      subscriber?: string | null;
      tags?: string[];
    }>;
    total: number;
    page: number;
    page_size: number;
  }>("/devices/list", {
    query: { page, page_size, search: params.q, only_online, sort_by: "_lastInform", order },
  }).then((r) => {
    const items: Device[] = (r.items || []).map((it) => ({
      id: it.device_id,
      serialNumber: it.serial_number || it.device_id,
      model: it.product_class || "UNKNOWN",
      ip: it.ip || "—",
      status: it.online ? "online" : "offline",
      lastInform: it.last_inform || "",
      subscriber: it.subscriber || undefined,
    }));
    return { items, total: r.total, page: r.page, pageSize: r.page_size } as Paged<Device>;
  });
}

// Detalhe
function getDeviceDetail(id: string) {
  return api<DeviceDetail>(`/devices/detail/${id}`);
}

// Ações
function deviceConnReq(id: string) { return api(`/devices/${id}/connreq`, { method: "POST" }); }
function deviceReboot(id: string) { return api(`/devices/${id}/reboot`, { method: "POST" }); }
function deviceFactoryReset(id: string) { return api(`/devices/${id}/factory_reset`, { method: "POST" }); }
function deviceReadValue(id: string, name: string) { return api<{ value: any }>(`/devices/${id}/read_value`, { query: { name } }); }
function deviceGetSSID(id: string, wlanIndex = 1) {
  return api<{ value: any }>(`/devices/${id}/ssid`, { query: { wlan_index: wlanIndex } })
    .then((r) => ({ ssid: r.value ?? "" }));
}
function deviceGetParameters(id: string, paths: string[]) {
  return Promise.all(paths.map(async (p) => [p, (await deviceReadValue(id, p)).value] as [string, any]))
    .then((entries) => ({ values: Object.fromEntries(entries) as Record<string, any> }));
}
function deviceSetWifi(id: string, data: { ssid: string; password: string; wlan_index?: number }) {
  const query: any = {};
  if (data.wlan_index) query.wlan_index = data.wlan_index;
  return api(`/devices/${id}/wifi`, { method: "POST", body: JSON.stringify({ ssid: data.ssid, password: data.password }), query });
}
function deviceSetPPPoE(id: string, data: { username: string; password: string; enable?: boolean }) {
  return api(`/devices/${id}/pppoe`, { method: "POST", body: JSON.stringify(data) });
}

// Métricas
type MetricsOverview = { online: number; offline: number; provisioning: number; error: number; uptime?: number; };
function getMetricsOverview(_window: string = "1h") {
  return api<{ total_devices: number; online_now: number }>(`/metrics/overview`)
    .then((r) => {
      const online = r.online_now ?? 0;
      const total = r.total_devices ?? 0;
      const offline = Math.max(total - online, 0);
      return { online, offline, provisioning: 0, error: 0 } as MetricsOverview;
    });
}
function getMetricsLastInforms(limit = 10) {
  return api<Array<{ device_id: string; last_inform: string; product_class?: string }>>(`/metrics/last-informs`, { query: { n: limit } })
    .then((arr) => arr.map((d) => ({ id: d.device_id, serialNumber: d.device_id, model: d.product_class || "UNKNOWN", ip: "—", at: d.last_inform })));
}
function getMetricsDistribution(kind: "model" | "firmware" = "model") {
  return api<{ product_class: Record<string, number>; software_version: Record<string, number> }>(`/metrics/distribution`)
    .then((r) => {
      const src = kind === "model" ? r.product_class : r.software_version;
      return Object.entries(src || {}).map(([key, count]) => ({ key, count }));
    });
}
function openMetricsStream(onMsg: (ev: MessageEvent) => void) {
  const url = new URL("/metrics/stream", window.location.origin);
  url.pathname = (API_BASE.replace(/\/+$/, "") + "/metrics/stream");
  const token = getApiKey();
  if (token) url.searchParams.set("token", token);
  const es = new EventSource(url.toString());
  es.addEventListener("overview", onMsg as any);
  return es;
}

// =====================================================================
// CSV OVERLAY — aceita formato "largo" e export GenieACS (Parameter,Value)
// =====================================================================

const CSV_OVERLAY_URL = "/static/devices.csv";
type OverlayRow = { device_id: string; ssid_24?: string; ssid_5?: string; model?: string };

let _overlayLoaded = false;
let _overlayById: Map<string, OverlayRow> = new Map();

function _canon(h: string) { return h.trim().toLowerCase().replace(/\s+/g, "_"); }
function _pick(row: Record<string,string>, names: string[]) {
  for (const n of names) {
    const key = Object.keys(row).find(k => _canon(k) === _canon(n));
    if (key && row[key] !== undefined && row[key] !== "") return row[key];
  }
  return undefined;
}
function _splitCsvLine(line: string): string[] {
  const out: string[] = []; let cur = ""; let inQ = false;
  for (let i=0;i<line.length;i++){
    const c = line[i];
    if (c === '"') { if (inQ && line[i+1] === '"'){ cur+='"'; i++; } else inQ = !inQ; }
    else if (c === ',' && !inQ) { out.push(cur); cur=""; }
    else cur += c;
  }
  out.push(cur);
  return out.map(s=>s.trim());
}
function _parseCsv(text: string): OverlayRow[] {
  const lines = text.replace(/\r/g,"").split("\n").filter(Boolean);
  if (lines.length === 0) return [];
  const headers = _splitCsvLine(lines[0]).map(h => h.trim());
  const rows: OverlayRow[] = [];

  const isParamExport = headers.some(h => _canon(h) === "parameter") && headers.some(h => _canon(h) === "value");

  if (isParamExport) {
    const kv: Record<string,string> = {};
    for (let i=1;i<lines.length;i++){
      const cols = _splitCsvLine(lines[i]);
      const obj: Record<string,string> = {};
      headers.forEach((h,idx)=>{ obj[h]= (cols[idx] ?? "").trim(); });
      const param = _pick(obj, ["parameter"]);
      const val = _pick(obj, ["value"]) ?? "";
      if (param) kv[param] = val;
    }

    const device_id = kv["InternetGatewayDevice.DeviceInfo.SerialNumber"] ?? kv["Device.DeviceInfo.SerialNumber"] ?? "";
    if (device_id) {
      let ssid24 =
        kv["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID"] ??
        kv["Device.WiFi.SSID.1.SSID"] ?? "";
      if (!ssid24) {
        ssid24 =
          kv["InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID"] ??
          kv["Device.WiFi.SSID.2.SSID"] ?? "";
      }

      let ssid5 =
        kv["InternetGatewayDevice.LANDevice.1.WLANConfiguration.3.SSID"] ??
        kv["Device.WiFi.SSID.3.SSID"] ?? "";
      if (!ssid5) {
        ssid5 =
          kv["InternetGatewayDevice.LANDevice.1.WLANConfiguration.4.SSID"] ??
          kv["Device.WiFi.SSID.4.SSID"] ??
          kv["InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID"] ??
          kv["Device.WiFi.SSID.2.SSID"] ?? "";
      }

      const model =
        kv["Device.DeviceInfo.ModelName"] ??
        kv["InternetGatewayDevice.DeviceInfo.ProductClass"] ??
        kv["Device.DeviceInfo.ProductClass"] ?? "";

      rows.push({
        device_id,
        ssid_24: ssid24 || undefined,
        ssid_5:  ssid5  || undefined,
        model:   model   || undefined,
      });
    }
  } else {
    for (let i=1;i<lines.length;i++){
      const cols = _splitCsvLine(lines[i]);
      const obj: Record<string,string> = {};
      headers.forEach((h,idx)=>{ obj[h]= (cols[idx] ?? "").trim(); });
      const device_id = _pick(obj, ["device_id","id","_id","serial","serial_number"]);
      if (!device_id) continue;
      rows.push({
        device_id,
        ssid_24: _pick(obj, ["ssid_24","wifi_ssid_24","ssid2g","ssid_2g","ssid_24g","ssid24","wlan1_ssid"]),
        ssid_5:  _pick(obj, ["ssid_5","wifi_ssid_5","ssid5g","ssid_5g","ssid5","wlan2_ssid"]),
        model:   _pick(obj, ["model","product_class","modelo","productclass","model_name","modelname"]),
      });
    }
  }
  return rows;
}
async function loadOverlayOnce(): Promise<void> {
  if (_overlayLoaded) return;
  try {
    const res = await fetch(CSV_OVERLAY_URL, { cache: "no-store" });
    if (!res.ok) { _overlayLoaded = true; return; }
    const text = await res.text();
    const rows = _parseCsv(text);
    _overlayById = new Map(rows.map(r => [r.device_id, r]));
  } catch {}
  _overlayLoaded = true;
}
async function getOverlayFor(id: string): Promise<OverlayRow | null> {
  await loadOverlayOnce();
  return _overlayById.get(id) || null;
}

// =====================================================================
// Helpers para SSID por caminhos TR-098/TR-181 (sem depender de /ssid)
// =====================================================================

function pickFirst(values: Record<string, any>, keys: string[]): string {
  for (const k of keys) {
    const v = values[k];
    if (typeof v === "string" && v.trim() !== "") return v.trim();
  }
  return "";
}
async function fetchSSIDsDirect(id: string): Promise<{ s24: string; s5: string }> {
  const paths = [
    // 2.4G
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID",
    "Device.WiFi.SSID.1.SSID",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID",
    "Device.WiFi.SSID.2.SSID",
    // 5G
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.3.SSID",
    "Device.WiFi.SSID.3.SSID",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.4.SSID",
    "Device.WiFi.SSID.4.SSID",
    // fallback 5G se fabricante usar índice 2
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID",
    "Device.WiFi.SSID.2.SSID",
  ];
  const res = await deviceGetParameters(id, paths);
  const v = res.values || {};
  const s24 = pickFirst(v, [
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID",
    "Device.WiFi.SSID.1.SSID",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID",
    "Device.WiFi.SSID.2.SSID",
  ]);
  const s5 = pickFirst(v, [
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.3.SSID",
    "Device.WiFi.SSID.3.SSID",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.4.SSID",
    "Device.WiFi.SSID.4.SSID",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration.2.SSID",
    "Device.WiFi.SSID.2.SSID",
  ]);
  return { s24, s5 };
}

// =====================================================================
// "Scripts" UI helpers
// =====================================================================

async function taskWifi24(id: string, ssid: string, pass: string) { return deviceSetWifi(id, { ssid, password: pass, wlan_index: 1 }); }
async function taskWifi5(id: string, ssid: string, pass: string)  { return deviceSetWifi(id, { ssid, password: pass, wlan_index: 2 }); }
async function taskWifiDual(id: string, s24: string, p24: string, s5: string, p5: string) { await taskWifi24(id, s24, p24); return taskWifi5(id, s5, p5); }

// =====================================================================
// HELPERS / UI
// =====================================================================

const statusColor: Record<DeviceStatus, string> = {
  online: "bg-emerald-500/15 text-emerald-500 border-emerald-500/20",
  offline: "bg-slate-500/15 text-slate-400 border-slate-500/20",
  provisioning: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  error: "bg-rose-500/15 text-rose-400 border-rose-500/20",
};

function formatRelative(ts: string) {
  if (!ts) return "—";
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / (1000 * 60));
  if (m < 1) return "agora";
  if (m < 60) return `${m} min atrás`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h atrás`;
  const d = Math.floor(h / 24);
  return `${d} d atrás`;
}

function useDebounce<T>(value: T, delay = 400) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

// =====================================================================
// NAV STRUCTURE
// =====================================================================

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", icon: Activity },
  { key: "devices", label: "Dispositivos", icon: Cpu },
  { key: "subscribers", label: "Assinantes", icon: Users },
  { key: "tasks", label: "Tarefas", icon: ServerCog },
  { key: "alarms", label: "Alertas", icon: AlertTriangle },
  { key: "settings", label: "Configurações", icon: Settings },
] as const;

type NavKey = (typeof NAV_ITEMS)[number]["key"];

// =====================================================================
// ROOT COMPONENT
// =====================================================================

export default function GenieACSAdminShell() {
  const [active, setActive] = useState<NavKey>("dashboard");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | DeviceStatus>("all");

  const [health, setHealth] = useState<{ status: string; version?: string } | null>(null);
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    const it = setInterval(() => getHealth().then(setHealth).catch(() => setHealth(null)), 30000);
    return () => clearInterval(it);
  }, []);

  return (
    <div className="dark">
      <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100 transition-colors">
        {/* Top Bar */}
        <header className="sticky top-0 z-40 backdrop-blur bg-slate-900/60 border-b border-slate-800">
          <div className="max-w-7xl mx-auto px-3 sm:px-6 py-3 flex items-center gap-3">
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="lg:hidden">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="p-0">
                <MobileNav active={active} onChange={setActive} />
              </SheetContent>
            </Sheet>

            <div className="hidden lg:flex">
              <Logo />
            </div>

            <div className="flex-1" />

            {/* Busca + filtros */}
            <div className="hidden md:flex items-center gap-2 w-[520px] max-w-full">
              <div className="relative flex-1">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <Input
                  placeholder="Buscar dispositivos, IP, modelo, assinante..."
                  className="pl-9"
                  value={query}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)}
                />
              </div>
              <Select value={status} onValueChange={(v: string) => setStatus(v as any)}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  <SelectItem value="online">Online</SelectItem>
                  <SelectItem value="provisioning">Provisionando</SelectItem>
                  <SelectItem value="offline">Offline</SelectItem>
                  <SelectItem value="error">Erro</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Direita: badge + API Key */}
            <div className="flex items-center gap-3">
              <Badge variant="outline" className={`text-xs ${health?.status === "ok" ? "border-emerald-500/30 text-emerald-300" : "border-rose-500/30 text-rose-400"}`}>
                <PlugZap className="h-3.5 w-3.5 mr-1" /> {health?.status === "ok" ? "backend ok" : "backend?"}
              </Badge>

              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm">API Key</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader><DialogTitle>Chave de Acesso</DialogTitle></DialogHeader>
                  <div className="space-y-2">
                    <Input
                      placeholder="cole aqui sua X-API-Key"
                      defaultValue={typeof window !== "undefined" ? getApiKey() : ""}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setApiKey(e.target.value)}
                    />
                    <div className="text-xs opacity-70">Header enviado: <code>X-API-Key</code></div>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="max-w-7xl mx-auto px-3 sm:px-6 py-6 grid grid-cols-1 lg:grid-cols-[240px,1fr] gap-6">
          <aside className="hidden lg:block">
            <Sidebar active={active} onChange={setActive} />
          </aside>

          <main>
            {active === "dashboard" && (
              <Dashboard />
            )}
            {active === "devices" && (
              <Devices query={query} onQuery={setQuery} status={status} onStatus={setStatus} />
            )}
            {active !== "dashboard" && active !== "devices" && (
              <ComingSoon what={NAV_ITEMS.find((n) => n.key === active)?.label || "Em breve"} />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// PIECES
// =====================================================================

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-blue-600 to-emerald-500 grid place-items-center text-white shadow-md">
        <Wifi className="h-4 w-4" />
      </div>
      <div className="leading-tight">
        <div className="font-semibold">PulseNet</div>
        <div className="text-[11px] opacity-60 -mt-0.5">GenieACS Console</div>
      </div>
    </div>
  );
}

function Sidebar({ active, onChange }: { active: NavKey; onChange: (k: NavKey) => void }) {
  return (
    <nav className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur p-2">
      {NAV_ITEMS.map((item) => (
        <button
          key={item.key}
          onClick={() => onChange(item.key)}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition hover:bg-slate-800/60 ${
            active === item.key
              ? "bg-gradient-to-r from-blue-600/10 to-emerald-500/10 text-emerald-300"
              : "text-slate-300"
          }`}
        >
          <item.icon className="h-4 w-4" />
          {item.label}
        </button>
      ))}
    </nav>
  );
}

function MobileNav({ active, onChange }: { active: NavKey; onChange: (k: NavKey) => void }) {
  return (
    <div className="h-full flex flex-col">
      <SheetHeader className="p-4">
        <SheetTitle className="flex items-center gap-2">
          <Logo />
        </SheetTitle>
      </SheetHeader>
      <div className="p-3 space-y-1">
        {NAV_ITEMS.map((n) => (
          <button
            key={n.key}
            onClick={() => onChange(n.key)}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition ${
              active === n.key
                ? "bg-gradient-to-r from-blue-600/10 to-emerald-500/10 text-emerald-300"
                : "hover:bg-slate-800/60 text-slate-200"
            }`}
          >
            <n.icon className="h-4 w-4" />
            {n.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function KPI({ title, value, icon: Icon, delta, tone }: {
  title: string;
  value: string | number;
  icon: any;
  delta?: string;
  tone?: "up" | "down";
}) {
  return (
    <Card className="border-slate-800/70">
      <CardHeader className="flex items-center justify-between flex-row py-3">
        <CardTitle className="text-sm font-medium opacity-80">{title}</CardTitle>
        <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-blue-600/90 to-emerald-500/90 grid place-items-center text-white shadow">
          <Icon className="h-4 w-4" />
        </div>
      </CardHeader>
      <CardContent className="py-0 pb-3">
        <div className="text-2xl font-semibold">{value}</div>
        {delta && (
          <div className={`text-xs mt-1 ${tone === "down" ? "text-rose-500" : "text-emerald-400"}`}>
            {tone === "down" ? "▼" : "▲"} {delta}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ------------------ Dashboard ------------------
function Dashboard() {
  const [window, setWindow] = useState("1h");
  const [overview, setOverview] = useState<MetricsOverview | null>(null);
  const [last, setLast] = useState<Array<{ id: string; serialNumber: string; model: string; ip: string; at: string }>>([]);
  const [dist, setDist] = useState<Array<{ key: string; count: number }>>([]);

  useEffect(() => {
    getMetricsOverview(window).then(setOverview).catch(() => setOverview(null));
    getMetricsLastInforms(8).then(setLast).catch(() => setLast([]));
    getMetricsDistribution("model").then(setDist).catch(() => setDist([]));
  }, [window]);

  useEffect(() => {
    const es = openMetricsStream((ev) => {
      try {
        const data = JSON.parse((ev as any).data);
        setOverview({
          online: data.online_now ?? 0,
          offline: Math.max((data.total_devices ?? 0) - (data.online_now ?? 0), 0),
          provisioning: 0,
          error: 0,
        });
      } catch {}
    });
    return () => es.close();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-lg font-semibold">Visão geral</div>
        <Select value={window} onValueChange={(v: string) => setWindow(v)}>
          <SelectTrigger className="w-[160px]"><SelectValue placeholder="Janela" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="15m">15 min</SelectItem>
            <SelectItem value="1h">1 hora</SelectItem>
            <SelectItem value="24h">24 horas</SelectItem>
            <SelectItem value="7d">7 dias</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 md:gap-6">
        <KPI title="Online" value={overview?.online ?? "—"} icon={Wifi} />
        <KPI title="Provisionando" value={overview?.provisioning ?? "—"} icon={ServerCog} />
        <KPI title="Offline" value={overview?.offline ?? "—"} icon={Cpu} />
        <KPI title="Erros" value={overview?.error ?? "—"} icon={AlertTriangle} />
        <KPI title="Modelos" value={dist.reduce((a, b) => a + (b.count || 0), 0)} icon={Settings} />
      </div>

      <Card className="border-slate-800/70">
        <CardHeader>
          <CardTitle>Distribuição por modelo (Top)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dist} margin={{ left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="key" tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} />
                <RTooltip cursor={{ strokeDasharray: "3 3" }} />
                <Bar dataKey="count" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-800/70">
        <CardHeader>
          <CardTitle>Últimos informs</CardTitle>
        </CardHeader>
        <CardContent className="grid sm:grid-cols-2 gap-3">
          {last.map((t) => (
            <div key={`${t.id}-${t.at}`} className="flex items-center gap-3 p-3 rounded-xl border border-slate-800/70">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-blue-600/90 to-emerald-500/90 grid place-items-center text-white">
                <Activity className="h-4 w-4" />
              </div>
              <div className="text-sm">
                <div className="font-medium">{t.serialNumber} <span className="opacity-60">({t.model})</span></div>
                <div className="opacity-70 text-xs">{t.ip} · {formatRelative(t.at)}</div>
              </div>
            </div>
          ))}
          {last.length === 0 && <div className="opacity-60 text-sm">Sem eventos recentes.</div>}
        </CardContent>
      </Card>
    </div>
  );
}

// ------------------ Devices ------------------
function Devices({
  query,
  onQuery,
  status,
  onStatus,
}: {
  query: string;
  onQuery: (s: string) => void;
  status: "all" | DeviceStatus;
  onStatus: (s: "all" | DeviceStatus) => void;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [sort, setSort] = useState("lastInform:desc");
  const dQuery = useDebounce(query, 400);

  const [data, setData] = useState<Paged<Device>>({ items: [], total: 0, page: 1, pageSize });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    listDevices({ page, pageSize, q: dQuery, status, sort })
      .then((res) => setData(res))
      .catch(() => setData({ items: [], total: 0, page: 1, pageSize }))
      .finally(() => setLoading(false));
  }, [page, pageSize, dQuery, status, sort]);

  function refresh() {
    setLoading(true);
    listDevices({ page, pageSize, q: dQuery, status, sort })
      .then(setData)
      .finally(() => setLoading(false));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col md:flex-row gap-2 md:items-center md:justify-between">
        <div className="text-lg font-semibold">Dispositivos (CPEs)</div>
        <div className="flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 md:w-[360px]">
            <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              placeholder="Buscar por serial, modelo, IP, assinante..."
              className="pl-9"
              value={query}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => onQuery(e.target.value)}
            />
          </div>
          <Select value={status} onValueChange={(v: string) => onStatus(v as any)}>
            <SelectTrigger className="w-[160px]"><SelectValue placeholder="Status" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="online">Online</SelectItem>
              <SelectItem value="provisioning">Provisionando</SelectItem>
              <SelectItem value="offline">Offline</SelectItem>
              <SelectItem value="error">Erro</SelectItem>
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(v: string) => setSort(v)}>
            <SelectTrigger className="w-[180px]"><SelectValue placeholder="Ordenar" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="lastInform:desc">Mais recentes</SelectItem>
              <SelectItem value="lastInform:asc">Mais antigos</SelectItem>
              <SelectItem value="model:asc">Modelo A→Z</SelectItem>
              <SelectItem value="model:desc">Modelo Z→A</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={refresh}>Atualizar</Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-800/70">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/40">
            <tr className="text-left">
              <Th>STATUS</Th>
              <Th>MODELO</Th>
              <Th>SERIAL</Th>
              <Th>IP</Th>
              <Th>ASSINANTE</Th>
              <Th>ÚLTIMO INFORM</Th>
              <Th className="text-right">AÇÕES</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {data.items.map((d) => (
              <tr key={d.id} className="hover:bg-slate-900/40">
                <Td>
                  <span className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full border ${statusColor[d.status]}`}>
                    <span className="h-1.5 w-1.5 rounded-full bg-current"></span>
                    {d.status}
                  </span>
                </Td>
                <Td>{d.model}</Td>
                <Td className="font-mono text-xs">{d.serialNumber}</Td>
                <Td className="font-mono text-xs">{d.ip}</Td>
                <Td>{d.subscriber ?? "—"}</Td>
                <Td>{formatRelative(d.lastInform)}</Td>
                <Td className="text-right">
                  <DeviceActions d={d} onDone={refresh} />
                </Td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <Td colSpan={7} className="py-8 text-center opacity-70">{loading ? "Carregando..." : "Sem resultados."}</Td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs opacity-70">
        <div>
          Página {data.page} · {data.items.length} de {data.total}
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(pageSize)} onValueChange={(v: string) => { setPageSize(Number(v)); setPage(1); }}>
            <SelectTrigger className="w-[100px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[10,20,50,100].map(n => <SelectItem key={n} value={String(n)}>{n}/página</SelectItem>)}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setPage(Math.max(1, page - 1))}>Anterior</Button>
            <Button variant="outline" size="sm" onClick={() => setPage(page + 1)}>Próxima</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// --------- Fallback de detalhes + overlay CSV ----------
async function enrichDetailFallback(id: string, base: DeviceDetail | null): Promise<DeviceDetail> {
  const paths = [
    // TR-098
    "InternetGatewayDevice.DeviceInfo.Manufacturer",
    "InternetGatewayDevice.DeviceInfo.ProductClass",
    "InternetGatewayDevice.DeviceInfo.SoftwareVersion",
    "InternetGatewayDevice.ManagementServer.ConnectionRequestURL",
    "InternetGatewayDevice.ManagementServer.STUNEnable",
    "InternetGatewayDevice.ManagementServer.PeriodicInformInterval",
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress",
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress",
    "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPInterface.1.IPInterfaceIPAddress",
    "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPAddress",
    // TR-181
    "Device.DeviceInfo.Manufacturer",
    "Device.DeviceInfo.ProductClass",
    "Device.DeviceInfo.ModelName",
    "Device.DeviceInfo.SoftwareVersion",
    "Device.ManagementServer.ConnectionRequestURL",
    "Device.ManagementServer.STUNEnable",
    "Device.ManagementServer.PeriodicInformInterval",
    // GenieACS DeviceID (o que você quer)
    "DeviceID.ProductClass",
  ];
  const res = await deviceGetParameters(id, paths);
  const v = res.values || {};

  const wan = (v["InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress"] ||
               v["InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1.ExternalIPAddress"]) || null;

  const lan = (v["InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPInterface.1.IPInterfaceIPAddress"] ||
               v["InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.IPAddress"]) || null;

  const productClass =
      v["DeviceID.ProductClass"] ||
      v["InternetGatewayDevice.DeviceInfo.ProductClass"] ||
      v["Device.DeviceInfo.ProductClass"] ||
      v["Device.DeviceInfo.ModelName"] ||
      base?.product_class;

  const out: DeviceDetail = {
    device_id: base?.device_id || id,
    serial_number: base?.serial_number || id,
    vendor: base?.vendor
      ?? v["InternetGatewayDevice.DeviceInfo.Manufacturer"]
      ?? v["Device.DeviceInfo.Manufacturer"]
      ?? undefined,
    product_class: productClass || undefined,
    software_version: base?.software_version
      ?? v["InternetGatewayDevice.DeviceInfo.SoftwareVersion"]
      ?? v["Device.DeviceInfo.SoftwareVersion"]
      ?? undefined,
    last_inform: base?.last_inform ?? undefined,
    tags: base?.tags ?? [],
    subscriber: base?.subscriber ?? undefined,
    ip: {
      wan_ipv4: base?.ip?.wan_ipv4 ?? (typeof wan === "string" && wan.length ? wan : null),
      lan_ipv4: base?.ip?.lan_ipv4 ?? (typeof lan === "string" && lan.length ? lan : null),
    },
    wifi: {
      ssid_24: base?.wifi?.ssid_24 ?? null,
      ssid_5:  base?.wifi?.ssid_5  ?? null,
    },
    mgmt: {
      conn_req_url: base?.mgmt?.conn_req_url
        ?? (v["InternetGatewayDevice.ManagementServer.ConnectionRequestURL"] ?? null)
        ?? (v["Device.ManagementServer.ConnectionRequestURL"] ?? null),
      stun_enable: base?.mgmt?.stun_enable
        ?? Boolean(v["InternetGatewayDevice.ManagementServer.STUNEnable"])
        ?? Boolean(v["Device.ManagementServer.STUNEnable"]),
      periodic_inform_interval: base?.mgmt?.periodic_inform_interval
        ?? (typeof v["InternetGatewayDevice.ManagementServer.PeriodicInformInterval"] === "number"
              ? v["InternetGatewayDevice.ManagementServer.PeriodicInformInterval"]
              : (v["InternetGatewayDevice.ManagementServer.PeriodicInformInterval"]
                  ? Number(v["InternetGatewayDevice.ManagementServer.PeriodicInformInterval"])
                  : null))
        ?? (typeof v["Device.ManagementServer.PeriodicInformInterval"] === "number"
              ? v["Device.ManagementServer.PeriodicInformInterval"]
              : (v["Device.ManagementServer.PeriodicInformInterval"]
                  ? Number(v["Device.ManagementServer.PeriodicInformInterval"]) : null)),
    },
  };

  // Overlay CSV (se existir)
  try {
    const ov = await getOverlayFor(id);
    if (ov) {
      out.product_class = out.product_class || ov.model || out.product_class;
      out.wifi = {
        ssid_24: out.wifi?.ssid_24 || ov.ssid_24 || null,
        ssid_5:  out.wifi?.ssid_5  || ov.ssid_5  || null,
      };
    }
  } catch {}

  return out;
}

function DeviceActions({ d, onDone }: { d: Device; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<DeviceDetail | null>(null);

  const [ssid24, setSsid24] = useState("");
  const [ssid5, setSsid5] = useState("");
  const [pass24, setPass24] = useState("");
  const [pass5, setPass5] = useState("");
  const [ssidLoading, setSsidLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSsidLoading(true);

    getDeviceDetail(d.id)
      .then(async (base) => {
        const enriched = await enrichDetailFallback(d.id, base);

        // SSIDs por leitura direta dos paths (cobre seu caso WLANConfiguration.3.SSID)
        const direct = await fetchSSIDsDirect(d.id);
        enriched.wifi = {
          ssid_24: enriched.wifi?.ssid_24 ?? (direct.s24 || null),
          ssid_5:  enriched.wifi?.ssid_5  ?? (direct.s5  || null),
        };

        setDetail(enriched);
        setSsid24(enriched.wifi?.ssid_24 || "");
        setSsid5(enriched.wifi?.ssid_5 || "");
      })
      .catch(async () => {
        const enriched = await enrichDetailFallback(d.id, null);
        const direct = await fetchSSIDsDirect(d.id);
        enriched.wifi = { ssid_24: direct.s24 || null, ssid_5: direct.s5 || null };
        setDetail(enriched);
        setSsid24(enriched.wifi?.ssid_24 || "");
        setSsid5(enriched.wifi?.ssid_5 || "");
      })
      .finally(() => setSsidLoading(false));
  }, [open, d.id]);

  async function doConnReq() { await deviceConnReq(d.id); }
  async function doReboot() { await deviceReboot(d.id); }
  async function doFactory() { await deviceFactoryReset(d.id); }

  async function doWifi24() {
    if (!ssid24 || !pass24) return;
    await taskWifi24(d.id, ssid24, pass24);
    onDone();
  }
  async function doWifi5() {
    if (!ssid5 || !pass5) return;
    await taskWifi5(d.id, ssid5, pass5);
    onDone();
  }
  async function doWifiDual() {
    if (!ssid24 || !ssid5 || !pass24 || !pass5) return;
    await taskWifiDual(d.id, ssid24, pass24, ssid5, pass5);
    onDone();
  }

  return (
    <div className="flex gap-2 justify-end">
      <Button variant="outline" size="sm" onClick={doConnReq}>ConnReq</Button>
      <Button variant="outline" size="sm" onClick={doReboot}>Reiniciar</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button size="sm" className="bg-gradient-to-r from-blue-600 to-emerald-500 text-white">Detalhes</Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Dispositivo · {d.serialNumber}</DialogTitle>
          </DialogHeader>
          <Tabs defaultValue="overview" className="mt-2">
            <TabsList className="grid grid-cols-3 w-full">
              <TabsTrigger value="overview">Visão</TabsTrigger>
              <TabsTrigger value="wifi">Wi-Fi</TabsTrigger>
              <TabsTrigger value="pppoe">PPPoE</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="space-y-3">
              <div className="text-sm grid grid-cols-2 gap-2">
                <Info label="Vendor" value={detail?.vendor || "—"} />
                <Info label="Modelo" value={detail?.product_class || d.model} />
                <Info label="Firmware" value={detail?.software_version || "—"} />
                <Info label="IP WAN" value={detail?.ip?.wan_ipv4 || d.ip || "—"} mono />
                <Info label="IP LAN" value={detail?.ip?.lan_ipv4 || "—"} mono />
                <Info label="SSID 2.4G" value={detail?.wifi?.ssid_24 || ssid24 || "—"} />
                <Info label="SSID 5G" value={detail?.wifi?.ssid_5 || ssid5 || "—"} />
                <Info label="ConnReq URL" value={detail?.mgmt?.conn_req_url || "—"} mono />
                <Info label="STUN" value={detail?.mgmt?.stun_enable ? "Ativo" : "—"} />
                <Info label="Inform (s)" value={detail?.mgmt?.periodic_inform_interval ?? "—"} />
                <Info label="Últ. inform" value={formatRelative(detail?.last_inform || d.lastInform)} />
                <Info label="Assinante" value={detail?.subscriber ?? d.subscriber ?? "—"} />
              </div>
              <ParametersQuickRead id={d.id} />
              <div className="flex gap-2 pt-1">
                <Button variant="outline" onClick={doConnReq}>Connection Request</Button>
                <Button variant="outline" onClick={doReboot}>Reboot</Button>
                <Button variant="outline" className="text-rose-400" onClick={doFactory}>Factory reset</Button>
              </div>
            </TabsContent>

            <TabsContent value="wifi" className="space-y-3">
              <div className="text-sm">{ssidLoading ? "Lendo SSIDs…" : "Trocar SSID e Senha (2.4G / 5G)"}</div>

              <div className="space-y-2">
                {/* 2.4G */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <Input placeholder="SSID 2.4G" value={ssid24} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSsid24(e.target.value)} />
                  <Input placeholder="Senha 2.4G" type="password" value={pass24} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPass24(e.target.value)} />
                  <Button onClick={doWifi24} disabled={!ssid24 || !pass24}>Aplicar 2.4G</Button>
                </div>

                {/* 5G */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <Input placeholder="SSID 5G" value={ssid5} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSsid5(e.target.value)} />
                  <Input placeholder="Senha 5G" type="password" value={pass5} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPass5(e.target.value)} />
                  <Button onClick={doWifi5} disabled={!ssid5 || !pass5}>Aplicar 5G</Button>
                </div>

                {/* Dual */}
                <div className="flex items-center gap-2">
                  <Button onClick={doWifiDual} disabled={!ssid24 || !ssid5 || !pass24 || !pass5}>Aplicar Dual</Button>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="pppoe" className="space-y-3">
              <PPPoEForm id={d.id} onDone={onDone} />
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value: any; mono?: boolean }) {
  return (
    <div>
      <div className="text-[11px] uppercase opacity-60">{label}</div>
      <div className={`${mono ? "font-mono" : ""}`}>{String(value)}</div>
    </div>
  );
}

function ParametersQuickRead({ id }: { id: string }) {
  const [paths, setPaths] = useState<string>("InternetGatewayDevice.DeviceInfo.ProductClass,InternetGatewayDevice.DeviceInfo.SoftwareVersion");
  const [values, setValues] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(false);

  async function fetchParams() {
    setLoading(true);
    try {
      const res = await deviceGetParameters(
        id,
        paths
          .split(/[\,\n]/)
          .map((s) => s.trim())
          .filter(Boolean)
      );
      setValues(res.values);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="border rounded-xl p-3 border-slate-800">
      <div className="text-sm font-medium mb-2">Leitura rápida de parâmetros</div>
      <div className="flex gap-2">
        <Input value={paths} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPaths(e.target.value)} />
        <Button onClick={fetchParams} disabled={loading}>{loading ? "Lendo…" : "Ler"}</Button>
      </div>
      {values && (
        <div className="mt-2 text-xs bg-slate-950/60 rounded p-2 font-mono whitespace-pre-wrap">
          {Object.entries(values)
            .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
            .join("\n")}
        </div>
      )}
    </div>
  );
}

function PPPoEForm({ id, onDone }: { id: string; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [enable, setEnable] = useState(true);

  async function apply() {
    await deviceSetPPPoE(id, { username, password, enable });
    onDone();
  }
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Input placeholder="Usuário PPPoE" value={username} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setUsername(e.target.value)} />
        <Input placeholder="Senha PPPoE" type="password" value={password} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)} />
      </div>
      <div className="flex items-center gap-2">
        <label className="text-sm opacity-80">Habilitar interface PPPoE</label>
        <input type="checkbox" checked={enable} onChange={(e) => setEnable(e.target.checked)} />
      </div>
      <Button onClick={apply}>Aplicar</Button>
    </div>
  );
}

function ComingSoon({ what }: { what: string }) {
  return (
    <div className="h-[60vh] grid place-items-center">
      <div className="max-w-md text-center space-y-3">
        <div className="h-14 w-14 rounded-2xl bg-gradient-to-br from-blue-600 to-emerald-500 grid place-items-center text-white mx-auto">
          <Activity className="h-6 w-6" />
        </div>
        <div className="text-xl font-semibold">{what}</div>
        <p className="opacity-70 text-sm">
          Seção em construção. Ideal para gerenciar perfis, presets, tarefas e alertas do GenieACS.
        </p>
        <div className="text-xs opacity-60">Dica: conecte aqui listas do REST API do GenieACS.</div>
      </div>
    </div>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`px-4 py-3 text-[11px] font-semibold tracking-wide uppercase text-slate-400 ${className}`}>
      {children}
    </th>
  );
}
function Td({ children, className = "", colSpan }: { children: React.ReactNode; className?: string; colSpan?: number }) {
  return <td colSpan={colSpan} className={`px-4 py-3 ${className}`}>{children}</td>;
}

// =====================================================================
// DEV SANITY TESTS (dev only)
// =====================================================================
if (typeof window !== "undefined" && (import.meta as any).env?.MODE !== "production") {
  (function runDevTests() {
    try {
      console.assert(typeof deviceFactoryReset === "function", "deviceFactoryReset deve ser função");
      const now = new Date().toISOString();
      const fr = formatRelative(now);
      console.assert(typeof fr === "string" && fr.length > 0, "formatRelative deve retornar string");
      const sample = "A,B\nC";
      const arr = sample.split(/[\,\n]/).map((s) => s.trim()).filter(Boolean);
      console.assert(arr.length === 3 && arr[0] === "A" && arr[1] === "B" && arr[2] === "C", "split de paths deve funcionar");
      const keys = ["online","offline","provisioning","error"];
      console.assert(keys.every(k => k in (statusColor as any)), "statusColor deve mapear todos os status");
      const u = new URL(`/devices/test/factory_reset`, window.location.origin).toString();
      console.assert(typeof u === "string" && u.includes("/factory_reset"), "URL factory_reset formada");
      console.debug("[DEV TESTS] OK");
    } catch (e) {
      console.error("[DEV TESTS] Falhou:", e);
    }
  })();
}
