# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# Legion Go 1 port
# https://github.com/Rayekkk/LeGoTDP

"""Lenovo GameZone "Other Method" TDP control through acpi_call.

This is the same firmware interface the in-kernel lenovo-wmi-other driver
drives; it is reached here through /proc/acpi/call for the kernels that do not
carry that driver yet. On the original Legion Go under SteamOS 3.7 (Linux 6.11)
that is the only way to reach the firmware at all, and it is the path Handheld
Daemon has used on this machine since 2024.

Wire format, all of it verified against drivers/platform/x86/lenovo/wmi-other.c
and the Handheld Daemon implementation:

    attribute id = device_id << 24 | feature_id << 16 | mode_id << 8 | type_id

        device_id  0x01  CPU
        feature_id 0x01  SPPT (slow)        0x02  SPL (sustained)
                   0x03  FPPT (fast)
        mode_id    0xFF  custom  (0x01 quiet, 0x02 balanced, 0x03 performance)
        type_id    0x00  plain attribute

    \\_SB.GZFD.WMAE 0x0 0x11 <id:4 LE>              -> get value
    \\_SB.GZFD.WMAE 0x0 0x12 <id:4 LE><value:4 LE>  -> set value
    \\_SB.GZFD.WMAA 0x0 0x2C <mode>                 -> set power mode
    \\_SB.GZFD.WMAA 0x0 0x2D 0x0                    -> get power mode

The values are watts, and the firmware range-checks them itself: a request
above what it accepts comes back clamped rather than applied, which is why
every write here is read back before it is reported as a success.
"""

import os
import subprocess
import threading

PROC_CALL = "/proc/acpi/call"

METHOD_GZ = r"\_SB.GZFD.WMAA"     # GameZone: power mode
METHOD_FAN = r"\_SB.GZFD.WMAB"    # GameZone: fan curve
METHOD_OTHER = r"\_SB.GZFD.WMAE"  # Other Method: feature get/set

GZ_GET_MODE = 0x2D
GZ_SET_MODE = 0x2C
FAN_GET_CURVE = 0x05
FAN_SET_CURVE = 0x06
OM_GET_VALUE = 0x11
OM_SET_VALUE = 0x12

MODE_NONE = 0x00
MODE_QUIET = 0x01
MODE_BALANCED = 0x02
MODE_PERFORMANCE = 0x03
MODE_EXTREME = 0xE0
MODE_CUSTOM = 0xFF

MODE_NAMES = {
    MODE_QUIET: "quiet",
    MODE_BALANCED: "balanced",
    MODE_PERFORMANCE: "performance",
    MODE_EXTREME: "extreme",
    MODE_CUSTOM: "custom",
}

DEVICE_ID_CPU = 0x01
DEVICE_ID_PSU = 0x03
DEVICE_ID_FAN = 0x04
FEATURE_SPPT = 0x01
FEATURE_SPL = 0x02
FEATURE_FPPT = 0x03
FEATURE_PSU_CHARGE_TYPES = 0x01
FEATURE_FAN_FULL_SPEED = 0x02


def attr_id(device_id: int, feature_id: int, mode_id: int, type_id: int = 0) -> int:
    return ((device_id & 0xFF) << 24 | (feature_id & 0xFF) << 16
            | (mode_id & 0xFF) << 8 | (type_id & 0xFF))


# The three limits, in the order the rest of the plugin names them.
FEATURE_IDS = {
    "spl":  attr_id(DEVICE_ID_CPU, FEATURE_SPL,  MODE_CUSTOM),
    "sppt": attr_id(DEVICE_ID_CPU, FEATURE_SPPT, MODE_CUSTOM),
    "fppt": attr_id(DEVICE_ID_CPU, FEATURE_FPPT, MODE_CUSTOM),
}

# Lenovo's conservation mode: stop charging at 80 % to spare the cells. One
# boolean, not a percentage - the threshold is the firmware's, not ours.
# device=PSU, feature=charge types, mode=none, type=1 (AC), i.e. 0x03010001,
# which is what the kernel driver reaches through POWER_SUPPLY_PROP_CHARGE_TYPES
# and what Handheld Daemon writes on this machine.
CHARGE_LIMIT_ID = attr_id(DEVICE_ID_PSU, FEATURE_PSU_CHARGE_TYPES, MODE_NONE, 0x01)

FULL_FAN_SPEED_ID = attr_id(DEVICE_ID_FAN, FEATURE_FAN_FULL_SPEED, MODE_NONE, 0x00)

# The curve is ten fan speeds, one per 10 °C from 10 °C to 100 °C. Below this
# floor the firmware is being asked to run the machine hotter than Lenovo
# thinks it should, so it is a floor here too - the point of fan control on a
# handheld is to cool it more, not less.
FAN_CURVE_POINTS = 10
FAN_CURVE_TEMPS = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
FAN_CURVE_MIN = (44, 48, 55, 60, 71, 79, 87, 87, 100, 100)
FAN_CURVE_MAX_VALUE = 115

# /proc/acpi/call is one global resource: the result of a call is read back
# from the same file, so a concurrent call would hand us somebody else's answer.
_lock = threading.RLock()

# None = never probed. Re-probed on demand rather than cached forever, because
# the module can be loaded after the plugin starts.
_available = None
_modprobe_tried = False

_logger = None


def set_logger(logger) -> None:
    """Route this module's log lines into the plugin logger."""
    global _logger
    _logger = logger


def _log(level: str, message: str) -> None:
    if _logger is not None:
        getattr(_logger, level, _logger.info)(f"[ltdp/acpi] {message}")


# -- raw transport ------------------------------------------------------------

def _encode(method: str, args) -> str:
    cmd = method
    for arg in args:
        if isinstance(arg, int):
            cmd += f" 0x{arg:02x}"
        else:
            cmd += f" b{arg.hex()}"
    return cmd


def _write(cmd: str) -> bool:
    try:
        with open(PROC_CALL, "wb") as f:
            f.write(cmd.encode())
        return True
    except OSError as e:
        _log("error", f"call failed ({cmd}): {e}")
        return False


def _read():
    """Parse whatever the last call left behind: int, bytes, or None."""
    try:
        with open(PROC_CALL, "rb") as f:
            raw = f.read().decode(errors="replace").strip()
    except OSError as e:
        _log("error", f"read failed: {e}")
        return None
    raw = raw.rstrip("\x00")
    if not raw or raw == "not called":
        return None
    if raw.startswith("Error"):
        _log("warning", f"acpi_call reported: {raw}")
        return None
    if raw.startswith("0x"):
        try:
            return int(raw, 16)
        except ValueError:
            return None
    if raw.startswith("{") and raw.endswith("}"):
        try:
            return bytes(int(b, 16) for b in raw[1:-1].split(", ") if b)
        except ValueError:
            return None
    return None


def call(method: str, args):
    """One call plus its result, taken atomically."""
    with _lock:
        if not _write(_encode(method, args)):
            return None
        return _read()


# -- availability -------------------------------------------------------------

def modprobe() -> bool:
    """Load acpi_call once per process. Absent module is not an error here."""
    global _modprobe_tried
    if _modprobe_tried:
        return os.path.exists(PROC_CALL)
    _modprobe_tried = True
    if os.path.exists(PROC_CALL):
        return True
    try:
        proc = subprocess.run(["modprobe", "acpi_call"],
                              capture_output=True, timeout=10)
        output = (proc.stdout + proc.stderr).decode(errors="replace").strip()
        if output:
            _log("info", f"modprobe acpi_call: {output}")
    except (OSError, subprocess.SubprocessError) as e:
        _log("info", f"modprobe acpi_call unavailable: {e}")
    return os.path.exists(PROC_CALL)


def available(force: bool = False) -> bool:
    """True when acpi_call is loaded and this firmware answers GameZone.

    The GameZone probe matters as much as the module: /proc/acpi/call will
    happily accept a method name that does not exist, and a machine that is not
    a Legion would then look controllable when it is not.
    """
    global _available
    if _available is not None and not force:
        return _available
    _available = False
    if not modprobe():
        return False
    if not os.access(PROC_CALL, os.W_OK):
        _log("warning", f"{PROC_CALL} is not writable")
        return False
    _available = get_mode() is not None
    if not _available:
        _log("info", "GameZone did not answer; acpi_call path unavailable")
    return _available


def reset_cache() -> None:
    global _available, _modprobe_tried
    _available = None
    _modprobe_tried = False


# -- power mode ---------------------------------------------------------------

def get_mode():
    """Current firmware power mode as an int, or None."""
    result = call(METHOD_GZ, [0, GZ_GET_MODE, 0])
    if isinstance(result, bytes) and result:
        result = result[0]
    if not isinstance(result, int):
        return None
    if result not in MODE_NAMES:
        _log("warning", f"unknown power mode 0x{result:02x}")
        return None
    return result


def mode_name(mode) -> str:
    return MODE_NAMES.get(mode, "unknown") if mode is not None else "unavailable"


def set_mode(mode: int) -> bool:
    with _lock:
        call(METHOD_GZ, [0, GZ_SET_MODE, mode])
        return get_mode() == mode


def ensure_custom_mode() -> bool:
    """Select the custom power mode, which is what makes the limits tunable.

    The firmware ignores a limit written in any other mode, exactly as the
    in-kernel driver documents (it returns -EBUSY rather than writing).
    """
    if get_mode() == MODE_CUSTOM:
        return True
    return set_mode(MODE_CUSTOM)


# -- limits -------------------------------------------------------------------

def get_feature(feature_id: int):
    result = call(METHOD_OTHER, [
        0, OM_GET_VALUE, feature_id.to_bytes(4, "little", signed=False)])
    if isinstance(result, bytes):
        result = int.from_bytes(result[:4], "little") if result else None
    return result if isinstance(result, int) else None


def set_feature(feature_id: int, value: int) -> bool:
    with _lock:
        call(METHOD_OTHER, [
            0, OM_SET_VALUE,
            feature_id.to_bytes(4, "little", signed=False)
            + int(value).to_bytes(4, "little", signed=False)])
        return get_feature(feature_id) == value


def read_limits() -> dict:
    """{'spl': w, 'sppt': w, 'fppt': w} - a live read, empty when unavailable.

    Unlike the ryzenadj path every one of the three reads back exactly what was
    asked for, so drift is detectable on all of them.
    """
    values = {}
    for key, feature_id in FEATURE_IDS.items():
        value = get_feature(feature_id)
        if value is None:
            return {}
        values[key] = value
    return values


def apply_limits(spl_w: int, sppt_w: int, fppt_w: int) -> dict:
    """Write the three limits and verify them. Result matches _apply_wmi()."""
    if not available():
        return {"success": False, "stdout": "", "stderr": "acpi_call unavailable",
                "returncode": -1}

    with _lock:
        if not ensure_custom_mode():
            return {"success": False, "stdout": "",
                    "stderr": "firmware would not enter its custom power mode",
                    "returncode": -1}

        current = read_limits()
        # SPL <= SPPT <= FPPT has to hold at every intermediate step or the
        # firmware rejects the odd one out: raise the ceiling first when going
        # up, and lower the floor first when coming down.
        raising = not current or spl_w > current.get("spl", 0)
        order = (("fppt", fppt_w), ("sppt", sppt_w), ("spl", spl_w)) if raising \
            else (("spl", spl_w), ("sppt", sppt_w), ("fppt", fppt_w))
        for key, value in order:
            set_feature(FEATURE_IDS[key], value)

        after = read_limits()

    want = {"spl": spl_w, "sppt": sppt_w, "fppt": fppt_w}
    if after == want:
        _log("info", f"apply {spl_w}W/{sppt_w}W/{fppt_w}W")
        return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    mismatch = "; ".join(f"{k}={after.get(k)} want {v}"
                         for k, v in want.items() if after.get(k) != v)
    return {"success": False, "stdout": "",
            "stderr": mismatch or "firmware did not answer", "returncode": -1}


# -- fans ---------------------------------------------------------------------

def get_fan_curve():
    """The ten curve points the firmware is running, or None.

    The read is a different shape from the write - four bytes per point rather
    than two - which is not symmetry anyone would design, but it is what this
    firmware answers.
    """
    with _lock:
        if call(METHOD_FAN, [0, FAN_GET_CURVE, bytes(4)]) is None:
            return None
        raw = _read()
    if not isinstance(raw, bytes) or len(raw) < 44:
        return None
    return [raw[i] for i in range(4, 44, 4)]


def clamp_fan_curve(curve):
    """Hold the curve at or above the firmware's own minimum."""
    values = list(curve)[:FAN_CURVE_POINTS]
    while len(values) < FAN_CURVE_POINTS:
        values.append(FAN_CURVE_MIN[len(values)])
    return [max(int(FAN_CURVE_MIN[i]), min(int(v), FAN_CURVE_MAX_VALUE))
            for i, v in enumerate(values)]


def set_fan_curve(curve) -> bool:
    """Write ten fan speeds, one per 10 °C step from 10 °C to 100 °C."""
    values = clamp_fan_curve(curve)
    payload = bytearray([0x00, 0x00, 0x0A, 0x00, 0x00, 0x00])
    for value in values:
        payload += bytes([value, 0x00])
    payload += bytes([0x00, 0x0A, 0x00, 0x00, 0x00])
    for temp in FAN_CURVE_TEMPS:
        payload += bytes([temp, 0x00])
    payload += bytes([0x00])

    with _lock:
        if not available():
            return False
        call(METHOD_FAN, [0, FAN_SET_CURVE, bytes(payload)])
        after = get_fan_curve()
    _log("info", f"fan curve -> {values} (read back {after})")
    return after is not None and curves_match(after, values)


def curves_match(a, b, tolerance: int = 2) -> bool:
    """True when two curves agree closely enough.

    Not an exact comparison: the firmware rounds what it is given, and chasing
    the last percent would have the enforce pass rewriting the curve forever.
    """
    if not a or not b or len(a) != len(b):
        return False
    return all(abs(int(x) - int(y)) <= tolerance for x, y in zip(a, b))


def get_full_fan_speed():
    value = get_feature(FULL_FAN_SPEED_ID)
    return None if value is None else bool(value)


def set_full_fan_speed(enabled: bool) -> bool:
    with _lock:
        if not available():
            return False
        set_feature(FULL_FAN_SPEED_ID, int(bool(enabled)))
        result = get_full_fan_speed()
    _log("info", f"full fan speed -> {bool(enabled)} (read back {result})")
    return result == bool(enabled)


def reset_fan_curve() -> bool:
    """Hand the fans back to the firmware.

    There is no "restore default curve" call; what resets it is a power-mode
    transition, so the mode is bounced and put back. Verified in Handheld
    Daemon, which does exactly this after a fan-mode change.
    """
    with _lock:
        mode = get_mode()
        if mode is None:
            return False
        bounce = (MODE_PERFORMANCE if mode != MODE_PERFORMANCE else MODE_BALANCED)
        set_mode(bounce)
        return set_mode(mode)


# -- charge limit -------------------------------------------------------------

def get_charge_limit():
    """True when the firmware is holding the charge at 80 %, or None."""
    value = get_feature(CHARGE_LIMIT_ID)
    return None if value is None else bool(value)


def set_charge_limit(enabled: bool) -> bool:
    with _lock:
        if not available():
            return False
        set_feature(CHARGE_LIMIT_ID, int(bool(enabled)))
        result = get_charge_limit()
        _log("info", f"charge limit -> {bool(enabled)} (read back {result})")
        return result == bool(enabled)


def restore_mode(mode: int = MODE_BALANCED) -> bool:
    """Hand the machine back to one of Lenovo's own power modes."""
    return set_mode(mode)
