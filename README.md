<div align="center">

# LTDP

**TDP control for the original Lenovo Legion Go (83E1, Ryzen Z1 Extreme), from the Steam overlay.**

A Decky Loader plugin for SteamOS Gaming Mode — firmware-first, per-game profiles,
a separate charger profile, live power draw, English and Russian.

[![Build](https://github.com/LORDEL/LTDP/actions/workflows/build.yml/badge.svg)](https://github.com/LORDEL/LTDP/actions/workflows/build.yml)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](LICENSE)
[![Decky Loader](https://img.shields.io/badge/Decky-plugin-5c5cff.svg)](https://decky.xyz)

[Установка и описание по-русски →](README.ru.md)

</div>

---

> **Status: tested on hardware.**
> Run and verified on a Legion Go 1 (`83E1`, Ryzen Z1 Extreme) against the
> [checklist below](#verifying-on-hardware) — limits apply and hold, per-game
> profiles switch, and the charger and suspend/resume transitions do not knock
> them off. On top of that, 212 automated tests cover every code path with DMI,
> sysfs and the ACPI transport stubbed.
>
> Your kernel decides which backend you get, so if anything behaves differently
> on your machine, [the diagnostic script](#diagnostics) says why in ten seconds
> — please attach its output to an issue.

---

## Why a separate plugin

[LeGoTDP](https://github.com/Rayekkk/LeGoTDP) is an excellent plugin for the
**Legion Go 2** and the **Legion Go S**. The original Legion Go is a different
machine: a different firmware range, a different preset ladder, and — on the
kernel SteamOS ships today — a completely different way of reaching the firmware
at all. Handing it another device's numbers is worse than handing it none, so
this fork gives it its own device profile and its own control path.

| | LTDP (Legion Go 1) | upstream LeGoTDP |
|---|---|---|
| Device | `83E1` / `Legion Go 8APU1` | `83N0`, `83N1` (Go 2) · `83L3`, `83N6`, `83Q2`, `83Q3` (Go S) |
| SoC | Ryzen Z1 Extreme (Phoenix) | Z2 Extreme · Z1E · Z2 Go |
| Firmware range | **5 – 30 / 32 / 41 W** | 35/37/45 (Go 2) · 40/43/53 (Go S) |
| Backends | firmware attributes → **acpi_call** → ryzenadj | firmware attributes → ryzenadj |
| Unlocked ceiling | 40 / 43 / 50 W | 50 W |

The device table keeps all four machines apart, and every value is clamped again
at runtime against what the firmware itself reports.

## Features

- **Presets** — Minimum, Silent, Balanced, Performance, Max, plus Custom, spaced
  against Lenovo's own modes for this machine rather than another one's.
- **Manual SPL / SPPT / FPPT sliders**, with `SPL ≤ SPPT ≤ FPPT` enforced on both
  sides, so an impossible combination cannot be requested.
- **Per-game profiles** — applied automatically when a game launches, global
  settings restored when it exits.
- **Separate charger profile** — globally and per game, switched automatically
  when the charger goes in or out.
- **Drift correction** — when the firmware or another tool moves the limits they
  are put back; after a few refusals the plugin stands down instead of fighting
  the hardware forever (the Go 1 BIOS lowers TDP by itself when the SoC gets hot,
  and that is thermal protection, not drift).
- **Charger transition handling** — Lenovo's firmware applies its own profile a
  moment *after* the transition, so the target is re-asserted over the seconds
  that follow (0.5 / 1.5 / 3 / 6 / 10 s) until one of them is the last word.
- **Suspend / resume** — limits are restored the moment Steam reports the wake.
- **Live readings** — the limit that is set and the power actually being drawn,
  labelled as the two different numbers they are.
- **Diagnostics in the panel** — device, CPU, BIOS, kernel, which backends exist,
  which one is active, the ranges and where they came from.
- **Conflict warnings** — HHD, adjustor, PowerStation, SimpleDeckyTDP,
  PowerControl or an upstream LeGoTDP install are reported rather than silently
  fought.
- **English and Russian**, switched in the panel and remembered.

## How it works

Three ways to reach the hardware, probed at startup and used in this order.

### 1 · Lenovo firmware attributes (`wmi`) — preferred

`/sys/class/firmware-attributes/lenovo-wmi-other-*/attributes/ppt_pl{1,2,3}_*`
plus a `platform-profile` that offers `custom`. This is the in-kernel
`lenovo-wmi-other` driver, mainline since **Linux 6.17**. It publishes
`min_value` / `max_value` per parameter, so the real range is read from the
firmware instead of assumed. The firmware only honours a write while the
platform profile is `custom`, so the plugin selects it first.

### 2 · Lenovo firmware through `acpi_call` (`acpi`)

The same firmware interface, reached through `/proc/acpi/call` when the kernel
has no driver for it — which is the case on the kernel SteamOS 3.7 ships. This is
the path [Handheld Daemon](https://github.com/hhd-dev/adjustor) has used on this
machine since 2024:

```
\_SB.GZFD.WMAA 0x00 0x2C 0xFF          # enter the custom power mode
\_SB.GZFD.WMAE 0x00 0x12 <id><value>   # set SPL / SPPT / FPPT
\_SB.GZFD.WMAE 0x00 0x11 <id>          # read it back
```

with `id = device<<24 | feature<<16 | mode<<8 | type` — SPL `0x0102FF00`,
SPPT `0x0101FF00`, FPPT `0x0103FF00`, matching
`drivers/platform/x86/lenovo/wmi-other.c` exactly. Every write is verified by
reading it back. Note that `acpi_call` is **not** shipped by SteamOS; it needs a
DKMS install.

### 3 · `ryzenadj` — last resort

On a stock SteamOS 3.7 install with neither of the above, this is the only thing
that works, so it stays. It also backs the unlocked range and cross-checks the
firmware's own bookkeeping against a live read of the SMU. The plugin downloads a
SHA-256 verified build on first run; if that download fails it falls back to a
`ryzenadj` already installed on the system, and says so.

## Presets

| Preset | SPL | SPPT | FPPT |
|---|---|---|---|
| Minimum | 5 W | 7 W | 10 W |
| Silent | 8 W | 10 W | 14 W |
| Balanced | 15 W | 17 W | 22 W |
| Performance | 20 W | 22 W | 28 W |
| Max | 30 W | 32 W | 41 W |
| Custom | 5 W … firmware maximum | | |

Beyond the firmware ceiling there is an opt-in **Extras** range reaching
40 / 43 / 50 W through ryzenadj. It is off by default and deliberately modest:
this chassis has a 30 W firmware ceiling for a reason, and the point of the
switch is headroom, not a bigger number.

## Install

Requires [Decky Loader](https://decky.xyz).

1. Download `LTDP-<version>.zip` from [Releases](https://github.com/LORDEL/LTDP/releases)
   and copy it to the device.
2. Gaming Mode → **Steam (⋯) → Decky → gear icon → Developer**.
3. **Install Plugin from ZIP** → pick the file.
4. **LTDP** appears in the Quick Access Menu.

If upstream **LeGoTDP** is installed, remove it first — two plugins driving the
same three limits overwrite each other.

Check what it picked:

```bash
sudo journalctl -u plugin_loader -n 100 --no-pager | grep ltdp
```

The line `ready on Lenovo Legion Go 1 (Z1 Extreme): backend=…` names the backend
and the range it determined.

## Diagnostics

The script ships inside the plugin and needs nothing else installed — it can even
be run before installing anything:

```bash
sudo /home/deck/homebrew/plugins/LTDP/scripts/ltdp-diagnostics.sh
```

It reports the DMI model, BIOS and kernel versions, the state of the
`lenovo_wmi_*` and `acpi_call` modules, every firmware attribute with its
min/max/current, the platform profile and its choices, whether GameZone answers
over acpi_call, the ryzenadj binary, RAPL package draw, conflicting processes and
plugins — and concludes with **which backend will be used and why**.

To prove writes land, and to ask the firmware for its real ceiling (it clamps a
deliberately excessive request to its own maximum, which is the number worth
knowing):

```bash
sudo ./ltdp-diagnostics.sh --write-test
```

It restores the previous values afterwards.

## Verifying on hardware

The port is not finished until all of these hold on a real device:

1. TDP changes — preset and slider.
2. The value actually applies (Diagnostics → *Currently set* agrees).
3. It has not reset itself 30–60 seconds later.
4. It has not reset after launching a game.
5. A per-game profile applies automatically.
6. The global profile comes back on exit.
7. AC / battery switching works both ways.
8. Suspend and resume do not break it.
9. Plugging the charger in does not reset it.
10. Gaming Mode stays stable, with no `[ltdp]` errors in the journal.

The device half of the test suite covers several of these directly:

```bash
cd /home/deck/homebrew/plugins/LTDP
sudo LTDP_PLUGIN_DIR=$PWD python3 -m unittest discover -s tests -t tests -v
```

Tests that need an interface the machine does not have skip themselves.

## Building

```bash
npm install
npm run typecheck
npm run build
npm run package        # -> LTDP-<version>.zip
python -m unittest discover -s tests -t tests
```

The archive is built by 7-Zip, `zip`, or Python's `zipfile`, whichever is
present — always with forward slashes, and with the diagnostic script marked
executable.

Automatic update checks are disabled in this build, because the releases they
would find belong to a project with a different device table. To enable them for
a fork of your own, point `GITHUB_RELEASES_URL` at your repository and set
`UPDATE_CHECKS_ENABLED = True` in `main.py`.

## Compatibility

Do not run these at the same time as LTDP — each of them sets the same limits:

- **Handheld Daemon** (`hhd` / `adjustor`) — uses the same acpi_call path
- **SimpleDeckyTDP**, **PowerControl** — the same firmware attributes, or ryzenadj
- **SteamOS's own TDP slider**, where it is active on this device
- **upstream LeGoTDP**, and this plugin under its former name `LeGoTDP-LegionGo1`

LTDP detects them and warns; it does not block them. The choice is yours.

## Safety

The firmware's own maximum is the primary limit. Sliders stop there unless the
user explicitly unlocks Extras, which is only possible when ryzenadj is
available. Nothing here bypasses a hardware limit silently, and turning the
plugin off — or uninstalling it — hands the machine back to a normal Lenovo
power mode.

## Credits

- **LTDP** — Legion Go 1 port by **LORDEL**.
- **[LeGoTDP](https://github.com/Rayekkk/LeGoTDP)** by [Rayekkk](https://github.com/Rayekkk)
  — the plugin this is forked from; the settings, per-game, drift and charger
  logic are its work.
- **[hhd-dev/adjustor](https://github.com/hhd-dev/adjustor)** — the Lenovo
  GameZone interface as it is actually used on this machine.
- **`drivers/platform/x86/lenovo/`** in the mainline kernel, by Derek J. Clark —
  the authority on the WMI attribute encoding and the custom-mode rule.
- **[aarron-lee/legion-go-tricks](https://github.com/aarron-lee/legion-go-tricks)**
  and **[SimpleDeckyTDP](https://github.com/aarron-lee/SimpleDeckyTDP)** — the
  practical Legion Go on Linux knowledge.
- **[RyzenAdj](https://github.com/FlyGoat/RyzenAdj)** (LGPL-3.0) — downloaded on
  the device, never bundled. See [NOTICE](NOTICE).

## License

BSD 3-Clause — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
