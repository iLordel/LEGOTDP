# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# https://github.com/Rayekkk/LeGoTDP

import decky
import asyncio
import copy
import glob
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import threading
from settings import SettingsManager

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# Not `updater`: the loader aliases its own decky_loader.updater to that bare
# name before we are imported, and sys.modules wins over sys.path. See the
# module docstring in ltdp_updater.py.
from ltdp_updater import Updater  # noqa: E402 - needs the sys.path line above

# Device identity, per-machine capability profiles, and the acpi_call transport
# for the firmware interface on kernels without the Lenovo WMI driver. Both are
# plain standard-library modules so the diagnostic script can import them too.
import ltdp_acpi  # noqa: E402
import ltdp_device  # noqa: E402
from ltdp_device import (  # noqa: E402
    BACKEND_ACPI,
    BACKEND_RYZENADJ,
    BACKEND_WMI,
    PRESETS_DEFAULT,
    PRESETS_LEGION_GO_1,
    PRESETS_LEGION_GO_S,
)

BIN_DIR       = os.path.join(PLUGIN_DIR, "bin")
BIN_PATH      = os.path.join(BIN_DIR, "ryzenadj")
RYZENADJ_URL  = (
    "https://github.com/FlyGoat/RyzenAdj/releases/download/v0.19.0/"
    "ryzenadj-manylinux_2_28-x86_64.tar.gz"
)
RYZENADJ_SHA256 = "d04547f111c6af3e40d3f210468adb884561618ddade0b640d90e50c88d03444"
RYZENADJ_BINARY_SHA256 = "18a61170efec95d2366355b9dd5c75a961a9e8008d42e3471f4f414a6faec471"
GITHUB_RELEASES_URL = "https://api.github.com/repos/iLordel/LEGOTDP/releases/latest"

# On, and pointed at this fork's own releases. It was off while the URL still
# named upstream: a check against that repository would have offered a package
# built for the Legion Go 2, with a different device table on it.
#
# The updater downloads; it does not install. This plugin runs as root, and
# replacing its own code over the network without the user pressing anything
# in Decky is not a power it should hold.
UPDATE_CHECKS_ENABLED = True

# Update checks, TLS trust store and downloads live in a reusable helper. The
# host allowlist matters especially here: this plugin executes RyzenAdj, so an
# unrestricted URL would be a fetch-and-run primitive.
updater = Updater(
    releases_url=GITHUB_RELEASES_URL,
    user_agent="LTDP",
    log_prefix="[ltdp]",
    plugin_dir=PLUGIN_DIR,
    asset_name_template="LTDP-{version}.zip",
    logger=decky.logger,
)

# Firmware ranges are per machine (30 / 32 / 41 W on a Legion Go 1,
# 35 / 37 / 45 W on a Go 2, 40 / 43 / 53 W on a Go S), so there is no single
# fallback constant here: _fallback_std_w() asks the device profile instead.

# Battery conservation. The firmware's own limit is a fixed 80 %, so this is a
# switch rather than a slider - offering a percentage the hardware would round
# to 80 anyway would be a lie told with more precision.
CHARGE_LIMIT_PERCENT = 80
CHARGE_FULL_PERCENT = 100
CHARGE_LIMIT_GLOB = "/sys/class/power_supply/BAT*/charge_control_end_threshold"

# Temperature and fan readings come from hwmon, which is the kernel's own view
# and therefore works whichever backend is driving the limits.
HWMON_GLOB = "/sys/class/hwmon/hwmon*"
CPU_TEMP_DRIVERS = ("k10temp", "zenpower")
FAN_HWMON_DRIVERS = ("lenovo_wmi_other", "legion_wmi", "lenovo_wmi")

# Fan modes. "auto" hands the curve back to the firmware; the rest are curves
# at or above the firmware's own minimum, because the reason to touch the fans
# on a handheld is to cool it more than Lenovo chose to, never less.
FAN_MODES = ("auto", "quiet", "balanced", "cool", "max")
FAN_CURVES = {
    # Ten points, one per 10 °C from 10 °C to 100 °C.
    "quiet":    (44, 48, 55, 60, 71, 79, 87, 87, 100, 100),
    "balanced": (48, 52, 60, 68, 78, 86, 93, 95, 100, 100),
    "cool":     (55, 60, 70, 80, 90, 95, 100, 100, 100, 100),
}

# Panel languages. The frontend carries the strings; the backend only stores
# which one was chosen, and refuses anything it does not know.
SUPPORTED_LANGUAGES = ("en", "ru", "es")

# Absolute floor/ceiling for any single limit, in milliwatts. Applied on load, which
# also migrates profiles saved back when the Extras ceiling was 60 W. The device
# profile narrows the ceiling further - a Legion Go 1 never goes above 40 W even
# with Extras unlocked.
HARD_MIN_MW = 5000
HARD_MAX_MW = 50000

# The preset ladders (PRESETS_LEGION_GO_1, PRESETS_DEFAULT, PRESETS_LEGION_GO_S)
# are imported from ltdp_device.py above - one per machine, defined next to the
# firmware range they were spaced against.

# Lenovo firmware attributes, published by the in-kernel lenovo-wmi-other driver
# (Linux 6.17 and newer). Writing these goes through the EC instead of poking the
# SMU directly, so the firmware stops fighting us and the values survive suspend.
# The instance number is not always 0, so the directory is globbed rather than
# hard-coded, with the historical path as the first candidate.
WMI_ROOT_GLOB = "/sys/class/firmware-attributes/lenovo-wmi-other-*/attributes"
WMI_ROOT = "/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes"
WMI_ATTRS = {"spl": "ppt_pl1_spl", "sppt": "ppt_pl2_sppt", "fppt": "ppt_pl3_fppt"}
PLATFORM_PROFILE_GLOB = "/sys/class/platform-profile/*/profile"

# Package energy counter, used instead of spawning `ryzenadj --info` every 2 s.
# Matched by the `name` file rather than the directory prefix: the powercap
# node is intel-rapl:N on most kernels but not all of them, and on the Z1
# Extreme the package counter is the one that answers.
RAPL_GLOB = "/sys/class/powercap/*:*"

_ryzenadj_lock = threading.Lock()
# Serialises a complete logical mutation: hardware apply, persistent settings
# and the target defended by the background loop. _apply_lock alone is too
# narrow because it is released before callers record what was applied.
_mutation_lock = threading.RLock()
# Serialises every hardware apply. The ryzenadj path has its own lock, but the WMI
# path (profile bounce + three ppt writes) is not atomic, so concurrent applies from
# the enforce loop and a user action could interleave and corrupt each other.
_apply_lock = threading.Lock()

# Runtime capability, not merely device capability. A Go 2 still has a working
# WMI range when the download fails, but it must not advertise the Extras range
# until the executable actually exists and passed its integrity check.
_ryzenadj_available: bool = False

# Cache of last successful --info parse - keeps UI responsive when lock is held
_info_cache: dict = {}
_info_cache_ts: float = 0.0
_info_cache_lock = threading.Lock()

_ROW_RE = re.compile(r"\|\s*(.+?)\s*\|\s*([\d.]+)\s*\|")

_current_game_id: str = ""
_current_ac_online: bool = False

# The panel says when it is on screen, and re-says it every 30 s while it stays
# there. The timestamp is what makes that a lease rather than a latch: a
# frontend that goes away without running its cleanup - a Steam UI restart, say
# - used to leave the info loop reading RAPL every two seconds, and spawning
# `ryzenadj --info` every fifteen with Extras on, for the rest of the session.
# _frontend_appid below is leased the same way for the same reason.
_panel_active: bool = False
_panel_active_ts: float = 0.0
_PANEL_ACTIVE_TTL_S = 90.0

# The frontend detects the running game via Steam's Router, which is authoritative;
# the /proc/*/environ scan misses games sandboxed by pressure-vessel/gamescope. When
# the panel is open the frontend pushes the appid here; we trust it while it is fresh
# and fall back to the proc scan once it goes stale (panel closed).
_frontend_appid: str = ""
_frontend_appid_ts: float = 0.0
_FRONTEND_APPID_TTL = 12.0


# ── Device identity ────────────────────────────────────────────────────────────

_wmi_only_cache: bool | None = None


def _dmi(field: str) -> str:
    try:
        with open(f"/sys/class/dmi/id/{field}") as f:
            return f.read().strip()
    except OSError:
        return ""


def _device():
    """The device profile for the hardware in front of us.

    Detected once - DMI does not change while the machine is running - and
    re-detected whenever _wmi_only_cache is cleared, which is how the tests
    move the process between machines.
    """
    global _wmi_only_cache
    if _wmi_only_cache is None:
        ltdp_device.reset_cache()
        profile = ltdp_device.detect(_dmi)
        _wmi_only_cache = profile.firmware_only
        decky.logger.info(
            f"[ltdp] device: {profile.label} "
            f"(product_name={_dmi('product_name') or '?'}, "
            f"backends={'/'.join(profile.backends)})")
    return ltdp_device.detect(_dmi)


def _wmi_only() -> bool:
    """True on hardware this plugin drives through the firmware alone.

    On a Legion Go S there is no ryzenadj at all, so the firmware range is the
    whole range. A Legion Go 1 is not in that category: the firmware path is
    preferred there, but ryzenadj remains as the fallback for the kernels that
    expose neither the Lenovo driver nor acpi_call.
    """
    return bool(_device().firmware_only)


def _fallback_std_w() -> dict:
    """Firmware ceilings in watts for this machine, when it will not say."""
    return {k: _device().fallback_range(k)[1] for k in ("spl", "sppt", "fppt")}


def _fallback_min_w() -> int:
    """The lowest limit this machine's firmware is documented to accept."""
    return max(HARD_MIN_MW // 1000,
               min(_device().fallback_range(k)[0] for k in ("spl", "sppt", "fppt")))


def _extras_ceilings_mw() -> tuple[int, int, int]:
    """What the Extras range reaches on this machine, in milliwatts.

    Per device rather than one number for everything: a Legion Go 1 has a 30 W
    firmware ceiling and a chassis to match, so its unlocked range stops at
    40 W instead of the 50 W a Go 2 will take.
    """
    extras = _device().extras_caps
    if not extras:
        return _standard_ceilings_mw()
    return tuple(min(extras.get(k, HARD_MAX_MW // 1000) * 1000, HARD_MAX_MW)
                 for k in ("spl", "sppt", "fppt"))


def _presets() -> dict:
    """The preset ladder for the hardware in front of us."""
    return _device().presets


def _defaults() -> dict:
    """Where a fresh install starts, in milliwatts.

    Read from the ladder rather than written out again, because Balanced is not
    the same everywhere - 15 / 17 / 22 W on a Go 1, 15 / 18 / 25 W on a Go 2,
    18 / 20 / 25 W on a Go S. Hard-coding one of them meant a fresh install on
    another machine opened on numbers belonging to a different device, and
    disagreed with the preset the panel was highlighting at the same moment.
    """
    balanced = _presets()["balanced"]
    return {"spl":  balanced["spl"]  * 1000,
            "sppt": balanced["sppt"] * 1000,
            "fppt": balanced["fppt"] * 1000,
            "enabled": True}


def _ceilings_mw() -> tuple[int, int, int]:
    """(spl, sppt, fppt) ceilings in milliwatts - the absolute bound.

    One per parameter, because the firmware does not use the same limit for all
    three - a Legion Go 1 reports 30 / 32 / 41 W, a Go S 40 / 43 / 53 W.

    This is the widest anything may ask for on this machine: the Extras ceiling
    where a second tool can reach past the firmware, and the firmware ceiling
    where it cannot.
    """
    if _wmi_only():
        return _standard_ceilings_mw()
    return _extras_ceilings_mw()


def _standard_ceilings_mw() -> tuple[int, int, int]:
    """Firmware ceilings in milliwatts, with the per-device safe fallback.

    The firmware's own numbers win whenever it publishes them. It only does so
    through the in-kernel driver; on the acpi_call path there is no equivalent
    to read, so the documented range for this machine is used and every write
    is verified against what comes back.
    """
    caps = _wmi_caps()
    if caps:
        return tuple(caps[k]["max"] * 1000 for k in ("spl", "sppt", "fppt"))
    fallback = _fallback_std_w()
    return tuple(fallback[k] * 1000 for k in ("spl", "sppt", "fppt"))


def _allowed_ceilings_mw(state: dict) -> tuple[int, int, int]:
    """Ceilings the current persisted mode is allowed to apply."""
    if _wmi_only():
        return _ceilings_mw()
    if state.get("extras_unlocked", False) and _ryzenadj_available:
        return _extras_ceilings_mw()
    return _standard_ceilings_mw()


# Plugging the charger in makes the firmware apply a profile of its own, and it
# lands after ours: measured on a Legion Go S, an apply at the moment of the
# transition wrote 40/43/53 and the attributes read back 10/15/20 - the
# low-power defaults - a fraction of a second later. One write at the instant
# the state changes is simply too early, so the values go back several times
# over the seconds that follow, until one of them is the last word.
#
# The Legion Go 1 does the same thing and takes longer about it, so its profile
# carries a ladder with a longer tail; _ac_settle_delays() reads whichever one
# belongs to this machine.
#
# Unplugging does not need this; it is included anyway because it costs one
# comparison and the firmware is free to grow the same behaviour there.
AC_SETTLE_DELAYS_S = (0.5, 1.5, 3.0, 6.0)


def _ac_settle_delays() -> tuple:
    return _device().ac_settle or AC_SETTLE_DELAYS_S

# What the last charger transition asked for. The ladder re-asserts this rather
# than the recorded active_* triplet, because a failed apply records nothing -
# and a failure is precisely when the ladder is needed. Reading active_* there
# would put back whatever ran before the transition, which with a per-game AC
# profile is the wrong half of it.
_ac_target: tuple = ()
# Every delayed charger ladder carries the generation that armed it. Any newer
# user action, game change or charger transition increments this and makes the
# old ladder a no-op before it reaches hardware.
_ac_generation: int = 0


# ── AC power detection ─────────────────────────────────────────────────────────

def _read_sysfs(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _get_ac_online() -> bool:
    """True when an external charger is present.

    Only Mains-type supplies count. The Legion Go 2 also exposes USB-C PD source
    PSYs (ucsi-source-psy-*, type=USB, scope=Device) whose `online` flag tracks the
    port's PD role, not whether the device is being powered - ORing those in made an
    unplug flicker straight back to "charging". ACAD (Mains) is the real signal, and
    BAT0 status is unreliable here because battery conservation mode reports
    "Not charging" even while on AC.
    """
    mains_seen = False
    for path in glob.glob("/sys/class/power_supply/*"):
        if _read_sysfs(os.path.join(path, "type")) != "Mains":
            continue
        mains_seen = True
        if _read_sysfs(os.path.join(path, "online")) == "1":
            return True
    if mains_seen:
        return False
    # No Mains supply exposed at all - fall back to battery status.
    status = _read_sysfs("/sys/class/power_supply/BAT0/status")
    return status not in ("", "Discharging", "Unknown")


# ── Charge limit ───────────────────────────────────────────────────────────────
#
# Two ways to reach it, same as the TDP limits. The kernel's own
# charge_control_end_threshold is preferred wherever a driver publishes it: it
# is the standard ABI, other tools understand it, and it survives this plugin
# being unloaded. The GZFD feature is the fallback for the kernels that have no
# such driver - the same interface the TDP path uses when it has to.

def _charge_limit_node() -> str:
    """The battery's charge threshold file, or ''."""
    for path in sorted(glob.glob(CHARGE_LIMIT_GLOB)):
        return path
    return ""


def _read_charge_limit() -> dict:
    """Whether charging is being held back, and by which layer."""
    node = _charge_limit_node()
    if node:
        raw = _read_sysfs(node)
        try:
            threshold = int(raw)
        except ValueError:
            threshold = 0
        if threshold:
            return {"supported": True, "enabled": threshold < CHARGE_FULL_PERCENT,
                    "threshold": threshold, "source": "sysfs", "path": node}

    if _acpi_ready(rescan=True):
        enabled = _acpi_charge_limit()
        if enabled is not None:
            return {"supported": True, "enabled": enabled,
                    "threshold": CHARGE_LIMIT_PERCENT if enabled else CHARGE_FULL_PERCENT,
                    "source": "acpi", "path": ltdp_acpi.PROC_CALL}

    return {"supported": False, "enabled": False, "threshold": None,
            "source": "", "path": ""}


def _acpi_charge_limit():
    """Indirection so the tests can replace one call rather than the transport."""
    return ltdp_acpi.get_charge_limit()


def _apply_charge_limit(enabled: bool) -> dict:
    """Hold the charge at 80 %, or let it fill. Returns the resulting state."""
    node = _charge_limit_node()
    want = CHARGE_LIMIT_PERCENT if enabled else CHARGE_FULL_PERCENT
    if node:
        try:
            with open(node, "w") as f:
                f.write(str(want))
        except OSError as e:
            decky.logger.warning(f"[ltdp] charge limit write failed on {node}: {e}")
        else:
            after = _read_charge_limit()
            if after.get("threshold") == want:
                decky.logger.info(f"[ltdp] charge limit -> {want} % (sysfs)")
                return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    if _acpi_ready() and ltdp_acpi.set_charge_limit(enabled):
        decky.logger.info(
            f"[ltdp] charge limit -> {'80 %' if enabled else 'full'} (firmware)")
        return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    return {"success": False, "stdout": "",
            "stderr": "this system exposes no charge limit control",
            "returncode": -1}


def _panel_is_active() -> bool:
    """True while the panel's lease is unexpired. See _PANEL_ACTIVE_TTL_S."""
    return _panel_active and time.monotonic() - _panel_active_ts < _PANEL_ACTIVE_TTL_S


def _pick_profile_values(p: dict, ac_online: bool) -> tuple[int, int, int]:
    if ac_online and p.get("ac_separate") and p.get("ac_spl") is not None:
        return (
            p["ac_spl"],
            p.get("ac_sppt", p.get("sppt", _defaults()["sppt"])),
            p.get("ac_fppt", p.get("fppt", _defaults()["fppt"])),
        )
    return (
        p.get("spl",  _defaults()["spl"]),
        p.get("sppt", _defaults()["sppt"]),
        p.get("fppt", _defaults()["fppt"]),
    )


# ── Persistence ────────────────────────────────────────────────────────────────

# Settings live in Decky's settings directory, not in the plugin directory. The
# plugin directory is wiped by every reinstall, and this plugin's own updater
# tells the user to uninstall before installing the new zip - which used to take
# the global settings and every per-game profile with it.
settings = SettingsManager(
    name="settings",
    settings_directory=decky.DECKY_PLUGIN_SETTINGS_DIR,
)

SETTINGS_KEY_SETTINGS      = "settings"
SETTINGS_KEY_GAME_PROFILES = "game_profiles"
SETTINGS_KEY_SCHEMA        = "schema_version"
CURRENT_SCHEMA             = 3

# Pre-schema-2 locations, inside the plugin directory. Read once by _migrate()
# and never written again.
LEGACY_SETTINGS_FILE = os.path.join(PLUGIN_DIR, "settings.json")
LEGACY_PROFILES_FILE = os.path.join(PLUGIN_DIR, "profiles.json")

# Schema 3: this plugin used to be installed as "LeGoTDP-LegionGo1", and Decky
# keys the settings directory on the plugin name - so the rename to LTDP would
# otherwise have looked to the user like every per-game profile was wiped.
# Only this plugin's own former name is read. Upstream LeGoTDP's directory is
# deliberately not touched: those settings belong to a different device table.
PREVIOUS_PLUGIN_NAMES = ("LeGoTDP-LegionGo1",)

# The enforce loop reads settings from an executor thread while RPC handlers
# write them from the event loop. Re-entrant because the write paths load first.
_settings_lock = threading.RLock()


async def _offload(fn, *args):
    """Run blocking work off the event loop.

    Settings I/O, sysfs reads and waiting on _settings_lock or _apply_lock all
    block. Decky gives each plugin its own process and loop, so blocking here
    does not stall other plugins - it stalls this one: every RPC the panel sends
    queues behind it, and neither the enforce loop nor the info loop ticks until
    it returns. _apply_lock alone can be held for a profile bounce plus three
    firmware writes.
    """
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def _read_key(key: str, default: dict) -> dict:
    """A private copy of one key. Callers clamp and mutate what they get back,
    and getSetting hands out a live reference into the manager's own dict - so
    without the copy those edits would land in the store uncommitted, and a
    later read() would silently drop them again."""
    with _settings_lock:
        settings.read()
        value = settings.getSetting(key, None)
        return copy.deepcopy(value) if isinstance(value, dict) else dict(default)


def _write_keys(values: dict[str, dict]) -> None:
    with _settings_lock:
        # Refresh first so a caller cannot commit a stale in-memory copy of an
        # unrelated key. All values in this transaction reach one JSON commit.
        settings.read()
        for key, value in values.items():
            settings.setSetting(key, value)
        settings.commit()


def _write_key(key: str, value: dict) -> None:
    _write_keys({key: value})


def _clamp_triplet(spl, sppt, fppt,
                   ceilings: tuple[int, int, int] | None = None) -> tuple[int, int, int]:
    """Enforce 5 W <= spl <= sppt <= fppt <= 50 W (milliwatts).

    SPPT/FPPT are offsets above SPL in the UI, so they can never sit below it.
    """
    try:
        spl, sppt, fppt = int(spl), int(sppt), int(fppt)
    except (TypeError, ValueError):
        return _defaults()["spl"], _defaults()["sppt"], _defaults()["fppt"]
    spl_max, sppt_max, fppt_max = ceilings or _ceilings_mw()
    spl  = max(HARD_MIN_MW, min(spl,  spl_max))
    fppt = max(spl,         min(fppt, fppt_max))
    sppt = max(spl,         min(sppt, min(sppt_max, fppt)))
    return spl, sppt, fppt


def _clamp_for_settings(state: dict, spl, sppt, fppt) -> tuple[int, int, int]:
    """Clamp a target to the range currently unlocked and actually available."""
    return _clamp_triplet(spl, sppt, fppt, _allowed_ceilings_mw(state))


def _load_settings() -> dict:
    s = _read_key(SETTINGS_KEY_SETTINGS, _defaults())
    s["spl"], s["sppt"], s["fppt"] = _clamp_triplet(
        s.get("spl",  _defaults()["spl"]),
        s.get("sppt", _defaults()["sppt"]),
        s.get("fppt", _defaults()["fppt"]),
    )
    if s.get("ac_spl") is not None:
        s["ac_spl"], s["ac_sppt"], s["ac_fppt"] = _clamp_triplet(
            s["ac_spl"],
            s.get("ac_sppt", s["ac_spl"]),
            s.get("ac_fppt", s["ac_spl"]),
        )
    if any(k in s for k in ("active_spl", "active_sppt", "active_fppt")):
        s["active_spl"], s["active_sppt"], s["active_fppt"] = _clamp_triplet(
            s.get("active_spl",  s["spl"]),
            s.get("active_sppt", s["sppt"]),
            s.get("active_fppt", s["fppt"]),
        )
    return s


def _save_settings(s: dict) -> None:
    _write_key(SETTINGS_KEY_SETTINGS, s)


# ── Per-game profiles ──────────────────────────────────────────────────────────

def _load_profiles() -> dict:
    profiles = _read_key(SETTINGS_KEY_GAME_PROFILES, {})
    for p in profiles.values():
        if not isinstance(p, dict):
            continue
        if p.get("spl") is not None:
            p["spl"], p["sppt"], p["fppt"] = _clamp_triplet(
                p["spl"], p.get("sppt", p["spl"]), p.get("fppt", p["spl"]))
        if p.get("ac_spl") is not None:
            p["ac_spl"], p["ac_sppt"], p["ac_fppt"] = _clamp_triplet(
                p["ac_spl"], p.get("ac_sppt", p["ac_spl"]), p.get("ac_fppt", p["ac_spl"]))
    return profiles


def _save_profiles(profiles: dict) -> None:
    _write_key(SETTINGS_KEY_GAME_PROFILES, profiles)


def _save_active(s: dict, spl: int, sppt: int, fppt: int) -> None:
    with _mutation_lock:
        s["active_spl"]  = spl
        s["active_sppt"] = sppt
        s["active_fppt"] = fppt
        _save_settings(s)


def _read_legacy(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _previous_store() -> dict:
    """The settings this plugin wrote under its previous name, or {}.

    Decky derives the settings directory from the plugin name, so a rename
    leaves the old store sitting next to the new one, full and unread.
    """
    root = os.path.dirname(decky.DECKY_PLUGIN_SETTINGS_DIR)
    for name in PREVIOUS_PLUGIN_NAMES:
        data = _read_legacy(os.path.join(root, name, "settings.json"))
        if data:
            return data
    return {}


def _migrate() -> None:
    """Fold older stores into this one.

    Two of them: the pre-1.5.0 files in the plugin directory, and the settings
    directory this plugin used before it was renamed to LTDP.

    Runs exactly once. Nothing is deleted: the old files disappear with the
    next reinstall anyway, and leaving them means a downgrade still finds its
    settings.
    """
    with _settings_lock:
        settings.read()
        try:
            schema = int(settings.getSetting(SETTINGS_KEY_SCHEMA, 1))
        except (TypeError, ValueError):
            schema = 1
        if schema >= CURRENT_SCHEMA:
            return

        legacy_settings = _read_legacy(LEGACY_SETTINGS_FILE)
        legacy_profiles = _read_legacy(LEGACY_PROFILES_FILE)

        # The rename first: it is the newer of the two stores, so anything it
        # holds should win over a pre-1.5.0 file left in the plugin directory.
        previous = _previous_store()
        if previous:
            adopted = []
            for key in (SETTINGS_KEY_SETTINGS, SETTINGS_KEY_GAME_PROFILES):
                value = previous.get(key)
                if isinstance(value, dict) and value                         and settings.getSetting(key, None) is None:
                    settings.setSetting(key, value)
                    adopted.append(key)
            if adopted:
                legacy_settings, legacy_profiles = {}, {}
                decky.logger.info(
                    f"[ltdp] adopted {', '.join(adopted)} from the settings this "
                    "plugin wrote under its previous name")

        if legacy_settings and settings.getSetting(SETTINGS_KEY_SETTINGS, None) is None:
            settings.setSetting(SETTINGS_KEY_SETTINGS, legacy_settings)
            decky.logger.info(
                f"[ltdp] migrated {LEGACY_SETTINGS_FILE} into the Decky settings store")
        if legacy_profiles and settings.getSetting(SETTINGS_KEY_GAME_PROFILES, None) is None:
            settings.setSetting(SETTINGS_KEY_GAME_PROFILES, legacy_profiles)
            decky.logger.info(
                f"[ltdp] migrated {len(legacy_profiles)} per-game profile(s) "
                f"from {LEGACY_PROFILES_FILE}")

        settings.setSetting(SETTINGS_KEY_SCHEMA, CURRENT_SCHEMA)
        settings.commit()


# ── ryzenadj binary ────────────────────────────────────────────────────────────

def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_ryzenadj() -> None:
    decky.logger.info(f"[ltdp] Downloading ryzenadj from {RYZENADJ_URL}")
    os.makedirs(BIN_DIR, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz")
    os.close(tmp_fd)
    bin_tmp = ""
    try:
        with open(tmp_path, "wb") as out:
            updater.download_to(RYZENADJ_URL, out, timeout=30)

        actual = _sha256_file(tmp_path)
        if actual != RYZENADJ_SHA256:
            raise RuntimeError(
                f"ryzenadj archive checksum mismatch: got {actual}, "
                f"expected {RYZENADJ_SHA256}")

        with tarfile.open(tmp_path, "r:gz") as tar:
            member = next(
                (m for m in tar.getmembers()
                 if os.path.basename(m.name) == "ryzenadj" and m.isfile()),
                None,
            )
            if member is None:
                raise RuntimeError("ryzenadj binary not found inside tarball")
            source = tar.extractfile(member)
            if source is None:
                raise RuntimeError("cannot read ryzenadj binary from tarball")
            bin_fd, bin_tmp = tempfile.mkstemp(prefix=".ryzenadj-", dir=BIN_DIR)
            with os.fdopen(bin_fd, "wb") as out, source:
                for chunk in iter(lambda: source.read(64 * 1024), b""):
                    out.write(chunk)
        os.chmod(bin_tmp, 0o755)
        binary_digest = _sha256_file(bin_tmp)
        if binary_digest != RYZENADJ_BINARY_SHA256:
            raise RuntimeError(
                f"ryzenadj binary checksum mismatch: got {binary_digest}, "
                f"expected {RYZENADJ_BINARY_SHA256}")
        os.replace(bin_tmp, BIN_PATH)
        bin_tmp = ""
        decky.logger.info(f"[ltdp] ryzenadj installed at {BIN_PATH}")
    finally:
        for path in (tmp_path, bin_tmp):
            if not path:
                continue
            try:
                os.unlink(path)
            except OSError:
                pass


# Where an already-installed ryzenadj might be. Only consulted when this
# plugin's own verified download fails: on a Legion Go 1 whose kernel has
# neither the Lenovo driver nor acpi_call, ryzenadj is the only way to set a
# limit at all, and refusing to use a copy that is already on the machine would
# turn "no network on first run" into "no TDP control".
RYZENADJ_SEARCH_PATHS = (
    "/usr/bin/ryzenadj",
    "/usr/local/bin/ryzenadj",
    "/bin/ryzenadj",
)

# Set only by the fallback above. Empty means the verified download is in use.
_system_ryzenadj: str = ""


def _find_system_ryzenadj() -> str:
    candidates = list(RYZENADJ_SEARCH_PATHS)
    candidates += [os.path.join(d, "ryzenadj")
                   for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    candidates += sorted(glob.glob(
        os.path.join(os.path.dirname(PLUGIN_DIR), "*", "bin", "ryzenadj")))
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


def _ryzenadj_binary() -> str:
    """The executable to run: this plugin's verified copy, or a system one."""
    if os.path.isfile(BIN_PATH):
        return BIN_PATH
    return _system_ryzenadj


def _ensure_ryzenadj() -> None:
    """Make a runnable ryzenadj available, or raise.

    The verified download is the wanted outcome and is always tried first. If
    it cannot be had - no network on first run, GitHub unreachable - a copy
    already installed on the system is used instead rather than leaving the
    machine with no working backend. That copy is not checksum-verified, so it
    is only ever reached after the verified path has failed, and it is said out
    loud in the log.
    """
    global _system_ryzenadj
    try:
        if not os.path.isfile(BIN_PATH) or _sha256_file(BIN_PATH) != RYZENADJ_BINARY_SHA256:
            if os.path.isfile(BIN_PATH):
                decky.logger.warning(
                    "[ltdp] existing ryzenadj failed integrity verification; replacing it")
                os.unlink(BIN_PATH)
            _download_ryzenadj()
    except Exception as e:
        fallback = _find_system_ryzenadj()
        if not fallback:
            raise
        _system_ryzenadj = fallback
        decky.logger.warning(
            f"[ltdp] could not install the verified ryzenadj ({e}); "
            f"falling back to the unverified copy already on this system at {fallback}")
        return
    _system_ryzenadj = ""
    mode = os.stat(BIN_PATH).st_mode
    if not (mode & stat.S_IXUSR):
        os.chmod(BIN_PATH, mode | 0o111)


# ── ryzenadj helpers ───────────────────────────────────────────────────────────

def _run_ryzenadj(args: list, timeout: float = 5.0) -> tuple[int, str, str]:
    """Run ryzenadj, return (returncode, stdout, stderr).
    Uses Popen so kill() after timeout never calls communicate() and blocks."""
    binary = _ryzenadj_binary()
    if not _ryzenadj_available or not binary or not os.path.isfile(binary):
        return -1, "", "verified ryzenadj is unavailable"
    proc = subprocess.Popen([binary] + args,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            decky.logger.warning("[ltdp] ryzenadj process could not be killed")
        decky.logger.warning(f"[ltdp] ryzenadj timed out: {args}")
        return -1, "", "timeout"


def _parse_ryzenadj_output(text: str) -> dict:
    values: dict = {}
    for line in text.splitlines():
        m = _ROW_RE.search(line)
        if not m:
            continue
        name  = m.group(1).strip().upper()
        value = float(m.group(2))
        if "STAPM" in name and "LIMIT" in name:
            values["spl_limit"] = value
        elif "STAPM" in name and "VALUE" in name:
            values["spl_value"] = value
        elif "FAST" in name and "LIMIT" in name:
            values["fppt_limit"] = value
        elif "FAST" in name and "VALUE" in name:
            values["fppt_value"] = value
        elif "SLOW" in name and "LIMIT" in name:
            values["sppt_limit"] = value
        elif "SLOW" in name and "VALUE" in name:
            values["sppt_value"] = value
        elif "PPT" in name and "LIMIT" in name and "APU" not in name and "sppt_limit" not in values:
            values["sppt_limit"] = value
        elif "PPT" in name and "VALUE" in name and "APU" not in name and "sppt_value" not in values:
            values["sppt_value"] = value
    return values


def _apply_ryzenadj(spl_mw: int, sppt_mw: int, fppt_mw: int) -> dict:
    if not _ryzenadj_lock.acquire(timeout=4.0):
        return {"success": False, "stdout": "", "stderr": "ryzenadj busy", "returncode": -1}
    try:
        rc, out, err = _run_ryzenadj([
            f"--stapm-limit={spl_mw}",
            f"--slow-limit={sppt_mw}",
            f"--fast-limit={fppt_mw}",
        ])
        decky.logger.info(f"[ltdp] ryzenadj apply {spl_mw//1000}W/{sppt_mw//1000}W/{fppt_mw//1000}W -> rc={rc}")
        return {"success": rc == 0, "stdout": out, "stderr": err, "returncode": rc}
    finally:
        _ryzenadj_lock.release()


# ── Lenovo WMI firmware attributes ─────────────────────────────────────────────

_wmi_root_cache: str | None = None


def _wmi_root() -> str:
    """The lenovo-wmi-other attributes directory, or the historical path.

    Globbed rather than hard-coded: the driver numbers its instance, and while
    it is -0 on every machine seen so far, a second Lenovo WMI device would
    move it. Re-probed while it is missing, because the driver can bind after
    the plugin has already started.
    """
    global _wmi_root_cache
    if _wmi_root_cache and os.path.isdir(_wmi_root_cache):
        return _wmi_root_cache
    found = sorted(p for p in glob.glob(WMI_ROOT_GLOB) if os.path.isdir(p))
    _wmi_root_cache = found[0] if found else None
    return _wmi_root_cache or WMI_ROOT


def _wmi_path(key: str, leaf: str) -> str:
    return os.path.join(_wmi_root(), WMI_ATTRS[key], leaf)


def _wmi_read(key: str, leaf: str) -> int | None:
    try:
        with open(_wmi_path(key, leaf)) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _wmi_caps() -> dict:
    """Firmware-reported {min,max} in watts per parameter, or {} when unavailable."""
    caps = {}
    for key in WMI_ATTRS:
        lo, hi = _wmi_read(key, "min_value"), _wmi_read(key, "max_value")
        if lo is None or hi is None:
            return {}
        caps[key] = {"min": lo, "max": hi}
    return caps


def _profile_path() -> str | None:
    """The platform-profile node whose choices include 'custom' (the tunable one)."""
    for path in glob.glob(PLATFORM_PROFILE_GLOB):
        try:
            with open(os.path.join(os.path.dirname(path), "choices")) as f:
                if "custom" in f.read().split():
                    return path
        except OSError:
            continue
    return None


def _read_profile(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_profile(path: str, value: str) -> bool:
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError:
        return False


def _profile_choices() -> list:
    """Everything the tunable platform profile will accept, or []."""
    path = _profile_path()
    if path is None:
        return []
    try:
        with open(os.path.join(os.path.dirname(path), "choices")) as f:
            return f.read().split()
    except OSError:
        return []


# ── Conflicting TDP controllers ────────────────────────────────────────────────
#
# Two things driving the same three limits fight, and the loser is whoever
# wrote first: the symptom is a TDP that will not stay put, which looks exactly
# like a bug in this plugin. None of this is blocked - the user may well want
# the other tool - but it is reported, so the cause is visible.

CONFLICTING_PROCESSES = {
    "hhd": "Handheld Daemon (hhd)",
    "adjustor": "Handheld Daemon TDP module (adjustor)",
    "powerstation": "PowerStation",
    "simple-ryzen-tdp": "Simple Ryzen TDP",
    "ryzenadjd": "ryzenadj daemon",
}

CONFLICTING_PLUGINS = {
    "SimpleDeckyTDP": "SimpleDeckyTDP",
    "PowerControl": "PowerControl",
    "LeGoTDP": "LeGoTDP (upstream build)",
    # This plugin's own former directory name. An install left behind from
    # before the rename is still a second copy driving the same three limits.
    "LeGoTDP-LegionGo1": "LTDP under its previous name",
}

_CONFLICT_CACHE_TTL_S = 20.0
_conflict_cache: list = []
_conflict_cache_ts: float = 0.0
_conflict_lock = threading.Lock()


def _running_process_names() -> set:
    names = set()
    for path in glob.glob("/proc/*/comm"):
        try:
            with open(path) as f:
                names.add(f.read().strip())
        except OSError:
            continue
    return names


def _detect_conflicts() -> list:
    """Other TDP controllers that are installed or running right now.

    Scanning /proc is cheap but not free and both the panel and the diagnostics
    ask for this, so the answer is held briefly.
    """
    global _conflict_cache, _conflict_cache_ts
    with _conflict_lock:
        if _conflict_cache_ts and time.monotonic() - _conflict_cache_ts < _CONFLICT_CACHE_TTL_S:
            return list(_conflict_cache)

    # Reported as {key, params} rather than as a finished sentence: the panel
    # speaks three languages and the backend speaks none of them. Anything that
    # renders text for the user gets the same treatment.
    found = []
    names = _running_process_names()
    for process, label in CONFLICTING_PROCESSES.items():
        if process in names:
            found.append({"key": "conflict.process", "params": {"name": label}})

    plugins_dir = os.path.dirname(PLUGIN_DIR)
    own = os.path.basename(PLUGIN_DIR)
    for directory, label in CONFLICTING_PLUGINS.items():
        if directory == own:
            continue
        if os.path.isdir(os.path.join(plugins_dir, directory)):
            found.append({"key": "conflict.plugin", "params": {"name": label}})

    with _conflict_lock:
        _conflict_cache, _conflict_cache_ts = list(found), time.monotonic()
    return found


def _write_ppt(spl_w: int, sppt_w: int, fppt_w: int) -> None:
    """Write the three limits, in an order that keeps SPL <= SPPT <= FPPT.

    The firmware holds that invariant across every intermediate state, not just
    the final one, so raising the sustained limit past the current fast limit in
    the first write is a request it can refuse outright. Going up, the ceiling
    moves first; coming down, the floor does.
    """
    current = {k: _wmi_read(k, "current_value") for k in WMI_ATTRS}
    raising = current.get("spl") is None or spl_w > current["spl"]
    order = (("fppt", fppt_w), ("sppt", sppt_w), ("spl", spl_w)) if raising \
        else (("spl", spl_w), ("sppt", sppt_w), ("fppt", fppt_w))
    for key, val in order:
        try:
            with open(_wmi_path(key, "current_value"), "w") as f:
                f.write(str(val))
        except OSError:
            pass


def _ppt_matches(spl_w: int, sppt_w: int, fppt_w: int) -> bool:
    return all(_wmi_read(k, "current_value") == v
               for k, v in (("spl", spl_w), ("sppt", sppt_w), ("fppt", fppt_w)))


# Verified on the Legion Go 2: the firmware only latches ppt_* writes when the
# platform profile transitions *into* 'custom'. Writing while already in custom is
# silently dropped, and entering custom resets the values to firmware defaults - so
# the reliable recipe is bounce-through-another-profile, then write.
def _apply_wmi(spl_w: int, sppt_w: int, fppt_w: int) -> dict:
    path = _profile_path()
    if path is None:
        return {"success": False, "stdout": "", "stderr": "no custom platform profile",
                "returncode": -1}

    # Fast path: if we can latch a write in place, skip the visible profile bounce.
    if _read_profile(path) == "custom":
        _write_ppt(spl_w, sppt_w, fppt_w)
        if _ppt_matches(spl_w, sppt_w, fppt_w):
            decky.logger.info(f"[ltdp] wmi apply {spl_w}W/{sppt_w}W/{fppt_w}W")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    # Force a real transition into custom, then write. Bounce via a low profile so the
    # momentary blip is downward, never a spike.
    bounce = "low-power"
    try:
        with open(os.path.join(os.path.dirname(path), "choices")) as f:
            choices = f.read().split()
        bounce = next((c for c in ("low-power", "balanced", "performance") if c in choices),
                      next((c for c in choices if c != "custom"), "custom"))
    except OSError:
        pass
    _write_profile(path, bounce)
    if not _write_profile(path, "custom"):
        return {"success": False, "stdout": "", "stderr": "cannot select custom profile",
                "returncode": -1}
    _write_ppt(spl_w, sppt_w, fppt_w)

    if not _ppt_matches(spl_w, sppt_w, fppt_w):
        mismatch = "; ".join(
            f"{WMI_ATTRS[k]}={_wmi_read(k, 'current_value')} want {v}"
            for k, v in (("spl", spl_w), ("sppt", sppt_w), ("fppt", fppt_w))
            if _wmi_read(k, "current_value") != v)
        return {"success": False, "stdout": "", "stderr": mismatch, "returncode": -1}
    decky.logger.info(f"[ltdp] wmi apply {spl_w}W/{sppt_w}W/{fppt_w}W (via bounce)")
    return {"success": True, "stdout": "", "stderr": "", "returncode": 0}


# ── RAPL package power ─────────────────────────────────────────────────────────

# None = never probed, "" = probed and not found. A miss is retried: powercap can
# register after the plugin starts, and remembering the failure forever left the
# package draw reading blank until the plugin was reloaded.
_rapl_dir: str | None = None
_rapl_probed_at: float = 0.0
_RAPL_RESCAN_S = 60.0
_rapl_last: tuple = ()


def _find_rapl_package() -> str | None:
    global _rapl_dir, _rapl_probed_at
    if _rapl_dir:
        return _rapl_dir
    now = time.monotonic()
    if _rapl_dir is not None and now - _rapl_probed_at < _RAPL_RESCAN_S:
        return None

    _rapl_probed_at = now
    _rapl_dir = ""
    for d in sorted(glob.glob(RAPL_GLOB)):
        try:
            with open(os.path.join(d, "name")) as f:
                if f.read().strip().startswith("package"):
                    _rapl_dir = d
                    break
        except OSError:
            continue
    return _rapl_dir or None


def _rapl_watts() -> float | None:
    """Average package draw since the previous call, in watts."""
    global _rapl_last
    d = _find_rapl_package()
    if not d:
        return None
    try:
        with open(os.path.join(d, "energy_uj")) as f:
            energy = int(f.read().strip())
    except (OSError, ValueError):
        return None
    now = time.monotonic()
    prev, _rapl_last = _rapl_last, (energy, now)
    if not prev:
        return None
    delta_e, delta_t = energy - prev[0], now - prev[1]
    if delta_t <= 0:
        return None
    if delta_e < 0:  # counter wrapped
        try:
            with open(os.path.join(d, "max_energy_range_uj")) as f:
                delta_e += int(f.read().strip())
        except (OSError, ValueError):
            return None
    return delta_e / delta_t / 1_000_000


# ── Temperature and fan readings ───────────────────────────────────────────────

_hwmon_cache: dict = {}


def _hwmon_name(path: str) -> str:
    return _read_sysfs(os.path.join(path, "name"))


def _find_hwmon(drivers: tuple, leaf_glob: str) -> str:
    """First hwmon node from `drivers` that has the file we want, or ''."""
    key = (drivers, leaf_glob)
    cached = _hwmon_cache.get(key)
    if cached and os.path.exists(cached):
        return cached
    for base in sorted(glob.glob(HWMON_GLOB)):
        if _hwmon_name(base) not in drivers:
            continue
        found = sorted(glob.glob(os.path.join(base, leaf_glob)))
        if found:
            _hwmon_cache[key] = found[0]
            return found[0]
    return ""


def _cpu_temp():
    """SoC temperature in °C, or None.

    Worth showing next to the watts on this machine: the BIOS lowers TDP by
    itself when the SoC gets hot, so a limit that is not being reached is
    either thermal protection or something else moving the limits - and the
    temperature is what tells those two apart.
    """
    node = _find_hwmon(CPU_TEMP_DRIVERS, "temp*_input")
    if not node:
        return None
    raw = _read_sysfs(node)
    try:
        return round(int(raw) / 1000.0, 1)
    except ValueError:
        return None


def _fan_rpms() -> list:
    """Fan speeds in RPM. Only the Lenovo driver publishes these."""
    speeds = []
    for base in sorted(glob.glob(HWMON_GLOB)):
        if _hwmon_name(base) not in FAN_HWMON_DRIVERS:
            continue
        for node in sorted(glob.glob(os.path.join(base, "fan*_input"))):
            try:
                speeds.append(int(_read_sysfs(node)))
            except ValueError:
                continue
    return speeds


# ── Fans ───────────────────────────────────────────────────────────────────────
#
# Only the acpi_call path reaches the curve: the in-kernel driver publishes fan
# speeds read-only, and the curve itself lives behind the GameZone method.

# The curve the enforce pass defends, and how many times it has tried. The
# firmware resets the curve whenever the power mode changes, which the plugin
# does on every TDP apply - so without this a fan mode would silently expire.
_fan_target: tuple = ()
_fan_attempts: int = 0
FAN_MAX_ATTEMPTS = 3


def _fan_available(rescan: bool = False) -> bool:
    return _acpi_ready(rescan)


def _read_fan_state() -> dict:
    # Asked for when the panel opens, which is exactly when someone who just
    # installed acpi_call is looking for the fan section to come alive.
    if not _fan_available(rescan=True):
        return {"supported": False, "mode": "auto", "curve": [], "full_speed": False}
    full = ltdp_acpi.get_full_fan_speed()
    return {
        "supported": True,
        "mode": _load_settings().get("fan_mode", "auto"),
        "curve": ltdp_acpi.get_fan_curve() or [],
        "full_speed": bool(full),
    }


def _apply_fan_mode(mode: str) -> dict:
    """Put the fans on one of the modes. Caller holds _mutation_lock."""
    global _fan_target, _fan_attempts
    if mode not in FAN_MODES:
        return {"success": False, "stdout": "", "stderr": f"unknown fan mode: {mode}",
                "returncode": -1}
    if not _fan_available():
        return {"success": False, "stdout": "",
                "stderr": "fan control needs the firmware interface (acpi_call)",
                "returncode": -1}

    _fan_attempts = 0
    if mode == "max":
        _fan_target = ()
        ok = ltdp_acpi.set_full_fan_speed(True)
        return {"success": ok, "stdout": "", "stderr": "" if ok else "firmware refused",
                "returncode": 0 if ok else -1}

    # Leaving max behind is a separate write, and has to happen first or the
    # curve below would be set on a machine still running its fans flat out.
    if ltdp_acpi.get_full_fan_speed():
        ltdp_acpi.set_full_fan_speed(False)

    if mode == "auto":
        _fan_target = ()
        ok = ltdp_acpi.reset_fan_curve()
        return {"success": ok, "stdout": "",
                "stderr": "" if ok else "could not hand the curve back to the firmware",
                "returncode": 0 if ok else -1}

    curve = tuple(ltdp_acpi.clamp_fan_curve(FAN_CURVES[mode]))
    ok = ltdp_acpi.set_fan_curve(curve)
    _fan_target = curve if ok else ()
    return {"success": ok, "stdout": "", "stderr": "" if ok else "firmware refused the curve",
            "returncode": 0 if ok else -1}


def _enforce_fan() -> None:
    """Put the curve back when a power-mode change has wiped it.

    Every TDP apply moves the firmware through its custom mode, and that resets
    the curve - so a fan mode that is set once does not stay set. Rewriting it
    is one ACPI call when it already matches, and after a few refusals this
    stands down exactly like the TDP drift pass does.
    """
    global _fan_attempts
    if not _fan_target or not _fan_available():
        return
    if _fan_attempts >= FAN_MAX_ATTEMPTS:
        return
    current = ltdp_acpi.get_fan_curve()
    if current and ltdp_acpi.curves_match(current, list(_fan_target)):
        _fan_attempts = 0
        return
    _fan_attempts += 1
    decky.logger.info(
        f"[ltdp] fan curve was reset, writing it back (attempt {_fan_attempts})")
    if not ltdp_acpi.set_fan_curve(list(_fan_target)) and _fan_attempts >= FAN_MAX_ATTEMPTS:
        decky.logger.warning("[ltdp] the firmware keeps refusing the fan curve, standing down")


# ── Apply dispatcher ───────────────────────────────────────────────────────────

_last_source: str = ""

# The triplet the hardware was last successfully asked for, in milliwatts.
# Needed because one of the three is not readable back on the ryzenadj path -
# see _adopt_unreadable_spl().
_applied_mw: tuple = ()

# When that happened, so the enforce pass can tell whether the info cache it is
# about to read predates the change it is checking.
_applied_at: float = 0.0


# Whether the acpi_call path answered when it was last probed. None = never
# probed; probing writes to /proc/acpi/call, so it is only ever attempted on a
# machine whose device profile says it speaks the Lenovo GameZone interface.
_acpi_available: bool = False


# acpi_call can arrive after the plugin has started: it is a DKMS module, and
# on SteamOS installing it is something the user does by hand, long after boot.
# Probed once at startup and then re-probed on demand, rate-limited - the same
# shape as the powercap lookup, and for the same reason.
_ACPI_RESCAN_S = 60.0
# None, not 0.0 - the same trap _wmi_verified_at documents a few hundred lines
# down. time.monotonic() counts from boot, so on a machine that has only just
# started 0.0 is a timestamp seconds in the past rather than "never", and the
# first re-probe never happened. Invisible on a console that has been on for
# hours; a freshly booted CI runner caught it immediately.
_acpi_probed_at: float | None = None


def _acpi_ready(rescan: bool = False) -> bool:
    """True when the firmware is reachable through acpi_call on this machine.

    `rescan` is for the paths a user is looking at when they wonder why a
    feature is missing - the fan section and the charge limit. The hot paths
    (applying limits, the enforce pass) read the cached answer instead: probing
    means a modprobe and a write to /proc/acpi/call, which is not something to
    do every five seconds on a machine that will never have the module.
    """
    global _acpi_available, _acpi_probed_at
    if not _device().supports_acpi_call:
        return False
    if not _acpi_available and rescan:
        now = time.monotonic()
        if _acpi_probed_at is None or now - _acpi_probed_at >= _ACPI_RESCAN_S:
            _acpi_probed_at = now
            # Drop the module's own "already tried" latch as well, or a
            # modprobe that failed before the user installed it would never
            # be attempted again.
            ltdp_acpi.reset_cache()
            _acpi_available = ltdp_acpi.available(force=True)
            if _acpi_available:
                decky.logger.info(
                    "[ltdp] acpi_call answered on a re-probe; the firmware "
                    "interface is available now")
    return _acpi_available


def _probe_backends() -> dict:
    """Work out what is actually available, in preference order.

    Called by the diagnostics panel, not on any hot path: it re-probes
    acpi_call, which means a write to /proc/acpi/call. Nothing here is a guess:
    the firmware attributes are looked for on disk, acpi_call is loaded and the
    GameZone method is asked to identify itself, and ryzenadj is only counted
    once its binary has been downloaded and verified.
    """
    global _acpi_available
    profile = _device()
    wmi_caps = _wmi_caps()
    report = {
        BACKEND_WMI: {
            "supported": BACKEND_WMI in profile.backends,
            "available": bool(wmi_caps) and _profile_path() is not None,
            "detail_key": "", "detail_params": {},
        },
        BACKEND_ACPI: {
            "supported": profile.supports_acpi_call,
            "available": False,
            "detail_key": "", "detail_params": {},
        },
        BACKEND_RYZENADJ: {
            "supported": BACKEND_RYZENADJ in profile.backends,
            "available": _ryzenadj_available,
            "detail_key": "", "detail_params": {},
        },
    }

    def detail(backend: str, key: str, **params) -> None:
        report[backend]["detail_key"] = key
        report[backend]["detail_params"] = params

    if wmi_caps and _profile_path() is None:
        detail(BACKEND_WMI, "backend.wmi.noCustomProfile")
    elif not wmi_caps:
        detail(BACKEND_WMI, "backend.wmi.absent")
    else:
        detail(BACKEND_WMI, "backend.wmi.ready")

    if profile.supports_acpi_call:
        _acpi_available = ltdp_acpi.available(force=True)
        report[BACKEND_ACPI]["available"] = _acpi_available
        if _acpi_available:
            detail(BACKEND_ACPI, "backend.acpi.mode",
                   mode=ltdp_acpi.mode_name(ltdp_acpi.get_mode()))
        else:
            detail(BACKEND_ACPI, "backend.acpi.absent")
    else:
        _acpi_available = False
        detail(BACKEND_ACPI, "backend.acpi.unused")

    if _ryzenadj_available and _system_ryzenadj:
        detail(BACKEND_RYZENADJ, "backend.ryzenadj.system", path=_system_ryzenadj)
    elif _ryzenadj_available:
        detail(BACKEND_RYZENADJ, "backend.ryzenadj.verified", path=BIN_PATH)
    elif profile.firmware_only:
        detail(BACKEND_RYZENADJ, "backend.ryzenadj.notUsed")
    else:
        detail(BACKEND_RYZENADJ, "backend.ryzenadj.absent")
    return report


def _active_backend() -> str:
    """The backend the next in-range apply would use."""
    for name in _device().backends:
        if name == BACKEND_WMI and _wmi_caps() and _profile_path() is not None:
            return name
        if name == BACKEND_ACPI and _acpi_ready():
            return name
        if name == BACKEND_RYZENADJ and _ryzenadj_available:
            return name
    return ""


def _within(caps: dict, triple_w: tuple) -> bool:
    return bool(caps) and all(caps[k]["min"] <= v <= caps[k]["max"] for k, v in triple_w)


def _apply_limits(spl_mw: int, sppt_mw: int, fppt_mw: int) -> dict:
    """Drive the highest-priority backend this machine has that can take the request.

    Firmware first, in whichever of its two forms is present: the in-kernel
    attributes when the Lenovo driver is loaded, the same firmware through
    acpi_call when it is not. ryzenadj is last, and is reached either because
    neither firmware path exists on this kernel or because the request is above
    what the firmware accepts - which is what the Extras range is.
    """
    global _last_source, _applied_mw, _applied_at
    spl_mw, sppt_mw, fppt_mw = _clamp_triplet(spl_mw, sppt_mw, fppt_mw)
    triple_w = (("spl", spl_mw // 1000), ("sppt", sppt_mw // 1000), ("fppt", fppt_mw // 1000))
    watts = tuple(v for _, v in triple_w)
    if not _apply_lock.acquire(timeout=8.0):
        return {"success": False, "stdout": "", "stderr": "apply busy", "returncode": -1}
    try:
        def _record(source: str, result: dict) -> dict:
            global _last_source, _applied_mw, _applied_at
            if result["success"]:
                _last_source = source
                _applied_mw, _applied_at = (spl_mw, sppt_mw, fppt_mw), time.monotonic()
                _invalidate_limits_cache()
            return result

        firmware_range = _standard_ceilings_mw()
        in_firmware_range = all(
            _fallback_min_w() <= v <= firmware_range[n] // 1000
            for n, (_, v) in enumerate(triple_w))
        last: dict | None = None

        for name in _device().backends:
            if name == BACKEND_WMI:
                caps = _wmi_caps()
                if not _within(caps, triple_w):
                    continue
                result = _record("wmi", _apply_wmi(*watts))
                if result["success"]:
                    return result
                last = result
                decky.logger.warning(
                    f"[ltdp] firmware attributes refused the write "
                    f"({result['stderr']}), trying the next backend")

            elif name == BACKEND_ACPI:
                if not _acpi_ready() or not in_firmware_range:
                    continue
                result = _record("acpi", ltdp_acpi.apply_limits(*watts))
                if result["success"]:
                    return result
                last = result
                decky.logger.warning(
                    f"[ltdp] acpi_call apply failed ({result['stderr']}), "
                    "trying the next backend")

            elif name == BACKEND_RYZENADJ:
                # Deliberately not gated on _ryzenadj_available: the runner
                # below already refuses when there is no verified binary, and
                # routing that decision through one place keeps the failure
                # message accurate rather than merely early.
                result = _record("ryzenadj", _apply_ryzenadj(spl_mw, sppt_mw, fppt_mw))
                if result["success"]:
                    return result
                last = result

        if last is not None:
            # "ryzenadj is unavailable" is true but unhelpful when the real
            # story is that no backend exists on this kernel at all.
            if (last.get("stderr") == "verified ryzenadj is unavailable"
                    and not _wmi_caps() and not _acpi_ready()):
                return {"success": False, "stdout": "",
                        "stderr": "no TDP backend is available on this system "
                                  "- see Diagnostics",
                        "returncode": -1}
            return last
        if _wmi_only():
            # Say what actually happened. ryzenadj is deliberately not
            # installed here, so falling through to it would only turn a
            # firmware refusal into a confusing "ryzenadj not found".
            return {"success": False, "stdout": "",
                    "stderr": "requested limits are outside what the firmware accepts",
                    "returncode": -1}
        return {"success": False, "stdout": "",
                "stderr": "no TDP backend is available on this system - see Diagnostics",
                "returncode": -1}
    finally:
        _apply_lock.release()


# The WMI attributes are the driver's record of its own writes, not a reading of
# the hardware, so anything that moves the limits without going through that
# interface leaves them reporting stale values and the enforce pass idle.
# Measured on the device: with the plugin holding 25/30/35 through WMI, an
# external drop to 15 W left the attributes still reporting 25/30/35, the panel
# showing 25/30/35, and zero re-apply attempts.
#
# `ryzenadj --info` is a live read and does see WMI-applied slow and fast
# correctly, so it can serve as a cross-check. Sparingly: it spawns a process,
# which is the cost the limits cache exists to avoid in the first place.
_WMI_VERIFY_EVERY_S = 30.0
# None, not 0.0. time.monotonic() counts from boot, so on a machine that has
# only just started 0.0 is a timestamp a few seconds in the past rather than
# "never" - which skipped the first cross-check for the first half minute of
# uptime. Invisible on a dev box or a console that has been on for hours; CI
# runs on a freshly booted runner and caught it immediately.
_wmi_verified_at: float | None = None


def _wmi_limits_overridden(want_w: tuple) -> bool:
    """True when a live read disagrees with what the firmware claims is set.

    Only SPPT and FPPT are compared. SPL cannot be read back through ryzenadj
    on this hardware (see _adopt_unreadable_spl), and the firmware's own
    reading of it is the thing under suspicion here.
    """
    global _wmi_verified_at
    if not _ryzenadj_available or not os.path.isfile(BIN_PATH):
        return False
    now = time.monotonic()
    if _wmi_verified_at is not None and now - _wmi_verified_at < _WMI_VERIFY_EVERY_S:
        return False
    _wmi_verified_at = now

    if not _ryzenadj_lock.acquire(timeout=2.0):
        return False
    try:
        rc, out, _ = _run_ryzenadj(["--info"], timeout=3.0)
    finally:
        _ryzenadj_lock.release()
    if rc != 0:
        return False

    live = _parse_ryzenadj_output(out)
    pairs = [(live.get("sppt_limit"), want_w[1]), (live.get("fppt_limit"), want_w[2])]
    if any(v is None for v, _ in pairs):
        return False
    return any(abs(v - w) > DRIFT_TOLERANCE_WMI_W for v, w in pairs)


def _wmi_profile_lost() -> bool:
    """True when the firmware has been knocked out of its custom power mode.

    Both firmware paths only honour a limit while the machine is in custom
    mode, and both keep reporting the last value they were given after
    something else - Steam, amd_pmf, gamezone, the Legion + Y shortcut on the
    Go 1 - has moved the mode. The values still read back correctly and no
    longer bind, which is precisely the case the enforce pass cannot see any
    other way.
    """
    if _last_source == "wmi":
        path = _profile_path()
        return path is not None and _read_profile(path) != "custom"
    if _last_source == "acpi":
        mode = ltdp_acpi.get_mode()
        return mode is not None and mode != ltdp_acpi.MODE_CUSTOM
    return False


# Reading limits over WMI is three sysfs reads. On the ryzenadj path it spawns a
# process, and the enforce loop asks every five seconds whether or not anyone has
# the panel open - so with Extras enabled that was a `ryzenadj --info` every five
# seconds forever, including mid-game. Serve a recent answer instead. The window
# is well inside the ryzenadj drift tolerance (6 W), which only exists to catch a
# post-resume reset, and _apply_limits drops the cache so a change we made is
# never hidden behind it.
_LIMITS_CACHE_TTL_S = 15.0
_limits_cache: dict = {}
_limits_cache_ts: float = 0.0
_limits_cache_lock = threading.Lock()


def _invalidate_limits_cache() -> None:
    global _limits_cache, _limits_cache_ts
    with _limits_cache_lock:
        _limits_cache, _limits_cache_ts = {}, 0.0


def _adopt_unreadable_spl(parsed: dict) -> dict:
    """Replace the STAPM read-back, which does not report what we asked for.

    Measured on a Legion Go 2 (Strix Point, ryzenadj 0.19.0) by sampling for a
    minute after each change with the plugin stopped:

        set stapm=15 slow=18 fast=25  ->  STAPM settles on 25.0, held for 60 s
        set stapm=40 slow=45 fast=47  ->  STAPM settles on ~46.6, wobbling
        set stapm=50 slow=50 fast=50  ->  STAPM settles on 50.0

    STAPM LIMIT follows the fast limit, never the value handed to
    --stapm-limit, and the SMU moves it by a few hundred milliwatts while it
    manages the budget. Sampled a second after a change it is somewhere in
    transit between the old value and the new one - which is where readings
    like 34.880 and 49.746 come from, and why matching it against fppt exactly
    does not work.

    Taking the row at face value put the FPPT number in the panel's SPL row,
    and handed the enforce loop a target it could never reach: three wasted
    ryzenadj re-applies on every change before it gave up and stood down.

    SPL is therefore not observable on this layer, so report what was applied.
    Slow and fast are honoured exactly, so drift is still caught through them -
    including a post-resume reset, which moves all three. The WMI path does not
    come through here; there all three are real registers and read back exact.
    """
    if _applied_mw and "spl_limit" in parsed:
        parsed["spl_limit"] = _applied_mw[0] / 1000
    return parsed


def _read_limits() -> dict:
    """Current limits in watts, read from whichever layer last applied them.

    The layers do not observe each other: after a ryzenadj write the firmware
    still reports its own stale bookkeeping, so reading the wrong one would
    misreport the active limits.

    Both firmware paths answer straight away and cost three reads, so neither
    goes through the cache below - that exists to keep the ryzenadj path from
    spawning a process every few seconds.
    """
    global _limits_cache, _limits_cache_ts
    if _last_source == "wmi":
        vals = {f"{k}_limit": _wmi_read(k, "current_value") for k in WMI_ATTRS}
        if all(v is not None for v in vals.values()):
            return {k: float(v) for k, v in vals.items()}

    if _last_source == "acpi":
        vals = ltdp_acpi.read_limits()
        if vals:
            return {f"{k}_limit": float(v) for k, v in vals.items()}

    with _limits_cache_lock:
        if _limits_cache and time.monotonic() - _limits_cache_ts < _LIMITS_CACHE_TTL_S:
            return dict(_limits_cache)

    if not _ryzenadj_lock.acquire(timeout=4.0):
        return {}
    try:
        rc, out, _ = _run_ryzenadj(["--info"], timeout=3.0)
    finally:
        _ryzenadj_lock.release()

    parsed = _adopt_unreadable_spl(_parse_ryzenadj_output(out)) if rc == 0 else {}
    if parsed:
        with _limits_cache_lock:
            _limits_cache, _limits_cache_ts = dict(parsed), time.monotonic()
    return parsed


# ── Info cache refresh ─────────────────────────────────────────────────────────

def _refresh_info_cache() -> None:
    global _info_cache_ts
    values = _read_limits()
    watts  = _rapl_watts()
    with _info_cache_lock:
        _info_cache_ts = time.monotonic()
        if values:
            _info_cache.clear()
            _info_cache.update(values)
        if watts is not None:
            _info_cache["package_draw"] = round(watts, 1)
        temp = _cpu_temp()
        if temp is not None:
            _info_cache["cpu_temp"] = temp
        rpms = _fan_rpms()
        if rpms:
            _info_cache["fan_rpm"] = rpms
        # Before the first apply there is nothing to report but the backend
        # that would be used, which is more honest than naming one at random.
        _info_cache["source"] = _last_source or _active_backend()


# ── Game detection ─────────────────────────────────────────────────────────────

def _get_running_appid() -> str:
    """Current Steam game appid, or ''.

    Prefer the frontend's Router-based value while it is fresh - the /proc scan below
    misses games running inside pressure-vessel/gamescope. Falls back to the scan when
    the frontend has gone quiet (panel closed)."""
    if time.monotonic() - _frontend_appid_ts < _FRONTEND_APPID_TTL:
        return _frontend_appid
    return _scan_proc_for_appid()


def _scan_proc_for_appid() -> str:
    # The Steam "reaper" wrapper (reaper SteamLaunch AppId=NNNN -- ...) runs outside
    # the game's pressure-vessel/gamescope sandbox, so its cmdline is the most reliable
    # background signal. Fall back to SteamAppId in the environ.
    for path in glob.glob("/proc/*/cmdline"):
        try:
            with open(path, "rb") as f:
                for arg in f.read().split(b"\x00"):
                    if arg.startswith(b"AppId="):
                        appid = arg[len(b"AppId="):].decode(errors="replace")
                        if appid and appid != "0":
                            return appid
        except OSError:
            continue
    for path in glob.glob("/proc/*/environ"):
        try:
            with open(path, "rb") as f:
                for entry in f.read().split(b"\x00"):
                    if entry.startswith(b"SteamAppId="):
                        appid = entry[len(b"SteamAppId="):].decode(errors="replace")
                        if appid and appid != "0":
                            return appid
        except OSError:
            continue
    return ""


# ── TDP enforce ────────────────────────────────────────────────────────────────

def _global_triplet(s: dict, ac_online: bool | None = None) -> tuple[int, int, int]:
    """The global target for the power source we are on.

    The global settings carry the same ac_separate / ac_* keys a per-game
    profile does, so the same picker serves both: with the switch off there is
    one set of numbers and the charger changes nothing, with it on the charger
    selects which set runs.
    """
    if ac_online is None:
        ac_online = _get_ac_online()
    return _clamp_for_settings(s, *_pick_profile_values(s, ac_online))


def _cancel_ac_settle() -> int:
    global _ac_target, _ac_generation
    _ac_generation += 1
    _ac_target = ()
    return _ac_generation


def _arm_ac_settle(target: tuple) -> int:
    global _ac_target, _ac_generation
    _ac_generation += 1
    _ac_target = tuple(target)
    return _ac_generation


def _apply_and_record(spl: int, sppt: int, fppt: int, why: str) -> dict:
    """Apply a triplet and remember it as the target the enforce pass defends."""
    with _mutation_lock:
        state = _load_settings()
        if not state.get("enabled", True):
            return {"success": False, "stdout": "", "stderr": "plugin disabled",
                    "returncode": -1}
        target = _clamp_for_settings(state, spl, sppt, fppt)
        result = _apply_limits(*target)
        if result["success"]:
            _save_active(state, *target)
            decky.logger.info(
                f"[ltdp] Applied {why}: "
                f"{target[0] // 1000}/{target[1] // 1000}/{target[2] // 1000} W")
        else:
            decky.logger.warning(
                f"[ltdp] Failed to apply {why}: "
                f"rc={result['returncode']} err={result['stderr']}")
        return result


def _target_matches(target: tuple) -> bool:
    """True when the readable limits agree with a milliwatt target."""
    values = _read_limits()
    current = tuple(values.get(f"{key}_limit") for key in ("spl", "sppt", "fppt"))
    if any(value is None for value in current):
        return False
    tolerance = _drift_tolerance()
    wanted = tuple(value / 1000 for value in target)
    return all(abs(actual - expected) <= tolerance
               for actual, expected in zip(current, wanted))


def _reapply_current_target(expected_generation: int | None = None) -> bool:
    """Re-assert whatever the enforce pass is currently defending.

    Returns True once the hardware already agrees, so the caller can stop early
    rather than keep writing at something that has settled.
    """
    global _ac_target
    with _mutation_lock:
        if expected_generation is not None and expected_generation != _ac_generation:
            return True
        s = _load_settings()
        if not s.get("enabled", True):
            _cancel_ac_settle()
            return True
        target = _ac_target or _clamp_for_settings(
            s,
            s.get("active_spl",  s.get("spl",  _defaults()["spl"])),
            s.get("active_sppt", s.get("sppt", _defaults()["sppt"])),
            s.get("active_fppt", s.get("fppt", _defaults()["fppt"])),
        )
        if _target_matches(target):
            _ac_target = ()
            return True
        _apply_and_record(*target, "TDP after a charger transition")
        if _target_matches(target):
            _ac_target = ()
            return True
        return False


def _check_and_enforce_locked() -> dict:
    """One enforce pass.

    Returns the events the caller should emit. This runs in an executor thread,
    which cannot await decky.emit itself, so the async loop above does the
    emitting - that is what lets the panel stop polling for the charger state.
    """
    global _current_game_id, _current_ac_online

    s = _load_settings()
    if not s.get("enabled", True):
        return {}

    appid    = _get_running_appid()
    ac_now   = _get_ac_online()
    ac_changed = ac_now != _current_ac_online
    _current_ac_online = ac_now
    events = {"power_source": {"ac": ac_now}} if ac_changed else {}

    game_changed = appid != _current_game_id

    if game_changed or ac_changed:
        prev = _current_game_id if game_changed else appid
        _current_game_id = appid

        profile = _load_profiles().get(appid) if appid else None
        if profile is not None:
            trigger = "AC state change" if ac_changed else "game launch"
            target = _clamp_for_settings(s, *_pick_profile_values(profile, ac_now))
            if ac_changed:
                events["_resettle_generation"] = _arm_ac_settle(target)
            else:
                _cancel_ac_settle()
            _apply_and_record(
                *target, f"game profile for app={appid} on {trigger} (ac={ac_now})")
            return events

        # Nothing per-game applies, so the global settings are what should be
        # running. Skipping this would leave the enforce pass below defending a
        # stale active_* triplet left over from whatever ran last.
        if appid:
            why = f"global TDP, app={appid} has no profile"
        elif prev:
            why = "global TDP, game exited"
        else:
            why = f"global TDP on AC change (ac={ac_now})"
        # ac_now was read at the top of this pass; reuse it rather than asking
        # the power supply again and risking two different answers in one pass.
        target = _global_triplet(s, ac_now)
        if ac_changed:
            events["_resettle_generation"] = _arm_ac_settle(target)
        else:
            _cancel_ac_settle()
        _apply_and_record(*target, why)
        return events

    _enforce_fan()
    _enforce_target(_clamp_for_settings(
        s,
        s.get("active_spl",  s.get("spl",  _defaults()["spl"])),
        s.get("active_sppt", s.get("sppt", _defaults()["sppt"])),
        s.get("active_fppt", s.get("fppt", _defaults()["fppt"])),
    ))
    return events


def _check_and_enforce() -> dict:
    with _mutation_lock:
        return _check_and_enforce_locked()


# WMI reads back the exact value we wrote, so a tight tolerance is right there. The
# ryzenadj path reports STAPM LIMIT for SPL, which the firmware manages dynamically
# (it drifts several watts below the set point under load), so comparing it tightly
# made the loop re-apply forever. A wide band there still catches a real reset - after
# resume the SMU drops to firmware defaults, which is a double-digit gap.
DRIFT_TOLERANCE_WMI_W      = 1.0
DRIFT_TOLERANCE_ACPI_W     = 1.0
DRIFT_TOLERANCE_RYZENADJ_W = 6.0
DRIFT_MAX_ATTEMPTS = 3


def _drift_tolerance() -> float:
    """How far the hardware may sit from the target before it counts as drift.

    Both firmware paths read back the exact value that was written, so a watt
    is already generous there. The ryzenadj path reports STAPM LIMIT for SPL,
    which the firmware manages dynamically, so it needs a band wide enough not
    to chase the SMU around - wide enough still to catch a post-resume reset,
    which is a double-digit gap.
    """
    if _last_source == "wmi":
        return DRIFT_TOLERANCE_WMI_W
    if _last_source == "acpi":
        return DRIFT_TOLERANCE_ACPI_W
    return DRIFT_TOLERANCE_RYZENADJ_W

_drift_target:   tuple = ()
_drift_settled:  tuple = ()
_drift_attempts: int   = 0


def _enforce_target(want: tuple) -> None:
    """Re-apply `want` when the hardware has drifted off it.

    Some targets are simply unreachable - the SMU silently caps slow-limit around
    50 W, for instance - and chasing those forever re-ran ryzenadj every 5 s and
    flooded the log. After a few failed attempts we accept whatever the hardware
    settled on, and only act again if it moves away from that.
    """
    global _drift_target, _drift_settled, _drift_attempts

    if want != _drift_target:
        _drift_target, _drift_settled, _drift_attempts = want, (), 0

    # Only reuse the panel's cache if it was filled after the last apply. It is
    # refreshed on its own two-second cadence, so a pass running right after a
    # change would otherwise compare the new target against a snapshot taken
    # before it - which reported a drift that had not happened and spent a
    # redundant apply correcting it. Visible in the journal as a "TDP drift"
    # line one second after every slider move.
    with _info_cache_lock:
        parsed = dict(_info_cache) if _panel_is_active() and _info_cache_ts > _applied_at else {}
    if not parsed:
        parsed = _read_limits()
    cur = tuple(parsed.get(f"{k}_limit") for k in ("spl", "sppt", "fppt"))
    if any(v is None for v in cur):
        return

    want_w    = tuple(v / 1000 for v in want)
    reference = _drift_settled or want_w
    tolerance = _drift_tolerance()
    # The WMI attributes keep reporting the last value even after the profile leaves
    # 'custom', so a matching read is not proof the limit is actually enforced - force
    # a re-apply (which re-selects custom) when we detect that. For the same reason
    # a matching read is no proof nobody else moved the limits, hence the live
    # cross-check; both make `cur` unreliable rather than merely stale.
    profile_lost = _wmi_profile_lost()
    overridden = _last_source == "wmi" and _wmi_limits_overridden(want_w)
    if not (profile_lost or overridden) \
            and all(abs(c - r) <= tolerance for c, r in zip(cur, reference)):
        # The retry budget is for consecutive failures to reach a target, not
        # the lifetime count of unrelated drifts. A confirmed real target starts
        # the next recovery from a full budget.
        if not _drift_settled:
            _drift_attempts = 0
        return

    if profile_lost:
        decky.logger.info("[ltdp] platform profile left 'custom', re-asserting limits")
        _drift_settled, _drift_attempts = (), 0

    if overridden:
        decky.logger.info(
            "[ltdp] a live read disagrees with the firmware attributes, "
            "something moved the limits behind us - re-asserting")
        _drift_settled, _drift_attempts = (), 0

    if _drift_settled:
        # Moved off the value we had accepted, so something external changed it.
        # Give the real target another go.
        _drift_settled, _drift_attempts = (), 0

    if _drift_attempts >= DRIFT_MAX_ATTEMPTS:
        _drift_settled = cur
        decky.logger.warning(
            f"[ltdp] target {want_w} unreachable after {_drift_attempts} attempts, "
            f"accepting {cur} and standing down")
        return

    _drift_attempts += 1
    decky.logger.info(
        f"[ltdp] TDP drift {cur} -> {want_w}, re-applying (attempt {_drift_attempts})")
    result = _apply_limits(*want)
    if not result["success"]:
        decky.logger.warning(
            f"[ltdp] drift re-apply failed rc={result['returncode']} err={result['stderr']}")


def _restore_defaults_locked() -> dict:
    """Hand control back to firmware. Caller must hold _mutation_lock."""
    global _last_source, _applied_mw, _applied_at
    global _drift_target, _drift_settled, _drift_attempts
    if not _apply_lock.acquire(timeout=8.0):
        return {"success": False, "stdout": "", "stderr": "apply busy", "returncode": -1}
    try:
        _drift_target, _drift_settled, _drift_attempts = (), (), 0
        path = _profile_path()
        if _wmi_caps() and path and _write_profile(path, "balanced"):
            _last_source, _applied_mw, _applied_at = "", (), 0.0
            _invalidate_limits_cache()
            decky.logger.info("[ltdp] restore_defaults: platform profile -> balanced")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
        # Same idea one layer down: on a kernel without the Lenovo driver the
        # only way back is to put the firmware into one of Lenovo's own power
        # modes, which is what leaving custom mode means.
        if _acpi_ready() and ltdp_acpi.restore_mode(ltdp_acpi.MODE_BALANCED):
            _last_source, _applied_mw, _applied_at = "", (), 0.0
            _invalidate_limits_cache()
            decky.logger.info("[ltdp] restore_defaults: firmware power mode -> balanced")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
        if not _ryzenadj_lock.acquire(timeout=4.0):
            return {"success": False, "stdout": "", "stderr": "ryzenadj busy", "returncode": -1}
        try:
            rc, out, err = _run_ryzenadj(["--max-performance"], timeout=5.0)
            if rc == 0:
                _last_source, _applied_mw, _applied_at = "", (), 0.0
                _invalidate_limits_cache()
            decky.logger.info(f"[ltdp] restore_defaults rc={rc}")
            return {"success": rc == 0, "stdout": out, "stderr": err, "returncode": rc}
        finally:
            _ryzenadj_lock.release()
    finally:
        _apply_lock.release()


def _clamp_profile(profile: dict, ceilings: tuple[int, int, int]) -> None:
    if profile.get("spl") is not None:
        before = (profile["spl"], profile.get("sppt", profile["spl"]),
                  profile.get("fppt", profile["spl"]))
        after = _clamp_triplet(
            profile["spl"], profile.get("sppt", profile["spl"]),
            profile.get("fppt", profile["spl"]), ceilings)
        profile["spl"], profile["sppt"], profile["fppt"] = after
        if after != before:
            profile["preset"] = "custom"
    if profile.get("ac_spl") is not None:
        before = (profile["ac_spl"], profile.get("ac_sppt", profile["ac_spl"]),
                  profile.get("ac_fppt", profile["ac_spl"]))
        after = _clamp_triplet(
            profile["ac_spl"], profile.get("ac_sppt", profile["ac_spl"]),
            profile.get("ac_fppt", profile["ac_spl"]), ceilings)
        profile["ac_spl"], profile["ac_sppt"], profile["ac_fppt"] = after
        if after != before:
            profile["ac_preset"] = "custom"


def _lock_extras_state(state: dict, profiles: dict) -> tuple:
    """Clamp every persisted target to firmware limits and return the active one."""
    ceilings = _standard_ceilings_mw()
    global_before = (state.get("spl", _defaults()["spl"]),
                     state.get("sppt", _defaults()["sppt"]),
                     state.get("fppt", _defaults()["fppt"]))
    state["spl"], state["sppt"], state["fppt"] = _clamp_triplet(
        state.get("spl", _defaults()["spl"]),
        state.get("sppt", _defaults()["sppt"]),
        state.get("fppt", _defaults()["fppt"]), ceilings)
    if (state["spl"], state["sppt"], state["fppt"]) != global_before:
        state["active_preset"] = "custom"
    # The global AC triplet is a persisted target like any other, so locking
    # Extras has to bring it back inside the firmware range too - otherwise the
    # next charger transition would re-apply a value that is no longer allowed.
    if state.get("ac_spl") is not None:
        ac_before = (state["ac_spl"], state.get("ac_sppt", state["ac_spl"]),
                     state.get("ac_fppt", state["ac_spl"]))
        state["ac_spl"], state["ac_sppt"], state["ac_fppt"] = _clamp_triplet(
            *ac_before, ceilings)
        if (state["ac_spl"], state["ac_sppt"], state["ac_fppt"]) != ac_before:
            state["ac_preset"] = "custom"
    if any(key in state for key in ("active_spl", "active_sppt", "active_fppt")):
        active = _clamp_triplet(
            state.get("active_spl", state["spl"]),
            state.get("active_sppt", state["sppt"]),
            state.get("active_fppt", state["fppt"]), ceilings)
    else:
        active = (state["spl"], state["sppt"], state["fppt"])
    state["active_spl"], state["active_sppt"], state["active_fppt"] = active
    for profile in profiles.values():
        if isinstance(profile, dict):
            _clamp_profile(profile, ceilings)
    return active


# ── Plugin class ───────────────────────────────────────────────────────────────

class Plugin:
    _ready: bool = False
    # Surfaced through is_ready() so a failed start shows up in the panel
    # instead of leaving the user with sliders that silently do nothing.
    _setup_error: str | None = None
    _tasks: list = []

    async def is_ready(self) -> dict:
        return {"ready": self._ready, "error": self._setup_error or ""}

    async def get_version(self) -> dict:
        return {"version": updater.plugin_version()}

    async def get_settings(self) -> dict:
        return await _offload(_load_settings)

    async def get_power_source(self) -> dict:
        return {"ac": await _offload(_get_ac_online)}

    async def get_fan_state(self) -> dict:
        """Fan mode, the curve in force, and whether the fans are flat out."""
        return await _offload(_read_fan_state)

    async def set_fan_mode(self, mode: str) -> dict:
        """Auto, one of the three curves, or full speed.

        Persisted like the TDP settings, and re-asserted by the enforce pass:
        the firmware wipes the curve every time the power mode moves, which is
        every time a TDP value is applied.
        """
        def _do() -> dict:
            with _mutation_lock:
                result = _apply_fan_mode(mode)
                if result["success"]:
                    state = _load_settings()
                    state["fan_mode"] = mode
                    _save_settings(state)
                return result
        result = await _offload(_do)
        decky.logger.info(f"[ltdp] fan_mode={mode} success={result['success']}")
        return result

    async def get_charge_limit(self) -> dict:
        """Whether charging is being held at 80 %, and whether that is offered."""
        return await _offload(_read_charge_limit)

    async def set_charge_limit(self, enabled: bool) -> dict:
        """Hold the charge at 80 %, or let the battery fill.

        Persisted separately from the TDP settings and deliberately not tied to
        the plugin's enable switch: turning TDP control off is a statement about
        power limits, not about how the battery should be charged.
        """
        def _do() -> dict:
            with _mutation_lock:
                result = _apply_charge_limit(enabled)
                if result["success"]:
                    state = _load_settings()
                    state["charge_limit"] = bool(enabled)
                    _save_settings(state)
                return result
        result = await _offload(_do)
        decky.logger.info(
            f"[ltdp] charge_limit={enabled} success={result['success']}")
        return result

    async def set_language(self, language: str) -> dict:
        """Remember the panel's language.

        Kept in the settings store rather than in the frontend, because the
        frontend is torn down and rebuilt every time the Quick Access Menu is
        opened, and a language that resets itself is worse than no choice at
        all. Anything unrecognised is refused rather than stored.
        """
        def _do() -> dict:
            if language not in SUPPORTED_LANGUAGES:
                return {"success": False, "stdout": "",
                        "stderr": f"unsupported language: {language}",
                        "returncode": -1}
            with _mutation_lock:
                state = _load_settings()
                state["language"] = language
                _save_settings(state)
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
        result = await _offload(_do)
        decky.logger.info(f"[ltdp] language={language} success={result['success']}")
        return result

    async def set_global_ac_separate(self, enabled: bool) -> dict:
        """Turn the global charger profile on or off.

        Switching it on seeds the AC set from the battery one, so the machine
        keeps running what it was running until the user changes something.
        Switching it off drops back to a single set for both power sources.
        Whatever should be running afterwards is applied straight away, unless
        a per-game profile is in charge - that outranks the global settings and
        must not be disturbed from here.
        """
        def _do() -> dict:
            with _mutation_lock:
                s = _load_settings()
                if enabled:
                    if s.get("ac_spl") is None:
                        s["ac_spl"] = s.get("spl", _defaults()["spl"])
                        s["ac_sppt"] = s.get("sppt", _defaults()["sppt"])
                        s["ac_fppt"] = s.get("fppt", _defaults()["fppt"])
                        s["ac_preset"] = s.get("active_preset", "")
                    s["ac_separate"] = True
                else:
                    s["ac_separate"] = False

                appid = _get_running_appid()
                governed_by_game = bool(appid) and _load_profiles().get(appid) is not None
                if s.get("enabled", True) and not governed_by_game:
                    target = _global_triplet(s)
                    result = _apply_limits(*target)
                    if not result["success"]:
                        return result
                    s["active_spl"], s["active_sppt"], s["active_fppt"] = target
                    _cancel_ac_settle()
                _save_settings(s)
                return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
        result = await _offload(_do)
        decky.logger.info(
            f"[ltdp] global AC profile separate={enabled} success={result['success']}")
        return result

    async def get_extras_unlocked(self) -> bool:
        s = await _offload(_load_settings)
        return s.get("extras_unlocked", False)

    async def set_extras_unlocked(self, enabled: bool) -> dict:
        def _do():
            with _mutation_lock:
                if enabled and (_wmi_only() or not _ryzenadj_available):
                    return {"success": False, "stdout": "",
                            "stderr": "Extras is unavailable because ryzenadj is not ready",
                            "returncode": -1}
                s = _load_settings()
                profiles = _load_profiles()
                if enabled:
                    s["extras_unlocked"] = True
                    _save_settings(s)
                    return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

                active = _lock_extras_state(s, profiles)
                if s.get("enabled", True):
                    result = _apply_limits(*active)
                    if not result["success"]:
                        return result
                s["extras_unlocked"] = False
                _write_keys({SETTINGS_KEY_SETTINGS: s,
                             SETTINGS_KEY_GAME_PROFILES: profiles})
                _cancel_ac_settle()
                return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
        result = await _offload(_do)
        decky.logger.info(f"[ltdp] extras_unlocked={enabled} success={result['success']}")
        return result

    async def get_game_profile(self, app_id: str) -> dict:
        def _do() -> dict:
            p = _load_profiles().get(app_id)
            if p is None:
                return {"exists": False, "profile": {}, "ac_separate": False, "ac_profile": {}}
            spl  = p.get("spl",  _defaults()["spl"])
            sppt = p.get("sppt", _defaults()["sppt"])
            fppt = p.get("fppt", _defaults()["fppt"])
            return {
                "exists":      True,
                "profile":     {"spl": spl, "sppt": sppt, "fppt": fppt,
                                "preset": p.get("preset", "")},
                "ac_separate": p.get("ac_separate", False),
                "ac_profile":  {"spl": p.get("ac_spl", spl), "sppt": p.get("ac_sppt", sppt),
                                "fppt": p.get("ac_fppt", fppt),
                                "ac_preset": p.get("ac_preset", "")},
            }
        return await _offload(_do)

    async def set_game_ac_profile(self, app_id: str, spl: int, sppt: int, fppt: int, ac_separate: bool, preset_name: str = "") -> dict:
        def _do() -> dict:
            with _mutation_lock:
                if not app_id or _get_running_appid() != app_id:
                    return {"success": False, "stderr": "game is no longer active",
                            "stdout": "", "returncode": -1}
                state = _load_settings()
                if not state.get("enabled", True):
                    return {"success": False, "stderr": "plugin disabled",
                            "stdout": "", "returncode": -1}
                ac = _clamp_for_settings(state, spl, sppt, fppt)
                profiles = _load_profiles()
                existing = profiles.get(app_id, {})
                p = existing if isinstance(existing, dict) else {}
                p.update({"ac_separate": ac_separate,
                          "ac_spl": ac[0], "ac_sppt": ac[1], "ac_fppt": ac[2]})
                if preset_name:
                    p["ac_preset"] = preset_name
                profiles[app_id] = p

                want = None
                if _get_ac_online():
                    if ac_separate:
                        want = ac
                    elif all(p.get(k) is not None for k in ("spl", "sppt", "fppt")):
                        want = _clamp_for_settings(state, p["spl"], p["sppt"], p["fppt"])
                if want is not None:
                    result = _apply_limits(*want)
                    if not result["success"]:
                        return result
                    state["active_spl"], state["active_sppt"], state["active_fppt"] = want
                    _cancel_ac_settle()

                _write_keys({SETTINGS_KEY_SETTINGS: state,
                             SETTINGS_KEY_GAME_PROFILES: profiles})
                decky.logger.info(
                    f"[ltdp] Saved AC profile: app={app_id} separate={ac_separate}")
                return {"success": True, "stderr": "", "stdout": "", "returncode": 0}
        return await _offload(_do)

    async def delete_game_profile(self, app_id: str) -> dict:
        def _do() -> dict:
            with _mutation_lock:
                profiles = _load_profiles()
                profiles.pop(app_id, None)
                state = _load_settings()
                if state.get("enabled", True) and _get_running_appid() == app_id:
                    target = _global_triplet(state)
                    result = _apply_limits(*target)
                    if not result["success"]:
                        return result
                    state["active_spl"], state["active_sppt"], state["active_fppt"] = target
                    _cancel_ac_settle()
                _write_keys({SETTINGS_KEY_SETTINGS: state,
                             SETTINGS_KEY_GAME_PROFILES: profiles})
                return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
        result = await _offload(_do)
        decky.logger.info(
            f"[ltdp] Deleted game profile: app={app_id} success={result['success']}")
        return result

    async def set_plugin_enabled(self, enabled: bool) -> dict:
        def _do() -> dict:
            with _mutation_lock:
                state = _load_settings()
                if not enabled:
                    result = _restore_defaults_locked()
                    if not result["success"]:
                        return result
                    state["enabled"] = False
                    _save_settings(state)
                    _cancel_ac_settle()
                    return result

                target = _clamp_for_settings(
                    state,
                    state.get("active_spl", state.get("spl", _defaults()["spl"])),
                    state.get("active_sppt", state.get("sppt", _defaults()["sppt"])),
                    state.get("active_fppt", state.get("fppt", _defaults()["fppt"])),
                )
                result = _apply_limits(*target)
                if not result["success"]:
                    return result
                state["enabled"] = True
                state["active_spl"], state["active_sppt"], state["active_fppt"] = target
                _save_settings(state)
                _cancel_ac_settle()
                return result
        result = await _offload(_do)
        decky.logger.info(f"[ltdp] Plugin enabled={enabled} success={result['success']}")
        return result

    async def get_caps(self) -> dict:
        """The slider range for this machine, in watts.

        `std` is what the firmware accepts and `max` is the Extras range, which
        only exists where ryzenadj can reach past the firmware. Neither is a
        guess: the firmware's own min_value/max_value win wherever the kernel
        driver publishes them, and the device profile's documented range is the
        fallback for the acpi_call path, which has nothing equivalent to read.
        """
        def _do() -> dict:
            caps = _wmi_caps()
            profile = _device()
            fallback = _fallback_std_w()
            std = {k: caps[k]["max"] for k in WMI_ATTRS} if caps else dict(fallback)
            mins = ({k: max(caps[k]["min"], HARD_MIN_MW // 1000) for k in WMI_ATTRS}
                    if caps else {k: _fallback_min_w() for k in WMI_ATTRS})
            extras_available = not _wmi_only() and _ryzenadj_available
            extras = _extras_ceilings_mw()
            return {
                # One number, kept for the panel's single SPL floor.
                "min": min(mins.values()),
                "mins": mins,
                "std": std,
                # ryzenadj is not installed on firmware-only machines, so the
                # two ranges are the same there and the frontend hides the
                # Extras switch rather than offering a range nothing applies.
                "max": dict(std) if not extras_available
                       else {k: extras[n] // 1000
                             for n, k in enumerate(("spl", "sppt", "fppt"))},
                "wmi": bool(caps),
                "extras": extras_available,
                "presets": _presets(),
                "backend": _active_backend(),
                "device": {"key": profile.key, "label": profile.label,
                           "short": profile.short},
                "conflicts": _detect_conflicts(),
            }
        return await _offload(_do)

    async def get_diagnostics(self) -> dict:
        """Everything needed to tell whether this machine is being driven, and how.

        This is the panel's half of scripts/ltdp-diagnostics.sh: the same
        facts, gathered the same way, without needing a terminal.
        """
        def _do() -> dict:
            profile = _device()
            backends = _probe_backends()
            caps = _wmi_caps()
            fallback = _fallback_std_w()
            limits = _read_limits()
            pp_path = _profile_path()
            with _info_cache_lock:
                draw = _info_cache.get("package_draw")
            ranges = {}
            for key in ("spl", "sppt", "fppt"):
                if caps:
                    ranges[key] = {"min": caps[key]["min"], "max": caps[key]["max"],
                                   "source": "firmware"}
                else:
                    ranges[key] = {"min": _fallback_min_w(), "max": fallback[key],
                                   "source": "device profile"}
            return {
                "device": profile.label,
                "device_key": profile.key,
                "dmi": {
                    "product_name": _dmi("product_name"),
                    "product_version": _dmi("product_version"),
                    "product_family": _dmi("product_family"),
                    "bios_version": _dmi("bios_version"),
                    "board_name": _dmi("board_name"),
                },
                "bios": {
                    "raw": _dmi("bios_version"),
                    "number": ltdp_device.bios_number(_dmi("bios_version")),
                    "baseline": profile.bios_baseline,
                    "status": profile.bios_status(
                        ltdp_device.bios_number(_dmi("bios_version"))),
                },
                "cpu": ltdp_device.cpu_model() or profile.cpu_label,
                "kernel": ltdp_device.kernel_release(),
                "backend": _active_backend(),
                "last_source": _last_source,
                "backends": backends,
                "ranges": ranges,
                "current": {
                    "spl": limits.get("spl_limit"),
                    "sppt": limits.get("sppt_limit"),
                    "fppt": limits.get("fppt_limit"),
                    "package_draw": draw,
                },
                "platform_profile": {
                    "path": pp_path or "",
                    "current": _read_profile(pp_path) if pp_path else "",
                    "choices": _profile_choices(),
                },
                "firmware_mode": ltdp_acpi.mode_name(ltdp_acpi.get_mode())
                                 if _acpi_ready() else "",
                "charge_limit": _read_charge_limit(),
                "fans": _read_fan_state(),
                "temperature": _cpu_temp(),
                "ryzenadj": {"available": _ryzenadj_available,
                             "path": _ryzenadj_binary() or BIN_PATH,
                             "verified": not bool(_system_ryzenadj)},
                "conflicts": _detect_conflicts(),
                "notes": list(profile.notes),
                "version": updater.plugin_version(),
            }
        return await _offload(_do)

    async def restore_defaults(self) -> dict:
        def _do() -> dict:
            with _mutation_lock:
                result = _restore_defaults_locked()
                if result["success"]:
                    _cancel_ac_settle()
                return result
        return await _offload(_do)

    async def set_panel_active(self, active: bool) -> None:
        """Renew (or drop) the panel's lease on the info loop."""
        global _panel_active, _panel_active_ts
        _panel_active = active
        _panel_active_ts = time.monotonic() if active else 0.0

    async def reapply(self) -> dict:
        """Force the saved limits back onto the hardware.

        Called by the frontend on resume from suspend, where the SMU comes back
        at firmware defaults. Decky has no backend resume hook - the loader only
        ever invokes _migration, _main, _unload and _uninstall - so Steam's own
        notification is the only signal there is, and without it the enforce
        loop takes up to five seconds to notice.
        """
        def _do() -> dict:
            with _mutation_lock:
                s = _load_settings()
                if not s.get("enabled", True):
                    return {"success": True, "skipped": True}
                # Whatever was cached describes the pre-suspend hardware.
                _invalidate_limits_cache()
                target = _clamp_for_settings(
                    s,
                    s.get("active_spl",  s.get("spl",  _defaults()["spl"])),
                    s.get("active_sppt", s.get("sppt", _defaults()["sppt"])),
                    s.get("active_fppt", s.get("fppt", _defaults()["fppt"])),
                )
                result = _apply_limits(*target)
                if result["success"]:
                    _cancel_ac_settle()
                decky.logger.info(
                    f"[ltdp] reapply after resume: success={result['success']}")
                return {"success": result["success"], "skipped": False,
                        "stderr": result.get("stderr", "")}
        return await _offload(_do)

    async def set_active_app(self, app_id: str) -> None:
        """Frontend reports the authoritative running-game appid (or '' for none)."""
        global _frontend_appid, _frontend_appid_ts
        _frontend_appid = app_id or ""
        _frontend_appid_ts = time.monotonic()

    async def get_tdp_info(self) -> dict:
        if not self._ready:
            return {"success": False, "values": {}, "error": "not ready"}
        with _info_cache_lock:
            return {"success": True, "values": dict(_info_cache)}

    async def apply_tdp(self, spl: int, sppt: int, fppt: int, app_id: str = "",
                        preset_name: str = "",
                        expected_app_id: str | None = None,
                        slot: str = "dc") -> dict:
        """Apply a triplet and persist it.

        `slot` only matters for the global settings, and says which of the two
        the numbers belong to: "dc" is the battery set, "ac" the charger one.
        Per-game AC values keep their own entry point (set_game_ac_profile),
        because there the sliders always describe the battery profile.
        """
        if not self._ready:
            return {"success": False, "stderr": "not ready", "stdout": "", "returncode": -1}

        def _do() -> dict:
            with _mutation_lock:
                s = _load_settings()
                if not s.get("enabled", True):
                    return {"success": False, "stderr": "plugin disabled",
                            "stdout": "", "returncode": -1}
                current_app_id = _get_running_appid()
                if expected_app_id is not None and current_app_id != expected_app_id:
                    return {"success": False, "stderr": "foreground game changed",
                            "stdout": "", "returncode": -1}
                if app_id and current_app_id != app_id:
                    return {"success": False, "stderr": "game is no longer active",
                            "stdout": "", "returncode": -1}

                requested = _clamp_for_settings(s, spl, sppt, fppt)
                profiles: dict = {}
                existing: dict = {}
                want = requested
                editing_ac = (not app_id) and slot == "ac"

                if app_id:
                    profiles = _load_profiles()
                    found = profiles.get(app_id, {})
                    existing = found if isinstance(found, dict) else {}
                    # On AC with a separate AC profile, the sliders describe the
                    # battery values but the hardware should run the AC ones.
                    if (_get_ac_online() and existing.get("ac_separate")
                            and existing.get("ac_spl") is not None):
                        want = _clamp_for_settings(
                            s,
                            existing["ac_spl"],
                            existing.get("ac_sppt", existing.get("sppt", _defaults()["sppt"])),
                            existing.get("ac_fppt", existing.get("fppt", _defaults()["fppt"])),
                        )
                else:
                    # Same rule one level up: editing the set that is not
                    # currently selected saves it without disturbing what is
                    # running, and editing the selected one applies it.
                    candidate = dict(s)
                    if editing_ac:
                        candidate["ac_spl"], candidate["ac_sppt"], candidate["ac_fppt"] = requested
                        candidate["ac_separate"] = True
                    else:
                        candidate["spl"], candidate["sppt"], candidate["fppt"] = requested
                    want = _global_triplet(candidate)

                result = _apply_limits(*want)
                if not result["success"]:
                    return result

                if app_id:
                    existing.update({"spl": requested[0], "sppt": requested[1],
                                     "fppt": requested[2]})
                    if preset_name:
                        existing["preset"] = preset_name
                    profiles[app_id] = existing
                    decky.logger.info(f"[ltdp] Saved game profile: app={app_id}")
                elif editing_ac:
                    s["ac_spl"], s["ac_sppt"], s["ac_fppt"] = requested
                    s["ac_separate"] = True
                    s["ac_preset"] = preset_name
                else:
                    s["spl"], s["sppt"], s["fppt"] = requested
                    s["active_preset"] = preset_name
                s["active_spl"], s["active_sppt"], s["active_fppt"] = want
                values = {SETTINGS_KEY_SETTINGS: s}
                if app_id:
                    values[SETTINGS_KEY_GAME_PROFILES] = profiles
                _write_keys(values)
                _cancel_ac_settle()
                return result
        return await _offload(_do)

    # ---- Updates ----------------------------------------------------- #

    async def check_for_updates(self) -> dict:
        """Deliberately inert in this fork.

        The upstream releases this would find are the Legion Go 2 / Go S
        builds, whose device table has no Legion Go 1 in it. Installing one
        over this plugin would silently swap the machine's whole capability
        profile, so the check says what it is rather than offering it.
        """
        if not UPDATE_CHECKS_ENABLED:
            return {
                "current_version": updater.plugin_version(),
                "update_available": False,
                "error": "Automatic updates are disabled in the Legion Go 1 build. "
                         "Install a newer LTDP zip through "
                         "Decky - Developer - Install Plugin from ZIP.",
            }
        return await _offload(updater.check)

    async def perform_update(self) -> dict:
        if not UPDATE_CHECKS_ENABLED:
            return {"success": False,
                    "error": "Automatic updates are disabled in this build."}
        return await _offload(updater.download_latest)

    async def _push_info(self) -> bool:
        """One refresh, pushed to the panel. True when something went out.

        Split out of _info_loop so the emit itself can be tested - the loop
        around it never terminates, so there is no way to await one iteration.
        """
        if not _panel_is_active():
            return False
        await _offload(_refresh_info_cache)
        with _info_cache_lock:
            values = dict(_info_cache)
        # Pushed, not polled. The panel used to ask for this over RPC every two
        # seconds - a round trip per tick to fetch numbers the backend had just
        # refreshed on this very schedule.
        await decky.emit("tdp_info", {"success": True, "values": values})
        return True

    async def _info_loop(self):
        while True:
            await asyncio.sleep(2)
            try:
                await self._push_info()
            except Exception as e:
                decky.logger.warning(f"[ltdp] info loop error: {e}")

    async def _resettle_after_ac(self, generation: int):
        """Put the limits back over the seconds after a charger transition.

        The firmware writes its own profile on plug-in and wins the race against
        a single apply, so the target is re-asserted until it stops being
        overwritten. Each pass is skipped once the hardware already agrees, so
        this costs nothing when the first write did stick.
        """
        for delay in _ac_settle_delays():
            await asyncio.sleep(delay)
            try:
                settled = await _offload(_reapply_current_target, generation)
            except Exception as e:
                decky.logger.warning(f"[ltdp] AC re-settle failed: {e}")
                return
            if settled:
                return

    async def _enforce_loop(self):
        while True:
            await asyncio.sleep(5)
            try:
                events = await _offload(_check_and_enforce)
                generation = events.pop("_resettle_generation", None)
                if generation is not None:
                    # Deliberately not awaited: the ladder runs for several
                    # seconds and the enforce loop has its own schedule to keep.
                    task = asyncio.create_task(self._resettle_after_ac(generation))
                    self._tasks.append(task)
                    task.add_done_callback(
                        lambda done: self._tasks.remove(done) if done in self._tasks else None)
                for event, payload in events.items():
                    await decky.emit(event, payload)
            except Exception as e:
                decky.logger.warning(f"[ltdp] enforce iteration failed: {e}")

    async def _migration(self):
        """Fold the pre-1.5.0 files into Decky's store, before anything reads it.

        This is the loader's own hook for the job: it runs to completion before
        _main() is even scheduled, so no settings read can race the migration.

        decky.migrate_settings() deliberately goes unused. It relocates a file
        under its own basename and rm -rf's the source, so the legacy
        PLUGIN_DIR/settings.json would land straight on top of the
        SettingsManager store - identical filename - and replace the whole
        keyed object with a flat pre-1.5.0 dict. That helper moves files; this
        migration has to reshape them.

        Nothing may escape. The loader runs this with run_until_complete inside
        a bare except that logs and sys.exit(0)s, and it never gets as far as
        creating the RPC socket - so a raise here would leave the panel retrying
        an is_ready() that has nobody to answer it, spinning on "Initializing"
        forever. Recording the failure instead tells the user their old settings
        did not come across, before they start rebuilding them on top.
        """
        try:
            await _offload(_migrate)
        except Exception as e:
            Plugin._setup_error = f"settings migration failed: {e}"
            decky.logger.error(f"[ltdp] migration failed: {e}")

    async def _main(self):
        decky.logger.info(f"[ltdp] startup  v{updater.plugin_version()}")
        try:
            global _current_ac_online, _ryzenadj_available, _acpi_available
            Plugin._ready = False
            Plugin._setup_error = None
            # Resolve the trust store now so the log states up front whether downloads
            # and update checks will be able to verify certificates.
            await _offload(updater.ssl_context)
            # Seed this so the first enforce pass does not report a phantom AC change.
            _current_ac_online = await _offload(_get_ac_online)
            ltdp_acpi.set_logger(decky.logger)
            profile = await _offload(_device)
            wmi = await _offload(_wmi_caps)
            # Probing acpi_call means writing to /proc/acpi/call, so it only
            # happens on a machine whose profile says it speaks the Lenovo
            # GameZone interface. It is probed even when the kernel driver is
            # present - the probe only reads the current power mode, and
            # knowing the path exists is what lets a refused firmware write
            # fall back to it instead of straight to ryzenadj.
            acpi = False
            if profile.supports_acpi_call:
                acpi = await _offload(lambda: ltdp_acpi.available(force=True))
                _acpi_available = acpi
            firmware = bool(wmi) or acpi
            try:
                if _wmi_only():
                    _ryzenadj_available = False
                    decky.logger.info(
                        "[ltdp] firmware-only device, skipping the ryzenadj download")
                else:
                    await _offload(_ensure_ryzenadj)
                    _ryzenadj_available = True
            except Exception as e:
                _ryzenadj_available = False
                # Only fatal when there is no firmware path to fall back on. On
                # a Legion Go 1 running a kernel without the Lenovo driver and
                # without acpi_call, ryzenadj is the only way to set anything at
                # all, so its absence there really is the end of the road.
                if not firmware:
                    raise
                decky.logger.warning(
                    f"[ltdp] ryzenadj unavailable ({e}); Extras range disabled")
            def _apply_saved() -> dict:
                with _mutation_lock:
                    s = _load_settings()
                    if s.get("extras_unlocked", False) and not _ryzenadj_available:
                        profiles = _load_profiles()
                        _lock_extras_state(s, profiles)
                        s["extras_unlocked"] = False
                        _write_keys({SETTINGS_KEY_SETTINGS: s,
                                     SETTINGS_KEY_GAME_PROFILES: profiles})
                    if not s.get("enabled", True):
                        return {"success": True, "skipped": True}
                    target = _clamp_for_settings(
                        s,
                        s.get("active_spl",  s.get("spl",  _defaults()["spl"])),
                        s.get("active_sppt", s.get("sppt", _defaults()["sppt"])),
                        s.get("active_fppt", s.get("fppt", _defaults()["fppt"])),
                    )
                    result = _apply_limits(*target)
                    if result["success"]:
                        _save_active(s, *target)
                    return result
            def _apply_saved_charge_limit() -> None:
                state = _load_settings()
                if "charge_limit" not in state:
                    return
                wanted = bool(state["charge_limit"])
                current = _read_charge_limit()
                # Only write when it disagrees: the firmware remembers this
                # across reboots, and re-asserting it every start would be a
                # write to the EC for nothing.
                if current.get("supported") and current.get("enabled") != wanted:
                    _apply_charge_limit(wanted)

            def _apply_saved_fan_mode() -> None:
                with _mutation_lock:
                    mode = _load_settings().get("fan_mode", "auto")
                    if mode != "auto" and _fan_available():
                        _apply_fan_mode(mode)

            try:
                await _offload(_apply_saved_fan_mode)
            except Exception as e:
                decky.logger.warning(f"[ltdp] fan mode not restored: {e}")

            try:
                await _offload(_apply_saved_charge_limit)
            except Exception as e:
                decky.logger.warning(f"[ltdp] charge limit not restored: {e}")

            startup_apply = await _offload(_apply_saved)
            if not startup_apply.get("success", False):
                decky.logger.warning(
                    f"[ltdp] saved TDP did not apply at startup: "
                    f"{startup_apply.get('stderr', 'unknown error')}")

            Plugin._ready = True
            # Keep references - a bare create_task() may be garbage-collected mid-run.
            self._tasks = [
                asyncio.create_task(self._enforce_loop()),
                asyncio.create_task(self._info_loop()),
            ]
            std = _standard_ceilings_mw()
            decky.logger.info(
                f"[ltdp] ready on {profile.label}: backend={_active_backend() or 'none'} "
                f"(firmware attributes={'yes' if wmi else 'no'}, "
                f"acpi_call={'yes' if acpi else 'no'}, "
                f"ryzenadj={'yes' if _ryzenadj_available else 'no'}), "
                f"range {_fallback_min_w()}-{std[0] // 1000}/"
                f"{std[1] // 1000}/{std[2] // 1000} W")
            for conflict in _detect_conflicts():
                decky.logger.warning(
                    f"[ltdp] possible conflict: {conflict['params']['name']} "
                    f"({conflict['key'].split('.')[-1]})")
        except Exception as e:
            Plugin._setup_error = str(e)
            decky.logger.error(f"[ltdp] setup failed: {e}")

    async def _unload(self):
        Plugin._ready = False
        def _invalidate_ac_ladder() -> None:
            with _mutation_lock:
                _cancel_ac_settle()
        await _offload(_invalidate_ac_ladder)
        for t in self._tasks:
            t.cancel()
        # Bounded on purpose. Cancelling a task parked in run_in_executor does
        # not stop the worker thread, so awaiting it takes as long as whatever
        # blocking call it sits inside - a `ryzenadj --info` plus its lock wait
        # is five seconds on its own. The loader gives a plugin exactly five
        # seconds to stop before it sends SIGKILL, and a SIGKILL means
        # _uninstall() never runs at all. Observed on the device: the platform
        # profile was left pinned to 'custom' with the plugin already gone.
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=1.0)
        self._tasks = []
        decky.logger.info("[ltdp] unloaded")

    async def _uninstall(self):
        """Hand the hardware back before the plugin directory disappears.

        The firmware keeps whatever ppt_* triplet was last latched into the
        'custom' profile, so without this an uninstall leaves the machine pinned
        to the plugin's final TDP with nothing left installed to change it.

        Nothing is cleaned off disk here: the loader removes the whole plugin
        directory straight afterwards, and DECKY_PLUGIN_SETTINGS_DIR - where the
        settings and per-game profiles live - is deliberately left alone, so a
        reinstall still finds them.
        """
        def _do() -> None:
            # _unload() cancelled the enforce loop, but cancelling a task parked
            # in run_in_executor does not stop the worker thread, so a pass may
            # still be in flight holding this lock. Take it, or that pass could
            # re-assert the limits after we have handed the profile back.
            with _mutation_lock:
                if not _apply_lock.acquire(timeout=8.0):
                    decky.logger.warning(
                        "[ltdp] uninstall: apply busy, leaving the profile as it is")
                    return
                # Same for the fans: a curve nobody can change any more is not
                # something to leave running.
                if _fan_available() and _load_settings().get("fan_mode", "auto") != "auto":
                    _apply_fan_mode("auto")
                    decky.logger.info("[ltdp] uninstall: fans handed back to the firmware")
                # A charge limit the user can no longer see or change is not
                # something to leave behind on the way out.
                if _read_charge_limit().get("enabled"):
                    _apply_charge_limit(False)
                    decky.logger.info("[ltdp] uninstall: charge limit removed")
                try:
                    path = _profile_path()
                    if path and _write_profile(path, "balanced"):
                        decky.logger.info("[ltdp] uninstall: platform profile -> balanced")
                    elif _acpi_ready() and ltdp_acpi.restore_mode(ltdp_acpi.MODE_BALANCED):
                        decky.logger.info(
                            "[ltdp] uninstall: firmware power mode -> balanced")
                finally:
                    _apply_lock.release()
        await _offload(_do)
        decky.logger.info("[ltdp] uninstalled")
