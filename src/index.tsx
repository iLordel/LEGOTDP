// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk
// https://github.com/Rayekkk/LeGoTDP

import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  toaster,
  useQuickAccessVisible,
} from "@decky/api";
import {
  ButtonItem,
  DialogButton,
  GamepadButton,
  type GamepadEvent as DeckyGamepadEvent,
  DropdownItem,
  Field,
  findModuleExport,
  Focusable,
  PanelSection,
  PanelSectionRow,
  Router,
  SliderField,
  Spinner,
  staticClasses,
  ToggleField,
} from "@decky/ui";
import { FC, useCallback, useEffect, useRef, useState } from "react";

import {
  detectLang,
  isLang,
  Key as StringKey,
  Lang,
  LANG_NAMES,
  LANGS,
  translate,
} from "./i18n";

// ── Language ───────────────────────────────────────────────────────────────────

/**
 * The chosen language, held outside React.
 *
 * Three components need it and they are siblings, not a tree - the alternative
 * was threading a prop through every one of them, or a context provider whose
 * only job would be to hold two letters. Components subscribe through useLang()
 * and re-render when it changes.
 */
class LanguageStore {
  private static lang: Lang = detectLang();
  private static subscribers: Array<() => void> = [];

  static get(): Lang {
    return this.lang;
  }

  static set(lang: Lang) {
    if (lang === this.lang) return;
    this.lang = lang;
    this.subscribers.forEach((fn) => fn());
  }

  static listen(fn: () => void): () => void {
    this.subscribers.push(fn);
    return () => {
      this.subscribers = this.subscribers.filter((f) => f !== fn);
    };
  }
}

type T = (key: StringKey, params?: Record<string, string | number>) => string;

/**
 * Render a backend-supplied {key, params} pair.
 *
 * The backend has no idea which language the panel is in, so it names the
 * string instead of writing it. An unknown key falls back to itself rather
 * than to an empty label, which makes a missing translation visible instead
 * of invisible.
 */
const localise = (t: T, item: Localised): string =>
  t(item.key as StringKey, item.params);

/** Current language plus a translator bound to it. */
function useLang(): [Lang, T] {
  const [lang, setLang] = useState<Lang>(LanguageStore.get());
  useEffect(() => LanguageStore.listen(() => setLang(LanguageStore.get())), []);
  return [lang, (key, params) => translate(lang, key, params)];
}

// ── Helpers ────────────────────────────────────────────────────────────────────
const toMw  = (w: number)  => w * 1000;
const toW   = (mw: number) => Math.round(mw / 1000);
const fmt   = (v?: number) => v != null ? `${v.toFixed(1)} W` : "-";
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

// ── Tuning model ───────────────────────────────────────────────────────────────
// SPL is the actual TDP dial. SPPT and FPPT are expressed as headroom *above* SPL
// rather than absolute watts, so raising the TDP carries the burst limits with it.
interface Tuning { spl: number; spptOff: number; fpptOff: number }
interface Caps   { spl: number; sppt: number; fppt: number }

const OFFSET_MAX = { sppt: 10, fppt: 15 };

// Used only until get_caps() answers, which it does within a second of the panel
// opening. The backend is the source of truth: it reports what the firmware
// itself publishes, and falls back to the same Legion Go 1 numbers below when
// the firmware has no range to publish (the acpi_call path).
const FALLBACK_STD: Caps = { spl: 30, sppt: 32, fppt: 41 };
const FALLBACK_MAX: Caps = { spl: 40, sppt: 43, fppt: 50 };
const FALLBACK_MIN = 5;

/** Headroom still available above the current SPL, per parameter. */
const offsetMax = (spl: number, caps: Caps) => ({
  sppt: Math.max(0, Math.min(OFFSET_MAX.sppt, caps.sppt - spl)),
  fppt: Math.max(0, Math.min(OFFSET_MAX.fppt, caps.fppt - spl)),
});

/** Force a tuning back inside the ceilings, keeping SPPT <= FPPT. */
function normalise(t: Tuning, caps: Caps, minW: number): Tuning {
  const spl = clamp(t.spl, minW, caps.spl);
  const max = offsetMax(spl, caps);
  const spptOff = clamp(t.spptOff, 0, max.sppt);
  const fpptOff = Math.max(clamp(t.fpptOff, 0, max.fppt), spptOff);
  return { spl, spptOff, fpptOff };
}

const absolute = (t: Tuning) => ({
  spl: t.spl, sppt: t.spl + t.spptOff, fppt: t.spl + t.fpptOff,
});

const fromAbsolute = (spl: number, sppt: number, fppt: number): Tuning => ({
  spl, spptOff: Math.max(0, sppt - spl), fpptOff: Math.max(0, fppt - spl),
});

/** Slider handlers implementing the coupling rules between the three limits. */
function makeTuningHandlers(t: Tuning, set: (next: Tuning) => void, caps: Caps, minW: number) {
  return {
    // Moving SPL re-clamps both offsets: at the ceiling there is no headroom left.
    onSpl: (v: number) => set(normalise({ ...t, spl: v }, caps, minW)),
    onSppt: (v: number) => {
      const spptOff = clamp(v, 0, offsetMax(t.spl, caps).sppt);
      // Pushing SPPT up drags FPPT along so SPPT never overtakes it.
      set({ ...t, spptOff, fpptOff: Math.max(t.fpptOff, spptOff) });
    },
    onFppt: (v: number) => {
      const fpptOff = clamp(v, 0, offsetMax(t.spl, caps).fppt);
      // Pulling FPPT below SPPT drags SPPT down to meet it.
      set({ ...t, fpptOff, spptOff: Math.min(t.spptOff, fpptOff) });
    },
  };
}

// ── Presets ────────────────────────────────────────────────────────────────────
type PresetKey = "minimum" | "silent" | "balanced" | "performance" | "max" | "custom";

type PresetTable = Record<Exclude<PresetKey, "custom">,
                          { spl: number; sppt: number; fppt: number }>;

// Used until get_caps() answers with the ladder for this machine. The backend
// is the source of truth, because it is the side that knows the hardware.
const PRESETS: PresetTable = {
  minimum:     { spl: 5,  sppt: 7,  fppt: 10 },
  silent:      { spl: 8,  sppt: 10, fppt: 14 },
  balanced:    { spl: 15, sppt: 17, fppt: 22 },
  performance: { spl: 20, sppt: 22, fppt: 28 },
  max:         { spl: 30, sppt: 32, fppt: 41 },
};

const PRESET_KEYS: Record<PresetKey, StringKey> = {
  minimum:     "preset.minimum",
  silent:      "preset.silent",
  balanced:    "preset.balanced",
  performance: "preset.performance",
  max:         "preset.max",
  custom:      "preset.custom",
};

const PRESET_ORDER: PresetKey[] = ["minimum", "silent", "balanced", "performance", "max", "custom"];

function detectPreset(spl: number, sppt: number, fppt: number,
                      table: PresetTable = PRESETS): PresetKey {
  for (const key of Object.keys(table) as Exclude<PresetKey, "custom">[]) {
    const v = table[key];
    if (v.spl === spl && v.sppt === sppt && v.fppt === fppt) return key;
  }
  return "custom";
}

function profileLabel(t: T, spl: number, sppt: number, fppt: number, stored?: string,
                      table: PresetTable = PRESETS): string {
  const customLabel = t("preset.customValue",
    { spl, sppt: sppt - spl, fppt: fppt - spl });
  if (stored !== undefined) {
    if (stored === "custom" || stored === "") return customLabel;
    const key = PRESET_KEYS[stored as PresetKey];
    return key ? t(key) : stored;
  }
  const key = detectPreset(spl, sppt, fppt, table);
  return key === "custom" ? customLabel : t(PRESET_KEYS[key]);
}

const exceedsCaps = (spl: number, sppt: number, fppt: number, caps: Caps) =>
  spl > caps.spl || sppt > caps.sppt || fppt > caps.fppt;

function statusStyle(isError: boolean) {
  return isError ? styles.errorBox : { fontSize: "12px", color: OK_COLOR };
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface Settings {
  spl: number; sppt: number; fppt: number;
  enabled: boolean;
  active_preset?: string;
  // The global charger profile. Same shape as a per-game one, because it is
  // the same idea one level up: with the switch off there is a single set of
  // numbers, with it on the charger decides which set runs.
  ac_separate?: boolean;
  ac_spl?: number; ac_sppt?: number; ac_fppt?: number;
  ac_preset?: string;
  language?: string;
}
interface TdpResult  { success: boolean; stderr?: string; skipped?: boolean; returncode?: number }
interface TdpValues  {
  spl_limit?:  number;
  sppt_limit?: number;
  fppt_limit?: number;
  package_draw?: number;
  cpu_temp?: number;
  fan_rpm?: number[];
  source?: string;
}

/** Text the backend wants shown: a key from i18n plus its placeholders. */
interface Localised { key: string; params?: Record<string, string | number> }

interface MakoRelease {
  available: boolean;
  plugin_name?: string;
  version?: string;
  asset?: string;
  url?: string;
  size?: number;
  error?: string;
}

interface Enhancer {
  key: string;
  name: string;
  installed: boolean;
  path: string;
  note: string;
  url: string;
}

interface FanState {
  supported: boolean;
  mode: string;
  curve: number[];
  full_speed: boolean;
}
interface TdpInfo     { success: boolean; values: TdpValues; error?: string }
interface PowerSource { ac: boolean }
interface GameProfile {
  exists: boolean;
  profile: { spl: number; sppt: number; fppt: number; preset?: string };
  ac_separate: boolean;
  ac_profile: { spl: number; sppt: number; fppt: number; ac_preset?: string };
}
interface CapsInfo {
  min: number;
  mins?: Caps;
  std: Caps;
  max: Caps;
  wmi: boolean;
  extras?: boolean;
  presets?: PresetTable;
  backend?: string;
  device?: { key: string; label: string; short: string };
  conflicts?: Localised[];
}

interface BackendReport {
  supported: boolean;
  available: boolean;
  detail_key: string;
  detail_params?: Record<string, string | number>;
}

interface ChargeLimit {
  supported: boolean;
  enabled: boolean;
  threshold: number | null;
  source: string;
  path: string;
}

interface Diagnostics {
  device: string;
  device_key: string;
  dmi: Record<string, string>;
  bios: { raw: string; number: number; baseline: number; status: string };
  cpu: string;
  kernel: string;
  backend: string;
  last_source: string;
  backends: Record<string, BackendReport>;
  ranges: Record<string, { min: number; max: number; source: string }>;
  current: { spl?: number; sppt?: number; fppt?: number; package_draw?: number };
  platform_profile: { path: string; current: string; choices: string[] };
  firmware_mode: string;
  charge_limit: ChargeLimit;
  fans: FanState;
  temperature: number | null;
  ryzenadj: { available: boolean; path: string; verified: boolean };
  conflicts: Localised[];
  notes: string[];
  version: string;
}
interface RunningGame { appId: string; name: string }

interface UpdateInfo {
  current_version?: string;
  latest_version?: string;
  update_available?: boolean;
  download_url?: string;
  asset_name?: string;
  error?: string;
}
interface ReadyState  { ready: boolean; error: string }
// ── Backend callables ──────────────────────────────────────────────────────────
const isReady           = callable<[], ReadyState>("is_ready");
const getSettings       = callable<[], Settings>("get_settings");
const getCaps           = callable<[], CapsInfo>("get_caps");
const applyTdp          = callable<[number, number, number, string, string, string | null, string], TdpResult>("apply_tdp");
const getTdpInfo        = callable<[], TdpInfo>("get_tdp_info");
const getGameProfile    = callable<[string], GameProfile>("get_game_profile");
const deleteGameProfile = callable<[string], TdpResult>("delete_game_profile");
const setPluginEnabled  = callable<[boolean], TdpResult>("set_plugin_enabled");
const setPanelActive    = callable<[boolean], void>("set_panel_active");
const setActiveApp      = callable<[string], void>("set_active_app");
const getPowerSource    = callable<[], PowerSource>("get_power_source");
const reapply           = callable<[], TdpResult>("reapply");
const setGameAcProfile  = callable<[string, number, number, number, boolean, string], TdpResult>("set_game_ac_profile");
const getDiagnostics    = callable<[], Diagnostics>("get_diagnostics");
const setGlobalAcSeparate = callable<[boolean], TdpResult>("set_global_ac_separate");
const setLanguageCall   = callable<[string], TdpResult>("set_language");
const getVersion        = callable<[], { version: string }>("get_version");
const checkForUpdates   = callable<[], UpdateInfo>("check_for_updates");
const performUpdate     = callable<[], { success: boolean; path?: string; error?: string }>("perform_update");
const getEnhancers      = callable<[], { enhancers: Enhancer[] }>("get_enhancers");
const getMakoRelease    = callable<[], MakoRelease>("get_mako_release");
const getFanState       = callable<[], FanState>("get_fan_state");
const setFanModeCall    = callable<[string], TdpResult>("set_fan_mode");
const getChargeLimit    = callable<[], ChargeLimit>("get_charge_limit");
const setChargeLimitCall = callable<[boolean], TdpResult>("set_charge_limit");
const getExtrasUnlocked = callable<[], boolean>("get_extras_unlocked");
const setExtrasUnlockedCall = callable<[boolean], TdpResult>("set_extras_unlocked");

// ── Toasts ─────────────────────────────────────────────────────────────────────

const notify = (title: string, body: string) => {
  try {
    toaster.toast({ title, body, duration: 4000 });
  } catch {
    console.error(`[ltdp] ${title}: ${body}`);
  }
};

const notifyFailure = (title: string, err: unknown) => {
  const body = err instanceof Error ? err.message : String(err ?? "Unknown error");
  console.error(`[ltdp] ${title}`, err);
  notify(title, body);
};

// ── Styles - Steam theme variables with hardcoded fallbacks ────────────────────

const OK_COLOR = "var(--gpColor-Green, #4ade80)";
const BAD_COLOR = "var(--gpColor-Red, #f87171)";
const WARN_COLOR = "var(--gpColor-Yellow, #fbbf24)";
const DIM_COLOR = "var(--gpColor-TextMuted, rgba(255,255,255,0.5))";

const styles = {
  valueTag: {
    fontSize: "13px",
    fontWeight: "bold",
    color: "var(--gpColor-White, #fff)",
    background: "rgba(255,255,255,0.1)",
    borderRadius: "4px",
    padding: "1px 6px",
    fontFamily: "monospace",
  },
  profileTag: {
    fontSize: "11px",
    fontWeight: "bold",
    color: "var(--gpColor-White, #fff)",
    background: "rgba(74,222,128,0.25)",
    border: "1px solid rgba(74,222,128,0.5)",
    borderRadius: "3px",
    padding: "0px 5px",
    fontFamily: "monospace",
  },
  infoBox: {
    background: "rgba(251,191,36,0.15)",
    border: "1px solid rgba(251,191,36,0.4)",
    borderRadius: "6px",
    padding: "8px 10px",
    fontSize: "11px",
    color: WARN_COLOR,
    lineHeight: "1.5",
    marginTop: "4px",
  },
  errorBox: {
    background: "rgba(248,113,113,0.1)",
    border: "1px solid rgba(248,113,113,0.4)",
    borderRadius: "6px",
    padding: "8px 10px",
    fontSize: "11px",
    color: BAD_COLOR,
    lineHeight: "1.5",
    marginTop: "4px",
  },

  // -- status card ----------------------------------------------------------
  card: {
    width: "100%",
    boxSizing: "border-box" as const,
    background: "linear-gradient(135deg, rgba(255,255,255,0.09), rgba(255,255,255,0.03))",
    border: "1px solid rgba(255,255,255,0.12)",
    borderRadius: "10px",
    padding: "10px 12px 12px",
  },
  cardHead: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    gap: "8px",
    marginBottom: "6px",
  },
  cardDevice: {
    fontSize: "11px",
    fontWeight: "bold" as const,
    letterSpacing: "0.06em",
    textTransform: "uppercase" as const,
    color: "var(--gpColor-White, #fff)",
    opacity: 0.85,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap" as const,
  },
  cardBackend: {
    fontSize: "10px",
    fontFamily: "monospace",
    color: DIM_COLOR,
    whiteSpace: "nowrap" as const,
  },
  cardNumbers: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-end",
    gap: "8px",
  },
  cardBig: {
    fontSize: "26px",
    lineHeight: "1.1",
    fontWeight: "bold" as const,
    fontFamily: "monospace",
    color: "var(--gpColor-White, #fff)",
  },
  cardCaption: {
    fontSize: "10px",
    color: DIM_COLOR,
    textTransform: "uppercase" as const,
    letterSpacing: "0.04em",
  },
  gaugeTrack: {
    marginTop: "8px",
    height: "5px",
    width: "100%",
    borderRadius: "3px",
    background: "rgba(255,255,255,0.12)",
    overflow: "hidden",
  },
  gaugeFill: {
    height: "100%",
    borderRadius: "3px",
    background: `linear-gradient(90deg, ${OK_COLOR}, ${WARN_COLOR})`,
    transition: "width 220ms ease-out",
  },

  // -- preset grid ----------------------------------------------------------
  presetGrid: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: "6px",
    width: "100%",
  },
  presetButton: {
    flex: "1 1 calc(50% - 6px)",
    minWidth: "calc(50% - 6px)",
    padding: "8px 4px",
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    gap: "2px",
    lineHeight: "1.1",
  },
  presetName: { fontSize: "13px", fontWeight: "bold" as const },
  presetWatts: { fontSize: "10px", fontFamily: "monospace", opacity: 0.7 },

  // -- segmented control (battery/AC, language) -----------------------------
  segmentRow: {
    display: "flex",
    gap: "6px",
    width: "100%",
  },
  segment: {
    flex: "1 1 0",
    padding: "7px 4px",
    fontSize: "12px",
  },

  // -- footer ---------------------------------------------------------------
  footer: {
    textAlign: "center" as const,
    padding: "10px 0 4px",
    fontSize: "11px",
    color: DIM_COLOR,
    letterSpacing: "0.18em",
    textTransform: "uppercase" as const,
  },
  footerName: {
    color: "var(--gpColor-White, #fff)",
    fontWeight: "bold" as const,
    opacity: 0.8,
  },
};

/** Accent applied to whichever button in a group is the active one. */
const activeStyle = {
  background: "rgba(74,222,128,0.22)",
  boxShadow: "inset 0 0 0 1px rgba(74,222,128,0.55)",
};

// ── Resume from suspend ────────────────────────────────────────────────────────

/**
 * Subscribe to resume-from-suspend. Returns an unsubscribe function, or null
 * when the client offers no way to hear about it.
 *
 * `SteamClient.System.RegisterForOnResumeFromSuspend` was removed from the
 * Steam client in the September 2025 beta. Optional chaining meant calling it
 * silently did nothing - confirmed on the device, where two suspend cycles
 * produced no callback and no error, and the limits only came back five
 * seconds later when the enforce loop noticed. The replacement lives on a
 * SleepManager module, reachable either as a global or through the webpack
 * exports; the legacy call stays as a fallback for older clients.
 */
function onResumeFromSuspend(handler: () => void): (() => void) | null {
  const asUnsub = (reg: any): (() => void) | null => {
    if (typeof reg === "function") return reg;
    if (typeof reg?.unregister === "function") return () => reg.unregister();
    return null;
  };
  const isSleepManager = (e: any) =>
    !!e && typeof e === "object" &&
    (typeof e.RegisterForNotifyResumeFromSuspend === "function" ||
      typeof e.NotifyResumeFromSuspend === "function");

  try {
    const mgr = (window as any).SleepManager ?? findModuleExport(isSleepManager);
    const unsub = asUnsub(mgr?.RegisterForNotifyResumeFromSuspend?.(handler));
    if (unsub) return unsub;
  } catch (e) {
    console.warn("[ltdp] SleepManager lookup failed", e);
  }

  try {
    const unsub = asUnsub(
      (window as any).SteamClient?.System?.RegisterForOnResumeFromSuspend?.(handler));
    if (unsub) return unsub;
  } catch (e) {
    console.warn("[ltdp] legacy resume registration failed", e);
  }

  // Said out loud rather than swallowed: this going quiet again is exactly how
  // the previous registration rotted unnoticed.
  console.warn("[ltdp] no resume-from-suspend notification available; "
    + "limits will be restored by the enforce loop instead");
  return null;
}

// ── Running app watcher ────────────────────────────────────────────────────────

type GameListener = (game: RunningGame | null) => void;

// The backend trusts a frontend-reported appid for 12 seconds. Refresh at half
// that, so one dropped call is not enough to make it fall back to the /proc scan.
const PUSH_INTERVAL_MS = 6000;

/**
 * Tracks the foreground game and tells the backend about it, so the backend's
 * enforce loop applies the right per-game profile even for titles its
 * /proc scan cannot see through pressure-vessel/gamescope.
 *
 * Started at plugin load rather than from the panel: the enforce loop runs
 * whether or not the Quick Access Menu is open, and it is exactly the
 * closed-panel case where the /proc fallback used to guess wrong.
 *
 * Unlike LeGo-Vibe-Control's copy, this pushes on every tick instead of only
 * on a change. The backend trusts a frontend-reported appid for 12 seconds and
 * falls back to the /proc scan once it goes stale, so the value has to be kept
 * fresh, not merely correct at the moment it last changed.
 */
class AppWatcher {
  private static listeners: GameListener[] = [];
  private static current: RunningGame | null = null;
  private static timer: ReturnType<typeof setInterval> | undefined;
  private static unsubs: Array<() => void> = [];
  private static started = false;
  private static busy = false;
  private static lastPush = 0;

  static activeGame(): RunningGame | null {
    try {
      const app = (Router as any)?.MainRunningApp;
      if (!app?.appid) return null;
      return { appId: String(app.appid), name: app.display_name ?? String(app.appid) };
    } catch {
      return null;
    }
  }

  static currentGame(): RunningGame | null {
    return this.current;
  }

  static listen(fn: GameListener): () => void {
    this.listeners.push(fn);
    return () => {
      this.listeners = this.listeners.filter((f) => f !== fn);
    };
  }

  static start() {
    if (this.started) return;
    this.started = true;
    this.current = this.activeGame();

    const steam = (window as any).SteamClient;

    try {
      const reg = steam?.GameSessions?.RegisterForAppLifetimeNotifications?.(() => {
        // Router.MainRunningApp lags the notification slightly.
        setTimeout(() => void this.check(), 300);
      });
      if (reg?.unregister) this.unsubs.push(() => reg.unregister());
    } catch (e) {
      console.warn("[ltdp] app lifetime notifications unavailable", e);
    }

    // The SMU comes back at firmware defaults after sleep. Decky has no backend
    // resume hook - the loader only calls _migration, _main, _unload and
    // _uninstall - so this notification is the only way to beat the enforce
    // loop's five-second tick to it.
    const offResume = onResumeFromSuspend(() => {
      void reapply()
        .then((res) => {
          if (!res.success) console.warn("[ltdp] reapply after resume failed", res.stderr);
        })
        .catch((e) => console.error("[ltdp] reapply after resume threw", e));
    });
    if (offResume) this.unsubs.push(offResume);

    this.timer = setInterval(() => void this.check(), 2000);
    void this.check();
  }

  static stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
    for (const off of this.unsubs) {
      try {
        off();
      } catch {
        /* the subscription may already be gone */
      }
    }
    this.unsubs = [];
    this.listeners = [];
    this.current = null;
    this.started = false;
    this.lastPush = 0;
  }

  private static async check() {
    if (this.busy) return;
    const game = this.activeGame();
    const changed = game?.appId !== this.current?.appId;
    this.current = game;

    // Tick often so a change is noticed quickly, but only send when there is
    // something to say or the backend's 12 s freshness window is running out.
    // This runs for the whole session, including mid-game with the panel shut.
    const now = Date.now();
    if (changed || now - this.lastPush >= PUSH_INTERVAL_MS) {
      this.busy = true;
      try {
        await setActiveApp(game?.appId ?? "");
        this.lastPush = now;
      } catch (e) {
        console.error("[ltdp] setActiveApp failed", e);
      } finally {
        this.busy = false;
      }
    }

    if (changed) this.listeners.forEach((fn) => fn(game));
  }
}

// ── Icon ───────────────────────────────────────────────────────────────────────
const ChipIcon: FC = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"
    style={{ width: "1em", height: "1em" }}>
    <path d="M9 2v2H7a2 2 0 0 0-2 2v2H3v2h2v2H3v2h2v2H3v2h2v2a2 2 0 0 0 2 2h2v2h2v-2h2v2h2v-2h2a2 2 0 0 0 2-2v-2h2v-2h-2v-2h2v-2h-2V9h2V7h-2V6a2 2 0 0 0-2-2h-2V2h-2v2h-2V2H9zm-1 4h12v12H8V6zm3 3v6h6V9h-6z" />
  </svg>
);

/** Green while there is headroom, amber as the firmware starts trimming TDP. */
const tempColor = (celsius: number) =>
  celsius >= 90 ? BAD_COLOR : celsius >= 80 ? WARN_COLOR : OK_COLOR;

type TabKey = "tdp" | "enhancers";

const TABS: TabKey[] = ["tdp", "enhancers"];

const TAB_KEYS: Record<TabKey, StringKey> = {
  tdp: "tab.tdp",
  enhancers: "tab.enhancers",
};

const FAN_MODES = ["auto", "quiet", "balanced", "cool", "max"] as const;

const FAN_MODE_KEYS: Record<string, StringKey> = {
  auto: "fan.auto",
  quiet: "fan.quiet",
  balanced: "fan.balanced",
  cool: "fan.cool",
  max: "fan.max",
};

const BACKEND_SHORT: Record<string, string> = {
  wmi: "Lenovo WMI",
  acpi: "acpi_call",
  ryzenadj: "ryzenadj",
};

const BACKEND_LABELS: Record<string, string> = {
  wmi: "Lenovo firmware attributes (kernel driver)",
  acpi: "Lenovo firmware via acpi_call",
  ryzenadj: "ryzenadj (SMU)",
  "": "none",
};

// ── Live TDP panel ─────────────────────────────────────────────────────────────

// Must stay comfortably under _PANEL_ACTIVE_TTL_S in main.py (90 s).
const PANEL_LEASE_MS = 30000;

/**
 * The two numbers that matter, side by side, with a bar between them.
 *
 * A limit and a measurement are different things and the old panel listed them
 * as two more rows of small print. Here the limit is the headline, the draw is
 * next to it, and the bar shows how much of the budget is actually in use.
 */
const StatusCard: FC<{ values: TdpValues; device: string; backend: string }> =
  ({ values, device, backend }) => {
  const [, t] = useLang();
  const limit = values.spl_limit ?? 0;
  const draw = values.package_draw ?? 0;
  const fill = limit > 0 ? Math.max(0, Math.min(1, draw / limit)) : 0;
  return (
    <div style={styles.card}>
      <div style={styles.cardHead}>
        <span style={styles.cardDevice}>{device}</span>
        <span style={styles.cardBackend}>
          {backend ? BACKEND_SHORT[backend] ?? backend : t("card.noBackend")}
        </span>
      </div>
      <div style={styles.cardNumbers}>
        <div>
          <div style={styles.cardBig}>{limit ? `${limit.toFixed(0)} W` : "-"}</div>
          <div style={styles.cardCaption}>{t("card.limit")}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ ...styles.cardBig, color: OK_COLOR }}>
            {values.package_draw != null ? `${draw.toFixed(1)} W` : "-"}
          </div>
          <div style={styles.cardCaption}>{t("card.now")}</div>
        </div>
        {values.cpu_temp != null && (
          <div style={{ textAlign: "right" }}>
            {/* The BIOS lowers TDP by itself when the SoC gets hot, so a limit
                that is not being reached is either that or something else
                moving the limits - and this is what tells them apart. */}
            <div style={{ ...styles.cardBig, color: tempColor(values.cpu_temp) }}>
              {`${values.cpu_temp.toFixed(0)}°`}
            </div>
            <div style={styles.cardCaption}>{t("card.temp")}</div>
          </div>
        )}
      </div>
      <div style={styles.gaugeTrack}>
        <div style={{ ...styles.gaugeFill, width: `${Math.round(fill * 100)}%` }} />
      </div>
    </div>
  );
};

const LivePanel: FC<{ device: string; backend: string }> = ({ device, backend }) => {
  const [info, setInfo] = useState<TdpInfo | null>(null);
  const [, t] = useLang();
  const visible = useQuickAccessVisible();

  // Gated on visibility, not just on mount: the panel stays mounted while the
  // Quick Access Menu is on another tab, and refreshing it there costs a RAPL
  // read every two seconds for nobody to look at. set_panel_active is what
  // gates the backend loop, so nothing is computed while this is unmounted.
  //
  // The backend pushes each refresh rather than answering a poll: it already
  // recomputed these numbers on exactly this cadence, so asking for them over
  // RPC was a round trip to be handed something that already existed.
  //
  // The lease is renewed rather than set once. The cleanup below drops it, but
  // it never runs if the frontend is torn down outright - a Steam UI restart -
  // and the backend would then keep refreshing forever. Thirty seconds against
  // the backend's ninety leaves room for two lost calls, and is still fifteen
  // times less traffic than the two-second poll this replaced.
  useEffect(() => {
    if (!visible) return;
    let active = true;
    setPanelActive(true);
    const lease = setInterval(() => setPanelActive(true), PANEL_LEASE_MS);
    const onInfo = (next: TdpInfo) => { if (active) setInfo(next); };
    addEventListener<[TdpInfo]>("tdp_info", onInfo);
    // Seed it: the first push is a full interval away, and the panel would
    // otherwise show a spinner for two seconds every time it is opened.
    getTdpInfo().then((v) => { if (active) setInfo(v); }).catch(() => undefined);
    return () => {
      active = false;
      clearInterval(lease);
      removeEventListener<[TdpInfo]>("tdp_info", onInfo);
      setPanelActive(false);
    };
  }, [visible]);

  const v = info?.values ?? {};
  return (
    <PanelSection title={t("live.title")}>
      {!info ? (
        <PanelSectionRow><Spinner /></PanelSectionRow>
      ) : !info.success ? (
        <PanelSectionRow>
          <Field label={t("panel.error")} description={info.error ?? t("live.readFailed")} />
        </PanelSectionRow>
      ) : (
        <>
          <PanelSectionRow>
            <StatusCard values={v} device={device} backend={v.source || backend} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("live.spl")}
              description={t("live.setTo", { value: fmt(v.spl_limit) })} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("live.sppt")}
              description={t("live.setTo", { value: fmt(v.sppt_limit) })} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("live.fppt")}
              description={t("live.setTo", { value: fmt(v.fppt_limit) })} />
          </PanelSectionRow>
          {/* A limit is what the SoC is allowed to draw; this is what it is
              drawing. They are different numbers and the panel says which is
              which - a 20 W limit reading 17.4 W is a machine behaving, not a
              setting that failed to apply. */}
          {v.cpu_temp != null && (
            <PanelSectionRow>
              <Field label={t("live.temp")}
                description={<span style={{ color: tempColor(v.cpu_temp) }}>
                  {`${v.cpu_temp.toFixed(1)} °C`}
                </span>} />
            </PanelSectionRow>
          )}
          {!!v.fan_rpm?.length && (
            <PanelSectionRow>
              <Field label={t("fan.speed")}
                description={v.fan_rpm.map((r) => t("fan.rpm", { value: r })).join("   ")} />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <Field
              label={t("live.draw")}
              description={`${fmt(v.package_draw)}${v.source
                ? `   -   ${t("live.appliedVia", { backend: BACKEND_LABELS[v.source] ?? v.source })}`
                : ""}`}
            />
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
};

// ── Enhancers ──────────────────────────────────────────────────────────────────

/**
 * What else on this machine changes how a game looks or how fast it runs.
 *
 * Read-only, deliberately. MAKO is a separate Decky plugin with its own backend
 * and a Vulkan layer of its own, under a different licence - one plugin cannot
 * render or drive another. Reporting what is present is the honest half, and it
 * is the half that matters next to a TDP limit: generated frames are what let
 * the limit come down.
 */
/**
 * Hand a plugin to Decky's own installer.
 *
 * `utilities/install_plugin` is what Decky's store calls: it does not install
 * anything by itself, it raises Decky's confirmation prompt and Decky does the
 * download and unpacking after the user agrees. That is the only way this
 * plugin will touch another one - unpacking a zip into somebody else's plugin
 * directory behind Decky's back would produce an install Decky does not know
 * about.
 *
 * It is an internal loader route, so it is reached defensively: if a future
 * Decky moves it, the panel says so and shows the address instead.
 */
async function requestPluginInstall(artifact: string, name: string, version: string) {
  const backend = (window as any)?.DeckyBackend;
  const install = backend?.callable?.("utilities/install_plugin");
  if (typeof install !== "function") return false;
  // hash empty: Decky skips the checksum when none is given, and the archive
  // comes straight from the project's own GitHub release over TLS.
  await install(artifact, name, version, "", 0);
  return true;
}

const EnhancersTab: FC = () => {
  const [items, setItems] = useState<Enhancer[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [, t] = useLang();

  const installMako = useCallback(async () => {
    setInstalling(true);
    try {
      const release = await getMakoRelease();
      if (!release.available || !release.url) {
        notify("LTDP", t("enhancer.releaseFailed",
          { message: release.error ?? t("status.unknownError") }));
        return;
      }
      const asked = await requestPluginInstall(
        release.url, release.plugin_name ?? "MAKO", release.version ?? "");
      if (!asked) notify("LTDP", t("enhancer.installUnavailable"));
    } catch (e) {
      notifyFailure("LTDP", e);
    } finally {
      setInstalling(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await getEnhancers()).enhancers ?? []);
    } catch (e) {
      notifyFailure("LTDP", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <PanelSection title={t("enhancer.title")}>
      <PanelSectionRow>
        <div style={{ fontSize: "11px", color: DIM_COLOR, lineHeight: "1.5" }}>
          {t("enhancer.intro")}
        </div>
      </PanelSectionRow>
      {items === null ? (
        <PanelSectionRow><Spinner /></PanelSectionRow>
      ) : (
        items.map((item) => (
          <PanelSectionRow key={item.key}>
            <Field
              label={item.name}
              description={
                <span>
                  <span style={{ color: item.installed ? OK_COLOR : DIM_COLOR,
                                 fontWeight: "bold" }}>
                    {item.installed ? t("enhancer.installed") : t("enhancer.missing")}
                  </span>
                  <br />
                  <span style={{ fontSize: "11px" }}>
                    {localise(t, { key: item.note })}
                  </span>
                  {item.installed && item.path && (
                    <>
                      <br />
                      <span style={{ fontSize: "10px", fontFamily: "monospace",
                                     color: DIM_COLOR, wordBreak: "break-all" }}>
                        {item.path}
                      </span>
                    </>
                  )}
                  {!item.installed && item.url && (
                    <>
                      <br />
                      <span style={{ fontSize: "10px", fontFamily: "monospace",
                                     color: DIM_COLOR, wordBreak: "break-all" }}>
                        {item.url}
                      </span>
                    </>
                  )}
                </span>
              }
            />
          </PanelSectionRow>
        ))
      )}
      {items?.some((i) => i.key === "mako" && !i.installed) && (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={installMako} disabled={installing}>
              {installing
                ? t("enhancer.installing")
                : t("enhancer.install", { name: "MAKO" })}
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", color: DIM_COLOR, lineHeight: "1.5" }}>
              {t("enhancer.installPrompt")}
            </div>
          </PanelSectionRow>
        </>
      )}
      <PanelSectionRow>
        <div style={styles.infoBox}>{t("enhancer.afterInstall")}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={styles.infoBox}>{t("enhancer.why")}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={load} disabled={loading}>
          {loading ? t("diag.reading") : t("enhancer.refresh")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};

// ── Updates ────────────────────────────────────────────────────────────────────

/**
 * Checks GitHub for a newer release and downloads it.
 *
 * Downloads, and stops there. This plugin runs as root; replacing its own code
 * over the network without the user pressing anything in Decky is not a power
 * it should hold, so the last step stays in the user's hands.
 */
const UpdateSection: FC = () => {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [path, setPath] = useState<string | null>(null);
  const [version, setVersion] = useState("");
  const [, t] = useLang();

  // Read from the manifest so the installed version is on screen before
  // anyone presses anything, rather than only after a network call.
  useEffect(() => {
    let active = true;
    getVersion()
      .then((v) => { if (active) setVersion(v.version ?? ""); })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const check = useCallback(async () => {
    setChecking(true);
    setInfo(null);
    setPath(null);
    try {
      setInfo(await checkForUpdates());
    } catch (e) {
      notifyFailure(t("update.failed"), e);
      setInfo({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      setChecking(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const download = useCallback(async () => {
    setDownloading(true);
    try {
      const res = await performUpdate();
      if (res.success && res.path) setPath(res.path);
      else {
        setInfo((current) => ({ ...(current ?? {}), error: res.error }));
        notify(t("update.downloadFailed"), res.error ?? t("status.unknownError"));
      }
    } catch (e) {
      notifyFailure(t("update.downloadFailed"), e);
    } finally {
      setDownloading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <PanelSection title={t("update.title")}>
      <PanelSectionRow>
        <div style={{ fontSize: "12px", color: DIM_COLOR }}>
          {t("update.installed")}:{" "}
          <span style={styles.valueTag}>v{info?.current_version ?? version ?? "?"}</span>
          {info?.latest_version && !info.error && (
            <span>
              {"  "}{t("update.latest")}:{" "}
              <span style={styles.valueTag}>v{info.latest_version}</span>
            </span>
          )}
        </div>
      </PanelSectionRow>
      {info?.error && (
        <PanelSectionRow>
          <div style={styles.errorBox}>{info.error}</div>
        </PanelSectionRow>
      )}
      {info && !info.error && !info.update_available && !path && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: OK_COLOR }}>{t("update.upToDate")}</div>
        </PanelSectionRow>
      )}
      {info?.update_available && info.download_url && !path && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={download} disabled={downloading}>
            {downloading
              ? t("update.downloading")
              : t("update.download", { version: info.latest_version ?? "" })}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {path && (
        <PanelSectionRow>
          <div style={styles.infoBox}>
            {t("update.downloadedTo", { path })}
            <br />
            <br />
            {t("update.howToInstall")}
          </div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={check} disabled={checking || downloading}>
          {checking ? t("update.checking") : t("update.check")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};

// ── Diagnostics ────────────────────────────────────────────────────────────────

/**
 * What this machine actually is, what is driving it, and what range that
 * leaves. The same facts scripts/ltdp-diagnostics.sh prints from a
 * terminal, so a device can be checked without leaving Gaming Mode.
 */
const DiagnosticsSection: FC = () => {
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [, t] = useLang();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDiag(await getDiagnostics());
    } catch (e) {
      notifyFailure(t("diag.failed"), e);
    } finally {
      setLoading(false);
    }
    // t is rebuilt on every render by design; the callback only reads it when
    // it runs, so the identity is deliberately not a dependency here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Gathered on demand rather than on mount: it probes acpi_call and scans
  // /proc, which is not work to do every time the Quick Access Menu opens.
  useEffect(() => { if (open && !diag) void load(); }, [open, diag, load]);

  const range = (key: "spl" | "sppt" | "fppt") => {
    const r = diag?.ranges?.[key];
    if (!r) return "-";
    const source = r.source === "firmware" ? t("diag.sourceFirmware") : t("diag.sourceProfile");
    return t("diag.rangeOf", { min: r.min, max: r.max, source });
  };

  // The BIOS line says how the installed firmware relates to the one this
  // build was written against - N3CN40WW - and flags the release Lenovo took
  // back. Reported, never acted on.
  const BIOS_NOTES: Record<string, StringKey> = {
    baseline: "diag.biosBaseline",
    older: "diag.biosOlder",
    newer: "diag.biosNewer",
    withdrawn: "diag.biosWithdrawn",
  };
  const biosKey = BIOS_NOTES[diag?.bios?.status ?? ""];
  const biosNote = biosKey
    ? t(biosKey, { baseline: `N3CN${diag?.bios?.baseline ?? 0}WW` })
    : "";

  const backendRow = (key: string) => {
    const b = diag?.backends?.[key];
    if (!b || !b.supported) return null;
    return (
      <PanelSectionRow key={key}>
        <Field
          label={BACKEND_LABELS[key] ?? key}
          description={
            <span style={{ color: b.available ? OK_COLOR : DIM_COLOR }}>
              {b.available ? t("diag.available") : t("diag.unavailable")}
              {b.detail_key
                ? ` - ${localise(t, { key: b.detail_key, params: b.detail_params })}`
                : ""}
            </span>
          }
        />
      </PanelSectionRow>
    );
  };

  return (
    <PanelSection title={t("diag.title")}>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => (open ? void load() : setOpen(true))}
          disabled={loading}>
          {loading ? t("diag.reading") : open ? t("diag.refresh") : t("diag.show")}
        </ButtonItem>
      </PanelSectionRow>
      {open && diag && (
        <>
          <PanelSectionRow>
            <Field label={t("diag.device")} description={diag.device} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("diag.model")} description={
              `${diag.dmi?.product_name || "?"}  ${diag.dmi?.product_version || ""}`.trim()} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("diag.cpu")} description={diag.cpu || "-"} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("diag.biosKernel")}
              description={
                <span>
                  {`${diag.dmi?.bios_version || "?"}  -  Linux ${diag.kernel || "?"}`}
                  {biosNote && (
                    <>
                      <br />
                      <span style={{ color: diag.bios?.status === "withdrawn" ? WARN_COLOR : DIM_COLOR }}>
                        {biosNote}
                      </span>
                    </>
                  )}
                </span>
              } />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("diag.activeBackend")}
              description={BACKEND_LABELS[diag.backend] ?? diag.backend ?? t("card.noBackend")} />
          </PanelSectionRow>
          {Object.keys(diag.backends ?? {}).map(backendRow)}
          <PanelSectionRow>
            <Field label={t("diag.splRange")} description={range("spl")} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("diag.spptRange")} description={range("sppt")} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("diag.fpptRange")} description={range("fppt")} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field
              label={t("diag.currentlySet")}
              description={`${fmt(diag.current?.spl)} / ${fmt(diag.current?.sppt)} / ${fmt(diag.current?.fppt)}`}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={t("live.draw")} description={fmt(diag.current?.package_draw)} />
          </PanelSectionRow>
          {(diag.platform_profile?.current || diag.firmware_mode) && (
            <PanelSectionRow>
              <Field
                label={t("diag.firmwareMode")}
                description={diag.platform_profile?.current
                  ? `${diag.platform_profile.current}${diag.platform_profile.choices?.length
                      ? ` (${t("diag.of", { list: diag.platform_profile.choices.join(", ") })})` : ""}`
                  : diag.firmware_mode}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <Field label={t("diag.version")} description={`v${diag.version}`} />
          </PanelSectionRow>
          {diag.notes?.map((note, i) => (
            <PanelSectionRow key={`note-${i}`}>
              <div style={{ fontSize: "11px", color: DIM_COLOR, lineHeight: "1.5" }}>{note}</div>
            </PanelSectionRow>
          ))}
        </>
      )}
    </PanelSection>
  );
};

// ── Main content ───────────────────────────────────────────────────────────────
const Content: FC = () => {
  const [ready,    setReady]    = useState(false);
  const [setupErr, setSetupErr] = useState<string | null>(null);

  const [tuning,   setTuning]   = useState<Tuning>(fromAbsolute(15, 18, 25));
  const [acTuning, setAcTuning] = useState<Tuning>(fromAbsolute(15, 18, 25));
  const [preset,   setPreset]   = useState<PresetKey>("balanced");

  const [stdCaps, setStdCaps] = useState<Caps>(FALLBACK_STD);
  const [maxCaps, setMaxCaps] = useState<Caps>(FALLBACK_MAX);
  // Hardware with no ryzenadj path has nothing above the firmware to unlock.
  const [extrasAvailable, setExtrasAvailable] = useState(true);
  // The ladder is per machine, so it comes from the backend with the ceilings.
  const [presets, setPresets] = useState<PresetTable>(PRESETS);
  const [minW,    setMinW]    = useState(FALLBACK_MIN);

  const [enabled,       setEnabled]       = useState(true);
  const [game,          setGame]          = useState<RunningGame | null>(null);
  const [perGame,       setPerGame]       = useState(false);

  const [acOnline,      setAcOnline]      = useState(false);
  const [acSeparate,    setAcSeparate]    = useState(false);
  const [editingAc,     setEditingAc]     = useState(false);

  const [globalProfile, setGlobalProfile] = useState<{ spl: number; sppt: number; fppt: number; preset: string | undefined }>({ spl: 15, sppt: 18, fppt: 25, preset: undefined });
  const [extrasUnlocked, setExtrasUnlocked] = useState(false);
  const [conflicts, setConflicts] = useState<Localised[]>([]);
  const [backend, setBackend] = useState("");
  const [deviceName, setDeviceName] = useState("Legion Go 1");
  const [charge, setCharge] = useState<ChargeLimit | null>(null);
  const [tab, setTab] = useState<TabKey>("tdp");
  const [fans, setFans] = useState<FanState | null>(null);
  const [lang, t] = useLang();

  const [savedPreset,   setSavedPreset]   = useState<string | undefined>(undefined);
  const [savedAcPreset, setSavedAcPreset] = useState<string | undefined>(undefined);

  const [status,   setStatus]   = useState<string | null>(null);
  // Whether `status` reports a failure. Kept alongside the text rather than
  // derived from it: the text is translated, and no prefix survives that.
  const [statusIsError, setStatusIsError] = useState(false);
  const [loading,  setLoading]  = useState(false);

  const visible = useQuickAccessVisible();

  const autoAppliedRef = useRef<string | null>(null);
  const noGameSyncedRef = useRef(false);
  const profileRequestRef = useRef(0);
  const statusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (statusTimerRef.current) clearTimeout(statusTimerRef.current); }, []);

  const caps    = extrasUnlocked && extrasAvailable ? maxCaps : stdCaps;
  const active  = editingAc ? acTuning : tuning;
  const setActive = editingAc ? setAcTuning : setTuning;
  const handlers = makeTuningHandlers(active, setActive, caps, minW);
  const om      = offsetMax(active.spl, caps);

  /** Adopt the charger half of the global settings. */
  const adoptGlobalAc = (s: Settings) => {
    const separate = s.ac_separate === true;
    setAcSeparate(separate);
    setSavedAcPreset(separate ? (s.ac_preset ?? "") : undefined);
    setAcTuning(fromAbsolute(
      toW(s.ac_spl ?? s.spl), toW(s.ac_sppt ?? s.sppt), toW(s.ac_fppt ?? s.fppt)));
    if (!separate) setEditingAc(false);
  };

  const showStatus = (msg: string | null, isError = false) => {
    if (statusTimerRef.current) clearTimeout(statusTimerRef.current);
    setStatus(msg);
    setStatusIsError(isError);
    if (msg) statusTimerRef.current = setTimeout(() => setStatus(null), 3000);
  };

  /** Inline status plus a toast: the inline line clears after three seconds and
   *  lives in a section the user may not be looking at. */
  const showError = (title: string, e: unknown) => {
    notifyFailure(title, e);
    showStatus(t("status.errorPrefix",
      { message: e instanceof Error ? e.message : String(e) }), true);
  };

  const applyGameProfile = async (
    gp: GameProfile,
    appId: string,
    statusMsg: string,
    isCurrent: () => boolean = () => AppWatcher.currentGame()?.appId === appId,
  ) => {
    if (!gp.exists || !gp.profile) {
      if (gp.exists) showStatus(t("status.profileCorrupt"));
      return;
    }
    const p  = gp.profile;
    const dc = fromAbsolute(toW(p.spl), toW(p.sppt), toW(p.fppt));
    const ac = gp.ac_profile ?? { spl: p.spl, sppt: p.sppt, fppt: p.fppt, ac_preset: "" };
    const at = fromAbsolute(toW(ac.spl), toW(ac.sppt), toW(ac.fppt));
    const storedPreset = (p.preset as PresetKey | undefined) || undefined;
    try {
      const result = await applyTdp(p.spl, p.sppt, p.fppt, appId, "", appId, "dc");
      if (!result.success) throw new Error(result.stderr || t("error.applyFailed"));
    } catch (e: unknown) {
      if (isCurrent()) showError(t("error.couldNotApply"), e);
      return false;
    }
    if (!isCurrent()) return false;
    setPerGame(true);
    setTuning(dc);
    setAcTuning(at);
    setAcSeparate(gp.ac_separate);
    setEditingAc(false);
    setSavedPreset(storedPreset);
    setSavedAcPreset(gp.ac_separate ? (ac.ac_preset ?? "") : undefined);
    setPreset(storedPreset || detectPreset(toW(p.spl), toW(p.sppt), toW(p.fppt), presets));
    showStatus(statusMsg);
    return true;
  };

  // ── Init ─────────────────────────────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const r = await isReady();
        if (!active) return;
        if (r.error) { setSetupErr(r.error); return; }
        if (r.ready) {
          const [s, ps, eu, c, cl, fs] = await Promise.all([
            getSettings(), getPowerSource(), getExtrasUnlocked(), getCaps(),
            getChargeLimit(), getFanState(),
          ]);
          if (!active) return;
          setCharge(cl);
          setFans(fs);
          const machinePresets = c?.presets ?? PRESETS;
          if (c?.std && c?.max) {
            setStdCaps(c.std); setMaxCaps(c.max); setMinW(c.min);
            setExtrasAvailable(c.extras !== false);
            setPresets(machinePresets);
          }
          setConflicts(c?.conflicts ?? []);
          setBackend(c?.backend ?? "");
          if (c?.device?.short) setDeviceName(c.device.short);
          // A saved language wins; the first run adopts the client's own and
          // writes it back, so the choice is made once and then remembered.
          if (isLang(s.language)) LanguageStore.set(s.language);
          else void setLanguageCall(LanguageStore.get()).catch(() => undefined);
          adoptGlobalAc(s);
          const w = toW(s.spl), sw = toW(s.sppt), fw = toW(s.fppt);
          setTuning(fromAbsolute(w, sw, fw));
          setGlobalProfile({ spl: w, sppt: sw, fppt: fw, preset: s.active_preset || undefined });
          setPreset((s.active_preset as PresetKey | undefined) || detectPreset(w, sw, fw, machinePresets));
          setEnabled(s.enabled !== false);
          setAcOnline(ps.ac);
          setExtrasUnlocked(eu);
          setReady(true);
        } else {
          if (active) setTimeout(check, 1000);
        }
      } catch (_) { if (active) setTimeout(check, 1000); }
    };
    check();
    return () => { active = false; };
  }, []);

  // ── Game detection ────────────────────────────────────────────────────────────
  // AppWatcher owns this and runs for the whole session, so the backend keeps
  // getting the authoritative appid while the panel is closed. Here we only
  // adopt what it reports.
  useEffect(() => {
    setGame(AppWatcher.currentGame());
    return AppWatcher.listen(setGame);
  }, []);

  // ── AC state ──────────────────────────────────────────────────────────────────
  // The enforce loop already reads the charger every five seconds to decide
  // which profile applies, and now emits when the answer changes - so the panel
  // subscribes instead of running its own three-second poll. The one read on
  // open seeds the label, since an event only fires on a change and the last one
  // may have happened while the panel was shut.
  useEffect(() => {
    if (!ready || !visible) return;
    let active = true;
    const onPower = (ps: PowerSource) => { if (active) setAcOnline(ps.ac); };
    addEventListener<[PowerSource]>("power_source", onPower);
    getPowerSource().then((ps) => { if (active) setAcOnline(ps.ac); }).catch(() => undefined);
    return () => {
      active = false;
      removeEventListener<[PowerSource]>("power_source", onPower);
    };
  }, [ready, visible]);

  // ── Auto-apply game profile when game / ready / enabled changes ──────────────
  useEffect(() => {
    if (!ready) return;
    const request = ++profileRequestRef.current;
    const current = (expected: string) =>
      request === profileRequestRef.current &&
      (AppWatcher.currentGame()?.appId ?? "") === expected;

    if (!enabled) {
      if (perGame) setPerGame(false);
      autoAppliedRef.current = null;
      noGameSyncedRef.current = false;
      return;
    }

    if (!game) {
      const wasInGame = autoAppliedRef.current !== null;
      if (perGame) setPerGame(false);
      autoAppliedRef.current = null;
      // setPerGame above re-runs this effect (perGame is a dependency), and
      // without this the whole no-game branch ran twice per game exit - a
      // second getSettings for a state we had already adopted.
      if (noGameSyncedRef.current) return;
      noGameSyncedRef.current = true;
      setSavedPreset(undefined);
      (async () => {
        try {
          const s = await getSettings();
          if (!current("")) return;
          adoptGlobalAc(s);
          const w = toW(s.spl), sw = toW(s.sppt), fw = toW(s.fppt);
          setTuning(fromAbsolute(w, sw, fw));
          setPreset((s.active_preset as PresetKey | undefined) || detectPreset(w, sw, fw, presets));
          setGlobalProfile({ spl: w, sppt: sw, fppt: fw, preset: s.active_preset || undefined });
          if (wasInGame) {
            const result = await applyTdp(
              s.spl, s.sppt, s.fppt, "", s.active_preset || "", "", "dc");
            if (!result.success) throw new Error(result.stderr || t("error.applyFailed"));
            if (!current("")) return;
            showStatus(t("status.globalRestored"));
          }
        } catch (e: unknown) {
          showError("LTDP", e);
        }
      })();
      return () => { profileRequestRef.current += 1; };
    }

    noGameSyncedRef.current = false;
    if (autoAppliedRef.current === game.appId) return;
    autoAppliedRef.current = game.appId;

    (async () => {
      try {
        const requestedGame = game;
        const gp = await getGameProfile(requestedGame.appId);
        if (!current(requestedGame.appId)) return;
        await applyGameProfile(
          gp,
          requestedGame.appId,
          t("status.autoApplied", { name: requestedGame.name }),
          () => current(requestedGame.appId),
        );
      } catch (e: unknown) {
        if (current(game.appId)) {
          autoAppliedRef.current = null;
          showError("LTDP", e);
        }
      }
    })();
    return () => { profileRequestRef.current += 1; };
  }, [game?.appId, ready, enabled]);

  // ── Preset handler ────────────────────────────────────────────────────────────
  const handlePresetChange = async (key: PresetKey) => {
    const prevPreset = preset;
    const prevTuning = tuning, prevAcTuning = acTuning;
    setPreset(key);
    if (key === "custom") return;

    const vals = presets[key];
    const next = normalise(fromAbsolute(vals.spl, vals.sppt, vals.fppt), caps, minW);
    if (editingAc) setAcTuning(next); else setTuning(next);

    setLoading(true);
    showStatus(null);
    const appId = (perGame && game) ? game.appId : "";
    const a = absolute(next);
    try {
      if (editingAc && !appId) {
        // Global charger profile: same call, saved into the AC slot.
        const r = await applyTdp(
          toMw(a.spl), toMw(a.sppt), toMw(a.fppt), "", key,
          AppWatcher.currentGame()?.appId ?? "", "ac");
        if (r.success) setSavedAcPreset(key);
        else { setPreset(prevPreset); setAcTuning(prevAcTuning); }
        showStatus(r.success
          ? t("status.acPresetSaved", { preset: t(PRESET_KEYS[key]) })
          : t("status.errorPrefix", { message: r.stderr || t("status.unknownError") }), !r.success);
      } else if (editingAc && appId) {
        const r = await setGameAcProfile(appId, toMw(a.spl), toMw(a.sppt), toMw(a.fppt), acSeparate, key);
        if (r.success) {
          setSavedAcPreset(key);
        } else {
          setPreset(prevPreset);
          setAcTuning(prevAcTuning);
        }
        showStatus(r.success
          ? t("status.acPresetSavedFor", { preset: t(PRESET_KEYS[key]), name: game!.name })
          : t("status.errorPrefix", { message: r.stderr || t("status.unknownError") }), !r.success);
      } else {
        const r = await applyTdp(
          toMw(a.spl), toMw(a.sppt), toMw(a.fppt), appId, key,
          AppWatcher.currentGame()?.appId ?? "", "dc");
        if (r.success) {
          if (!appId) setGlobalProfile({ ...a, preset: key });
          else setSavedPreset(key);
        } else {
          setPreset(prevPreset);
          setTuning(prevTuning);
        }
        showStatus(r.success
          ? (appId
              ? t("status.presetSavedFor", { preset: t(PRESET_KEYS[key]), name: game!.name })
              : t("status.presetApplied", { preset: t(PRESET_KEYS[key]) }))
          : t("status.errorPrefix", { message: r.stderr || t("status.unknownError") }),
          !r.success);
      }
    } catch (e: unknown) {
      setPreset(prevPreset);
      if (editingAc) setAcTuning(prevAcTuning); else setTuning(prevTuning);
      showError("LTDP", e);
    }
    setLoading(false);
  };

  // ── Per-game toggle ───────────────────────────────────────────────────────────
  const handlePerGameToggle = async (checked: boolean) => {
    setPerGame(checked);
    if (!checked && game) {
      const prevAcSeparate = acSeparate, prevEditingAc = editingAc;
      const prevSavedPreset = savedPreset, prevSavedAcPreset = savedAcPreset;
      // The global charger profile is re-read from the settings below; only
      // the per-game state is cleared here.
      setEditingAc(false);
      setSavedPreset(undefined);
      let profileDeleted = false;
      try {
        const deleted = await deleteGameProfile(game.appId);
        if (!deleted.success) throw new Error(deleted.stderr || t("error.couldNotDelete"));
        profileDeleted = true;
        const s = await getSettings();
        adoptGlobalAc(s);
        const w = toW(s.spl), sw = toW(s.sppt), fw = toW(s.fppt);
        setTuning(fromAbsolute(w, sw, fw));
        setPreset((s.active_preset as PresetKey | undefined) || detectPreset(w, sw, fw, presets));
        setGlobalProfile({ spl: w, sppt: sw, fppt: fw, preset: s.active_preset || undefined });
        showStatus(t("status.switchedToGlobal"));
      } catch (e: unknown) {
        if (!profileDeleted) {
          setPerGame(true);
          setAcSeparate(prevAcSeparate); setEditingAc(prevEditingAc);
          setSavedPreset(prevSavedPreset); setSavedAcPreset(prevSavedAcPreset);
        }
        showError("LTDP", e);
      }
      // Cleared last so the auto-apply effect cannot race the delete above.
      autoAppliedRef.current = profileDeleted ? game.appId : null;
    } else if (checked && game) {
      try {
        const gp = await getGameProfile(game.appId);
        if (!gp.exists) {
          setSavedPreset(undefined);
          setSavedAcPreset(undefined);
          showStatus(t("status.noProfile", { name: game.name }));
          autoAppliedRef.current = game.appId;
        } else {
          await applyGameProfile(gp, game.appId,
            t("status.profileApplied", { name: game.name }));
        }
      } catch (e: unknown) {
        setPerGame(false);
        showError("LTDP", e);
      }
    }
  };

  // ── Enable / disable plugin ───────────────────────────────────────────────────
  const handleEnabledToggle = async (checked: boolean) => {
    setEnabled(checked);
    showStatus(null);
    try {
      const result = await setPluginEnabled(checked);
      if (!result.success) throw new Error(result.stderr || t("error.couldNotToggle"));
      showStatus(t(checked ? "status.enabled" : "status.disabled"));
    } catch (e: unknown) {
      setEnabled(!checked);
      showError("LTDP", e);
    }
  };

  // ── AC separate toggle ────────────────────────────────────────────────────────
  const handleAcSeparateToggle = async (checked: boolean) => {
    if (!perGame || !game) {
      // Global: the backend seeds the AC values from the battery ones the
      // first time it is switched on, and applies whichever set the machine
      // should be running now.
      const prevSeparate = acSeparate, prevEditingAc = editingAc;
      const prevAcTuning = acTuning, prevSavedAcPreset = savedAcPreset;
      setAcSeparate(checked);
      if (checked && savedAcPreset === undefined) setAcTuning(tuning);
      if (!checked) { setEditingAc(false); setSavedAcPreset(undefined); }
      try {
        const result = await setGlobalAcSeparate(checked);
        if (!result.success) throw new Error(result.stderr || t("error.couldNotAc"));
        const s = await getSettings();
        adoptGlobalAc(s);
        showStatus(t(checked ? "status.acOn" : "status.acOff"));
      } catch (e: unknown) {
        setAcSeparate(prevSeparate);
        setEditingAc(prevEditingAc);
        setAcTuning(prevAcTuning);
        setSavedAcPreset(prevSavedAcPreset);
        showError("LTDP", e);
      }
      return;
    }
    const prevSavedAcPreset = savedAcPreset;
    const prevEditingAc = editingAc;
    const prevAcTuning = acTuning;
    setAcSeparate(checked);
    let use = acTuning;
    if (checked && savedAcPreset === undefined) {
      use = tuning;
      setAcTuning(tuning);
    }
    if (!checked) {
      setEditingAc(false);
      setSavedAcPreset(undefined);
    }
    const a = absolute(use);
    try {
      const result = await setGameAcProfile(
        game.appId, toMw(a.spl), toMw(a.sppt), toMw(a.fppt), checked, "");
      if (!result.success) throw new Error(result.stderr || t("error.couldNotSaveAc"));
    } catch (e: unknown) {
      setAcSeparate(!checked);
      setSavedAcPreset(prevSavedAcPreset);
      setEditingAc(prevEditingAc);
      setAcTuning(prevAcTuning);
      showError("LTDP", e);
    }
  };

  // ── Tabs ─────────────────────────────────────────────────────────────────────
  // The shoulder buttons page between them, the way the rest of the Steam UI
  // does. The strip below stays clickable regardless: Steam is free to consume
  // a bumper before it reaches us, and a tab you cannot reach by touch would
  // then be a tab you cannot reach at all.
  const cycleTab = (delta: number) =>
    setTab(TABS[(TABS.indexOf(tab) + delta + TABS.length) % TABS.length]);

  const onPanelButton = (event: DeckyGamepadEvent) => {
    switch (event?.detail?.button) {
      case GamepadButton.BUMPER_RIGHT:
      case GamepadButton.TRIGGER_RIGHT:
        cycleTab(1);
        break;
      case GamepadButton.BUMPER_LEFT:
      case GamepadButton.TRIGGER_LEFT:
        cycleTab(-1);
        break;
      default:
        break;
    }
  };

  // ── Fans ─────────────────────────────────────────────────────────────────────
  // The firmware wipes the curve whenever the power mode moves, which is every
  // time a TDP value is applied - the backend's enforce pass puts it back, so
  // nothing here has to.
  const handleFanMode = async (mode: string) => {
    const previous = fans;
    setFans((current) => (current ? { ...current, mode } : current));
    setLoading(true);
    try {
      const result = await setFanModeCall(mode);
      if (!result.success) throw new Error(result.stderr || t("fan.unsupported"));
      setFans(await getFanState());
    } catch (e: unknown) {
      setFans(previous);
      showError("LTDP", e);
    }
    setLoading(false);
  };

  // ── Charge limit ─────────────────────────────────────────────────────────────
  // Independent of the Enable switch above: that one is about power limits, and
  // this one is about how the battery is charged.
  const handleChargeLimitToggle = async (checked: boolean) => {
    const previous = charge;
    setCharge((current) => (current ? { ...current, enabled: checked } : current));
    try {
      const result = await setChargeLimitCall(checked);
      if (!result.success) throw new Error(result.stderr || t("error.couldNotChargeLimit"));
      setCharge(await getChargeLimit());
      showStatus(t(checked ? "status.chargeLimitOn" : "status.chargeLimitOff"));
    } catch (e: unknown) {
      setCharge(previous);
      showError("LTDP", e);
    }
  };

  // ── Language ─────────────────────────────────────────────────────────────────
  // Switched locally first so the panel redraws on the button press, then
  // persisted; a failed write is reported but not rolled back, because the
  // language the user just chose is still the one they want to read.
  const handleLanguageChange = async (next: Lang) => {
    if (next === lang) return;
    LanguageStore.set(next);
    try {
      const result = await setLanguageCall(next);
      if (!result.success) throw new Error(result.stderr || t("error.couldNotLanguage"));
    } catch (e: unknown) {
      notifyFailure("LTDP", e);
    }
  };

  // ── Extras: unlock extended TDP range ────────────────────────────────────────
  const handleExtrasUnlockedToggle = async (checked: boolean) => {
    setExtrasUnlocked(checked);
    try {
      const result = await setExtrasUnlockedCall(checked);
      if (!result.success) throw new Error(result.stderr || t("error.couldNotExtras"));
    } catch (e: unknown) {
      setExtrasUnlocked(!checked);
      showError("LTDP", e);
      return;
    }
    if (checked) return;

    // The backend clamps every persisted target and the active hardware change
    // in one transaction. Mirror that result locally without issuing a second
    // apply that could race a game or charger transition.
    const dc = normalise(tuning,   stdCaps, minW);
    const at = normalise(acTuning, stdCaps, minW);
    const tChanged = dc.spl !== tuning.spl || dc.spptOff !== tuning.spptOff ||
      dc.fpptOff !== tuning.fpptOff;
    const atChanged = at.spl !== acTuning.spl || at.spptOff !== acTuning.spptOff ||
      at.fpptOff !== acTuning.fpptOff;
    setTuning(dc);
    setAcTuning(at);
    setGlobalProfile((current) => {
      const clamped = normalise(
        fromAbsolute(current.spl, current.sppt, current.fppt), stdCaps, minW);
      const values = absolute(clamped);
      return values.spl !== current.spl || values.sppt !== current.sppt || values.fppt !== current.fppt
        ? { ...values, preset: "custom" }
        : current;
    });
    if (tChanged) {
      setPreset("custom");
      if (perGame) setSavedPreset("custom");
    }
    if (acSeparate && atChanged) setSavedAcPreset("custom");
  };

  // ── Apply (Custom mode only) ──────────────────────────────────────────────────
  const apply = async () => {
    setLoading(true);
    showStatus(null);
    const appId = (perGame && game) ? game.appId : "";
    const a = absolute(active);
    try {
      if (editingAc && !appId) {
        const r = await applyTdp(
          toMw(a.spl), toMw(a.sppt), toMw(a.fppt), "", "custom",
          AppWatcher.currentGame()?.appId ?? "", "ac");
        if (r.success) setSavedAcPreset("custom");
        showStatus(r.success ? t("status.acProfileSaved")
          : t("status.errorPrefix", { message: r.stderr || t("status.unknownError") }), !r.success);
      } else if (editingAc && appId) {
        const r = await setGameAcProfile(appId, toMw(a.spl), toMw(a.sppt), toMw(a.fppt), acSeparate, "custom");
        if (r.success) setSavedAcPreset("custom");
        showStatus(r.success ? t("status.acProfileSavedFor", { name: game!.name })
          : t("status.errorPrefix", { message: r.stderr || t("status.unknownError") }), !r.success);
      } else {
        const r = await applyTdp(
          toMw(a.spl), toMw(a.sppt), toMw(a.fppt), appId, "custom",
          AppWatcher.currentGame()?.appId ?? "", "dc");
        if (r.success) {
          if (!appId) setGlobalProfile({ ...a, preset: "custom" });
          else setSavedPreset("custom");
        }
        showStatus(r.success
          ? (appId ? t("status.profileSavedFor", { name: game!.name })
                   : t("status.customApplied"))
          : t("status.errorPrefix", { message: r.stderr || t("status.unknownError") }),
          !r.success);
      }
    } catch (e: unknown) {
      showError("LTDP", e);
    }
    setLoading(false);
  };

  // ── Render ────────────────────────────────────────────────────────────────────
  if (setupErr) return (
    <PanelSection title={t("panel.setupError")}>
      <PanelSectionRow>
        <Field label={t("panel.error")} description={setupErr} />
      </PanelSectionRow>
    </PanelSection>
  );

  if (!ready) return (
    <PanelSection title={t("panel.initializing")}>
      <PanelSectionRow><Spinner /></PanelSectionRow>
    </PanelSection>
  );

  return (
    <Focusable onButtonDown={onPanelButton} style={{ display: "flex",
                                                     flexDirection: "column" }}>
      <PanelSection>
        <PanelSectionRow>
          <Focusable style={styles.segmentRow} flow-children="horizontal">
            {TABS.map((key) => (
              <DialogButton
                key={key}
                style={{ ...styles.segment, ...(tab === key ? activeStyle : {}) }}
                onClick={() => setTab(key)}
              >
                {t(TAB_KEYS[key])}
              </DialogButton>
            ))}
          </Focusable>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "10px", color: DIM_COLOR, textAlign: "center" }}>
            {t("tab.hint")}
          </div>
        </PanelSectionRow>
      </PanelSection>

      {tab === "enhancers" ? <EnhancersTab /> : <>
      <PanelSection title="LTDP">
        <PanelSectionRow>
          <ToggleField
            label={t("panel.enable")}
            description={
              enabled ? (
                <span>
                  <span style={{ fontSize: "11px", color: DIM_COLOR }}>
                    {t(acSeparate && !perGame ? "panel.globalBattery" : "panel.global")}
                  </span>
                  <span style={styles.profileTag}>{profileLabel(t, globalProfile.spl, globalProfile.sppt, globalProfile.fppt, globalProfile.preset, presets)}</span>
                  {acSeparate && !perGame && (
                    <>
                      <span style={{ fontSize: "11px", color: DIM_COLOR }}>{t("panel.globalAc")}</span>
                      <span style={styles.profileTag}>
                        {profileLabel(t, absolute(acTuning).spl, absolute(acTuning).sppt,
                                      absolute(acTuning).fppt, savedAcPreset, presets)}
                      </span>
                    </>
                  )}
                  {!extrasUnlocked && exceedsCaps(globalProfile.spl, globalProfile.sppt, globalProfile.fppt, stdCaps) && (
                    <span style={{ fontSize: "11px", color: WARN_COLOR }}>{t("panel.exceeds")}</span>
                  )}
                </span>
              ) : t("panel.usingDefaults")
            }
            checked={enabled}
            onChange={handleEnabledToggle}
          />
        </PanelSectionRow>
        {conflicts.length > 0 && (
          <PanelSectionRow>
            <div style={styles.infoBox}>
              {t("panel.conflict",
                 { list: conflicts.map((c) => localise(t, c)).join("; ") })}
            </div>
          </PanelSectionRow>
        )}
        {status && !enabled && (
          <PanelSectionRow>
            <div style={statusStyle(statusIsError)}>
              {status}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <LivePanel device={deviceName} backend={backend} />

      {enabled && <>
        <PanelSection title={t("game.title")}>
          <PanelSectionRow>
            <ToggleField
              label={t("game.perGame")}
              description={
                game ? (
                  perGame ? (
                    <span style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
                      <span>{game.name}</span>
                      <span style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
                        <span>
                          <span style={{ fontSize: "11px", color: DIM_COLOR }}>{t("game.battery")}</span>
                          <span style={styles.profileTag}>
                            {profileLabel(t, absolute(tuning).spl, absolute(tuning).sppt, absolute(tuning).fppt, savedPreset, presets)}
                          </span>
                        </span>
                        {acSeparate && (
                          <span>
                            <span style={{ fontSize: "11px", color: DIM_COLOR }}>{t("game.ac")}</span>
                            <span style={styles.profileTag}>
                              {profileLabel(t, absolute(acTuning).spl, absolute(acTuning).sppt, absolute(acTuning).fppt, savedAcPreset, presets)}
                            </span>
                          </span>
                        )}
                      </span>
                    </span>
                  ) : game.name
                ) : t("game.noGame")
              }
              checked={perGame}
              disabled={!game}
              onChange={handlePerGameToggle}
            />
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title={t("power.title")}>
          <PanelSectionRow>
            <ToggleField
              label={t("power.separate")}
              description={acSeparate
                ? (perGame && game
                    ? t("power.separateOnGame", { name: game.name })
                    : t("power.separateOn"))
                : t("power.separateOff")}
              checked={acSeparate}
              onChange={handleAcSeparateToggle}
            />
          </PanelSectionRow>
          {acSeparate && (
            <PanelSectionRow>
              {/* Focusable with horizontal flow keeps both halves reachable
                  with the stick; a bare div would be invisible to the
                  gamepad. */}
              <Focusable style={styles.segmentRow} flow-children="horizontal">
                <DialogButton
                  style={{ ...styles.segment, ...(editingAc ? {} : activeStyle) }}
                  onClick={() => setEditingAc(false)}
                >
                  {t("power.batteryProfile")}
                </DialogButton>
                <DialogButton
                  style={{ ...styles.segment, ...(editingAc ? activeStyle : {}) }}
                  onClick={() => setEditingAc(true)}
                >
                  {t("power.acProfile")}
                </DialogButton>
              </Focusable>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", fontWeight: "bold", color: acOnline ? OK_COLOR : WARN_COLOR }}>
              {t(acOnline ? "power.charging" : "power.onBattery")}
              {backend ? (
                <span style={{ fontWeight: "normal", color: DIM_COLOR }}>
                  {"   -   "}{BACKEND_LABELS[backend] ?? backend}
                </span>
              ) : null}
            </div>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title={t("preset.title")}>
          {/* Six stacked full-width buttons was six screens of scrolling on a
              handheld. Two columns fit the panel, and each chip carries the
              watts it stands for, so the ladder is readable without opening
              Custom to find out. */}
          <PanelSectionRow>
            <Focusable style={styles.presetGrid} flow-children="horizontal">
              {PRESET_ORDER.map((key) => {
                const values = key === "custom" ? null : presets[key];
                return (
                  <DialogButton
                    key={key}
                    style={{ ...styles.presetButton, ...(preset === key ? activeStyle : {}) }}
                    disabled={loading}
                    onClick={() => handlePresetChange(key)}
                  >
                    <span style={styles.presetName}>{t(PRESET_KEYS[key])}</span>
                    <span style={styles.presetWatts}>
                      {values ? `${values.spl} / ${values.sppt} / ${values.fppt} W` : `${minW} - ${caps.spl} W`}
                    </span>
                  </DialogButton>
                );
              })}
            </Focusable>
          </PanelSectionRow>
          {status && preset !== "custom" && (
            <PanelSectionRow>
              <div style={statusStyle(statusIsError)}>
                {status}
              </div>
            </PanelSectionRow>
          )}
        </PanelSection>

        {preset === "custom" && (
          <>
            <PanelSection title={t(editingAc ? "limits.titleAc" : "limits.title")}>
              <PanelSectionRow>
                <SliderField
                  label={t("limits.spl", { value: active.spl })}
                  value={active.spl} min={minW} max={caps.spl} step={1}
                  onChange={handlers.onSpl}
                  description={t("limits.splDesc")}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <SliderField
                  label={t("limits.sppt", { offset: active.spptOff, total: active.spl + active.spptOff })}
                  value={active.spptOff} min={0} max={om.sppt || 1} step={1}
                  disabled={om.sppt === 0}
                  onChange={handlers.onSppt}
                  description={om.sppt === 0
                    ? t("limits.noHeadroom")
                    : t("limits.spptDesc", { max: om.sppt })}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <SliderField
                  label={t("limits.fppt", { offset: active.fpptOff, total: active.spl + active.fpptOff })}
                  value={active.fpptOff} min={0} max={om.fppt || 1} step={1}
                  disabled={om.fppt === 0}
                  onChange={handlers.onFppt}
                  description={om.fppt === 0
                    ? t("limits.noHeadroom")
                    : t("limits.fpptDesc", { max: om.fppt })}
                />
              </PanelSectionRow>
            </PanelSection>

            <PanelSection title={t("action.title")}>
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={apply} disabled={loading}>
                  {loading ? t("action.applying")
                    : editingAc && game ? t("action.saveAcFor", { name: game.name })
                    : perGame && game ? t("action.saveFor", { name: game.name })
                    : t("action.apply")}
                </ButtonItem>
              </PanelSectionRow>
              {status && (
                <PanelSectionRow>
                  <div style={statusStyle(statusIsError)}>
                    {status}
                  </div>
                </PanelSectionRow>
              )}
            </PanelSection>
          </>
        )}
      </>}

      <UpdateSection />

      <DiagnosticsSection />

      {extrasAvailable && (
        <PanelSection title={t("extras.title")}>
          <PanelSectionRow>
            <div style={styles.infoBox}>{t("extras.warning")}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label={t("extras.unlock", { max: maxCaps.spl })}
              description={t(extrasUnlocked ? "extras.on" : "extras.off", { max: maxCaps.spl })}
              checked={extrasUnlocked}
              onChange={handleExtrasUnlockedToggle}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title={t("fan.title")}>
        {!fans?.supported ? (
          <PanelSectionRow>
            <div style={styles.infoBox}>{t("fan.unsupported")}</div>
          </PanelSectionRow>
        ) : (
          <>
            <PanelSectionRow>
              <Focusable style={styles.presetGrid} flow-children="horizontal">
                {FAN_MODES.map((mode) => (
                  <DialogButton
                    key={mode}
                    style={{ ...styles.presetButton,
                             ...(fans.mode === mode ? activeStyle : {}) }}
                    disabled={loading}
                    onClick={() => handleFanMode(mode)}
                  >
                    <span style={styles.presetName}>{t(FAN_MODE_KEYS[mode])}</span>
                  </DialogButton>
                ))}
              </Focusable>
            </PanelSectionRow>
            <PanelSectionRow>
              <div style={{ fontSize: "11px", color: DIM_COLOR, lineHeight: "1.5" }}>
                {t(fans.mode === "auto" ? "fan.autoDesc"
                   : fans.mode === "max" ? "fan.maxDesc" : "fan.curveDesc")}
              </div>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title={t("battery.title")}>
        <PanelSectionRow>
          <ToggleField
            label={t("battery.limit")}
            description={!charge?.supported
              ? t("battery.unsupported")
              : `${t(charge.enabled ? "battery.limitOn" : "battery.limitOff")}${
                  charge.source ? `   -   ${t("battery.via", { source: charge.source })}` : ""}`}
            checked={charge?.enabled ?? false}
            disabled={!charge?.supported}
            onChange={handleChargeLimitToggle}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t("lang.title")}>
        <PanelSectionRow>
          <DropdownItem
            label={t("lang.title")}
            rgOptions={LANGS.map((code) => ({ data: code, label: LANG_NAMES[code] }))}
            selectedOption={lang}
            onChange={(option) => handleLanguageChange(option.data as Lang)}
          />
        </PanelSectionRow>
      </PanelSection>

      </>}

      <PanelSectionRow>
        <div style={styles.footer}>
          by <span style={styles.footerName}>LORDEL</span>
        </div>
      </PanelSectionRow>
    </Focusable>
  );
};

// ── Plugin entry point ─────────────────────────────────────────────────────────

export default definePlugin(() => {
  // Started here rather than from the panel: the backend enforce loop needs the
  // running appid whether or not anyone has the Quick Access Menu open.
  AppWatcher.start();

  return {
    name: "LTDP",
    titleView: (
      <div className={staticClasses.Title}
        style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
        <span>LTDP</span>
        <span style={{ fontSize: "11px", opacity: 0.6, fontWeight: "normal" }}>
          Legion Go 1
        </span>
      </div>
    ),
    content: <Content />,
    icon: <ChipIcon />,
    onDismount() {
      AppWatcher.stop();
    },
  };
});
