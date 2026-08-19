#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# LTDP - TDP control for the Legion Go 1
#
# Reports what this machine is, which TDP interfaces it has, and what range
# they allow - then says which backend the plugin will use and why.
#
#   sudo ./ltdp-diagnostics.sh                 read-only, safe at any time
#   sudo ./ltdp-diagnostics.sh --write-test    also proves writes land
#
# The write test changes the TDP for a few seconds and puts back exactly what
# it found. Do not run it in the middle of a benchmark.

set -uo pipefail

WRITE_TEST=0
for arg in "$@"; do
  case "$arg" in
    --write-test) WRITE_TEST=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

ACPI_CALL=/proc/acpi/call
WMI_ATTRS=""
PP_DIR=""
HAVE_WMI=0
HAVE_ACPI=0
HAVE_RYZENADJ=0
RYZENADJ_BIN=""

say()  { printf '%s\n' "$*"; }
head1() { printf '\n== %s ==\n' "$*"; }
kv()   { printf '  %-28s %s\n' "$1:" "$2"; }

read_or() {
  if [ -r "$1" ]; then tr -d '\0' < "$1" | head -n 1; else printf '%s' "${2:-<absent>}"; fi
}

if [ "$(id -u)" != "0" ]; then
  say "warning: not running as root - most of this needs it. Re-run with sudo."
fi

# ---------------------------------------------------------------- device ----
head1 "Device"
PRODUCT=$(read_or /sys/class/dmi/id/product_name)
VERSION=$(read_or /sys/class/dmi/id/product_version)
FAMILY=$(read_or /sys/class/dmi/id/product_family)
BIOS=$(read_or /sys/class/dmi/id/bios_version)
BIOS_DATE=$(read_or /sys/class/dmi/id/bios_date)
BOARD=$(read_or /sys/class/dmi/id/board_name)
kv "product_name" "$PRODUCT"
kv "product_version" "$VERSION"
kv "product_family" "$FAMILY"
kv "board_name" "$BOARD"
# N3CN40WW (January 2026) is the release this build is written against.
# N3CN42WW was withdrawn by Lenovo after handhelds failed to boot.
BIOS_NUM=$(printf '%s' "$BIOS" | sed 's/^N3CN//; s/WW.*//' | tr -cd '0-9')
BIOS_NOTE=""
case "$BIOS_NUM" in
  "")  BIOS_NOTE="" ;;
  42)  BIOS_NOTE="  <- WITHDRAWN by Lenovo after boot failures were reported" ;;
  40)  BIOS_NOTE="  <- the version this build targets" ;;
  *)   if [ "$BIOS_NUM" -lt 40 ] 2>/dev/null; then
         BIOS_NOTE="  <- older than N3CN40WW, the version this build targets"
       else
         BIOS_NOTE="  <- newer than N3CN40WW, the version this build targets"
       fi ;;
esac
kv "BIOS" "$BIOS ($BIOS_DATE)$BIOS_NOTE"
kv "CPU" "$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
kv "kernel" "$(uname -r)"
kv "OS" "$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}")"

case "$PRODUCT" in
  83E1) DEVICE="Lenovo Legion Go 1 (Z1 Extreme) - supported by this build" ;;
  83N0|83N1) DEVICE="Lenovo Legion Go 2 - use the upstream LeGoTDP build" ;;
  83L3|83N6|83Q2|83Q3) DEVICE="Lenovo Legion Go S - use the upstream LeGoTDP build" ;;
  *) DEVICE="not a Legion Go - the plugin will fall back to its generic profile" ;;
esac
kv "identified as" "$DEVICE"

# ------------------------------------------------------------- lenovo wmi ---
head1 "Lenovo WMI kernel drivers"
for mod in lenovo_wmi_other lenovo_wmi_gamezone lenovo_wmi_capdata01 lenovo_wmi_events acpi_call; do
  if lsmod 2>/dev/null | grep -q "^${mod} "; then
    kv "$mod" "loaded"
  elif modinfo "$mod" >/dev/null 2>&1; then
    kv "$mod" "available, not loaded"
  else
    kv "$mod" "absent"
  fi
done

for dir in /sys/class/firmware-attributes/lenovo-wmi-other-*/attributes; do
  [ -d "$dir" ] || continue
  WMI_ATTRS="$dir"
  break
done

head1 "Firmware attributes (lenovo-wmi-other)"
if [ -n "$WMI_ATTRS" ]; then
  kv "path" "$WMI_ATTRS"
  HAVE_WMI=1
  for attr in ppt_pl1_spl ppt_pl2_sppt ppt_pl3_fppt; do
    if [ -d "$WMI_ATTRS/$attr" ]; then
      kv "$attr" "current=$(read_or "$WMI_ATTRS/$attr/current_value") \
min=$(read_or "$WMI_ATTRS/$attr/min_value") \
max=$(read_or "$WMI_ATTRS/$attr/max_value") \
default=$(read_or "$WMI_ATTRS/$attr/default_value" '-')"
    else
      kv "$attr" "<absent>"
      HAVE_WMI=0
    fi
  done
  ls "$WMI_ATTRS" 2>/dev/null | tr '\n' ' ' | sed 's/^/  all attributes:            /;s/$/\n/'
else
  kv "path" "<absent> - needs Linux 6.17+ (or a distro backport) for lenovo-wmi-other"
fi

# ------------------------------------------------------- platform profile ---
head1 "Platform profile"
for p in /sys/class/platform-profile/*; do
  [ -e "$p/profile" ] || continue
  kv "$(basename "$p") ($(read_or "$p/name" '?'))" \
     "current=$(read_or "$p/profile") choices=$(read_or "$p/choices")"
  if grep -q custom "$p/choices" 2>/dev/null; then PP_DIR="$p"; fi
done
if [ -r /sys/firmware/acpi/platform_profile ]; then
  kv "legacy acpi node" "$(read_or /sys/firmware/acpi/platform_profile) \
of [$(read_or /sys/firmware/acpi/platform_profile_choices)]"
fi
if [ -n "$PP_DIR" ]; then
  kv "tunable profile" "$PP_DIR (offers 'custom')"
else
  kv "tunable profile" "none offers 'custom' - the firmware-attributes path cannot bind"
  HAVE_WMI=0
fi

# -------------------------------------------------------------- acpi_call ---
# Attribute id = device<<24 | feature<<16 | mode<<8 | type, little-endian on the
# wire. CPU=0x01, SPPT=0x01, SPL=0x02, FPPT=0x03, custom mode=0xFF.
SPL_ID=b00ff0201
SPPT_ID=b00ff0101
FPPT_ID=b00ff0301

acpi_do() { printf '%s' "$1" > "$ACPI_CALL" 2>/dev/null && tr -d '\0' < "$ACPI_CALL"; }
acpi_get() { acpi_do "\\_SB.GZFD.WMAE 0x00 0x11 $1"; }
acpi_mode() { acpi_do "\\_SB.GZFD.WMAA 0x00 0x2d 0x00"; }

hex2dec() {
  case "$1" in
    0x*) printf '%d' "$1" 2>/dev/null || printf '?' ;;
    *) printf '%s' "${1:-?}" ;;
  esac
}

head1 "Lenovo firmware through acpi_call"
if [ ! -e "$ACPI_CALL" ]; then
  modprobe acpi_call 2>/dev/null
fi
if [ -w "$ACPI_CALL" ]; then
  MODE_RAW=$(acpi_mode)
  MODE=$(hex2dec "$MODE_RAW")
  case "$MODE" in
    1) MODE_NAME=quiet ;; 2) MODE_NAME=balanced ;; 3) MODE_NAME=performance ;;
    224) MODE_NAME=extreme ;; 255) MODE_NAME=custom ;; *) MODE_NAME="unknown ($MODE_RAW)" ;;
  esac
  kv "/proc/acpi/call" "writable"
  kv "firmware power mode" "$MODE_NAME"
  if [ "$MODE_NAME" != "unknown ($MODE_RAW)" ]; then
    HAVE_ACPI=1
    kv "SPL  (custom mode)" "$(hex2dec "$(acpi_get $SPL_ID)") W"
    kv "SPPT (custom mode)" "$(hex2dec "$(acpi_get $SPPT_ID)") W"
    kv "FPPT (custom mode)" "$(hex2dec "$(acpi_get $FPPT_ID)") W"
  else
    kv "GameZone" "did not answer - this firmware does not expose \\_SB.GZFD"
  fi
else
  kv "/proc/acpi/call" "absent or not writable - acpi_call is not installed"
  say "  On SteamOS acpi_call is not shipped; it needs a DKMS install, or a kernel"
  say "  new enough to carry the lenovo-wmi drivers instead."
fi

# --------------------------------------------------------------- ryzenadj ---
head1 "ryzenadj"
for candidate in \
  /home/deck/homebrew/plugins/LTDP/bin/ryzenadj \
  /home/deck/homebrew/plugins/*/bin/ryzenadj \
  /usr/bin/ryzenadj /usr/local/bin/ryzenadj "$(command -v ryzenadj 2>/dev/null)"; do
  [ -n "$candidate" ] && [ -x "$candidate" ] || continue
  RYZENADJ_BIN="$candidate"
  break
done
if [ -n "$RYZENADJ_BIN" ]; then
  HAVE_RYZENADJ=1
  kv "binary" "$RYZENADJ_BIN"
  "$RYZENADJ_BIN" --info 2>/dev/null | grep -Ei 'stapm|ppt limit|slow|fast' | sed 's/^/  /'
else
  kv "binary" "not installed (the plugin downloads its own on first run)"
fi

# ------------------------------------------------------------------- power --
head1 "Power"
for d in /sys/class/powercap/*:*; do
  [ -r "$d/name" ] || continue
  case "$(read_or "$d/name")" in
    package*)
      E1=$(read_or "$d/energy_uj"); sleep 1; E2=$(read_or "$d/energy_uj")
      if [ "$E1" -ge 0 ] 2>/dev/null && [ "$E2" -ge 0 ] 2>/dev/null && [ "$E2" -ge "$E1" ]; then
        kv "package power ($(basename "$d"))" "$(( (E2 - E1) / 100000 )) dW  (~$(( (E2-E1)/1000000 )) W)"
      fi
      ;;
  esac
done
for h in /sys/class/hwmon/hwmon*; do
  [ -r "$h/name" ] || continue
  HWNAME=$(read_or "$h/name")
  case "$HWNAME" in
    k10temp|zenpower)
      for t in "$h"/temp*_input; do
        [ -r "$t" ] || continue
        kv "temperature ($HWNAME)" "$(( $(read_or "$t") / 1000 )) C"
      done
      ;;
    lenovo_wmi_other|lenovo_wmi|legion_wmi)
      for f in "$h"/fan*_input; do
        [ -r "$f" ] || continue
        kv "fan ($HWNAME)" "$(read_or "$f") rpm"
      done
      ;;
  esac
done

for ps in /sys/class/power_supply/*; do
  [ -r "$ps/type" ] || continue
  if [ "$(read_or "$ps/type")" = "Mains" ]; then
    kv "$(basename "$ps") (Mains)" "online=$(read_or "$ps/online")"
  fi
done

# ------------------------------------------------------------------ fans ----
# The curve is ten fan speeds, one per 10 C from 10 C to 100 C. Read-only here:
# writing it is the plugin's job, and a wrong curve is felt, not just reported.
head1 "Fan curve"
if [ "$HAVE_ACPI" = "1" ]; then
  CURVE_RAW=$(acpi_do "\_SB.GZFD.WMAB 0x00 0x05 b00000000")
  if [ -n "$CURVE_RAW" ]; then
    CURVE=$(printf '%s' "$CURVE_RAW" | tr -d '{}' | tr ',' '
'             | awk 'NR>=5 && (NR-5)%4==0 {printf "%d ", strtonum($1)}')
    kv "curve (10..100 C)" "${CURVE:-<unreadable>}"
    kv "minimum allowed" "44 48 55 60 71 79 87 87 100 100"
  else
    kv "curve" "<no answer>"
  fi
  FULL=$(acpi_get b00000204)
  kv "full fan speed" "$(hex2dec "$FULL")"
else
  kv "result" "needs acpi_call; the kernel driver publishes speeds but not the curve"
fi

# ------------------------------------------------------------- conflicts ----
head1 "Other TDP controllers"
FOUND_CONFLICT=0
for proc in hhd adjustor powerstation simple-ryzen-tdp; do
  if pgrep -x "$proc" >/dev/null 2>&1; then
    kv "$proc" "RUNNING - will fight this plugin for the same limits"
    FOUND_CONFLICT=1
  fi
done
for plug in SimpleDeckyTDP PowerControl LeGoTDP LeGoTDP-LegionGo1; do
  if [ -d "/home/deck/homebrew/plugins/$plug" ]; then
    kv "decky plugin" "$plug installed"
    FOUND_CONFLICT=1
  fi
done
[ "$FOUND_CONFLICT" = "0" ] && kv "result" "none found"

# ------------------------------------------------------------ write test ----
if [ "$WRITE_TEST" = "1" ]; then
  head1 "Write test"
  if [ "$HAVE_WMI" = "1" ]; then
    OLD_SPL=$(read_or "$WMI_ATTRS/ppt_pl1_spl/current_value")
    OLD_SPPT=$(read_or "$WMI_ATTRS/ppt_pl2_sppt/current_value")
    OLD_FPPT=$(read_or "$WMI_ATTRS/ppt_pl3_fppt/current_value")
    OLD_PP=$(read_or "$PP_DIR/profile")
    kv "saved" "spl=$OLD_SPL sppt=$OLD_SPPT fppt=$OLD_FPPT profile=$OLD_PP"
    echo custom > "$PP_DIR/profile" 2>/dev/null
    echo 12 > "$WMI_ATTRS/ppt_pl1_spl/current_value" 2>/dev/null
    sleep 1
    kv "wrote 12 W, read back" "$(read_or "$WMI_ATTRS/ppt_pl1_spl/current_value") W"
    # Ask for more than the firmware allows: it answers with its own maximum,
    # which is the real ceiling rather than a documented one.
    echo 99 > "$WMI_ATTRS/ppt_pl1_spl/current_value" 2>/dev/null
    kv "asked 99 W, firmware gave" "$(read_or "$WMI_ATTRS/ppt_pl1_spl/current_value") W"
    echo "$OLD_FPPT" > "$WMI_ATTRS/ppt_pl3_fppt/current_value" 2>/dev/null
    echo "$OLD_SPPT" > "$WMI_ATTRS/ppt_pl2_sppt/current_value" 2>/dev/null
    echo "$OLD_SPL" > "$WMI_ATTRS/ppt_pl1_spl/current_value" 2>/dev/null
    [ -n "$OLD_PP" ] && echo "$OLD_PP" > "$PP_DIR/profile" 2>/dev/null
    kv "restored" "spl=$(read_or "$WMI_ATTRS/ppt_pl1_spl/current_value") profile=$(read_or "$PP_DIR/profile")"
  elif [ "$HAVE_ACPI" = "1" ]; then
    OLD_SPL=$(hex2dec "$(acpi_get $SPL_ID)")
    OLD_MODE=$MODE
    kv "saved" "spl=${OLD_SPL} W mode=$MODE_NAME"
    acpi_do "\\_SB.GZFD.WMAA 0x00 0x2c 0xff" >/dev/null   # custom mode
    acpi_do "\\_SB.GZFD.WMAE 0x00 0x12 ${SPL_ID}0c000000" >/dev/null  # 12 W
    sleep 1
    kv "wrote 12 W, read back" "$(hex2dec "$(acpi_get $SPL_ID)") W"
    acpi_do "\\_SB.GZFD.WMAE 0x00 0x12 ${SPL_ID}63000000" >/dev/null  # 99 W
    kv "asked 99 W, firmware gave" "$(hex2dec "$(acpi_get $SPL_ID)") W"
    printf -v RESTORE '%02x' "$OLD_SPL"
    acpi_do "\\_SB.GZFD.WMAE 0x00 0x12 ${SPL_ID}${RESTORE}000000" >/dev/null
    kv "restored" "spl=$(hex2dec "$(acpi_get $SPL_ID)") W"
    if [ "$OLD_MODE" != "255" ]; then
      printf -v MODEHEX '0x%02x' "$OLD_MODE"
      acpi_do "\\_SB.GZFD.WMAA 0x00 0x2c $MODEHEX" >/dev/null
      kv "power mode restored" "$(hex2dec "$(acpi_mode)")"
    fi
  elif [ "$HAVE_RYZENADJ" = "1" ]; then
    kv "note" "no firmware path; testing ryzenadj instead"
    "$RYZENADJ_BIN" --stapm-limit=12000 --slow-limit=14000 --fast-limit=18000 2>&1 | sed 's/^/  /'
    "$RYZENADJ_BIN" --info 2>/dev/null | grep -Ei 'stapm|slow|fast' | sed 's/^/  /'
    kv "note" "put your own limits back from the plugin, or reboot"
  else
    kv "result" "nothing to write with"
  fi
fi

# ------------------------------------------------------------- conclusion ---
head1 "Conclusion"
if [ "$HAVE_WMI" = "1" ]; then
  kv "backend the plugin will use" "wmi - Lenovo firmware attributes (kernel driver)"
  kv "why" "lenovo-wmi-other is bound and a platform profile offers 'custom'"
elif [ "$HAVE_ACPI" = "1" ]; then
  kv "backend the plugin will use" "acpi - Lenovo firmware through acpi_call"
  kv "why" "no lenovo-wmi driver on this kernel, but GameZone answers"
elif [ "$HAVE_RYZENADJ" = "1" ]; then
  kv "backend the plugin will use" "ryzenadj - direct SMU"
  kv "why" "neither firmware interface is present on this kernel"
  say "  This works, but the firmware does not know about it: expect the EC to"
  say "  reassert its own limits on a charger transition or a mode change. The"
  say "  plugin watches for exactly that and re-applies."
else
  kv "backend the plugin will use" "none yet"
  say "  The plugin downloads its own verified ryzenadj on first run, which will"
  say "  give it the third path. For the firmware path, either run a kernel with"
  say "  the lenovo-wmi drivers (6.17+) or install acpi_call."
fi
say ""
