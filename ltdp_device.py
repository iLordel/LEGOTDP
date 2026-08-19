# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# Legion Go 1 port
# https://github.com/Rayekkk/LeGoTDP

"""Device identity and per-machine hardware capability profiles.

One profile per machine, keyed on DMI. The original Legion Go, the Legion Go 2
and the two Legion Go S variants are deliberately kept apart: they do not share
a firmware TDP range, a preset ladder, or even the same working control path,
so a profile that fits one is wrong on the others.

This module is standalone on purpose - it imports nothing outside the standard
library, so the diagnostic script and the test suite can use it without
DeckyLoader present.
"""

import os

DMI_DIR = "/sys/class/dmi/id"


def dmi(field: str) -> str:
    try:
        with open(os.path.join(DMI_DIR, field)) as f:
            return f.read().strip()
    except OSError:
        return ""


def cpu_model() -> str:
    """`model name` from /proc/cpuinfo, or ''."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def bios_number(raw: str = "") -> int:
    """The numeric part of a Lenovo BIOS string, or 0.

    Lenovo numbers this family `N3CN<nn>WW` - N3CN40WW is the January 2026
    release. Parsed the same way Handheld Daemon does it, because that is the
    only scheme this machine has ever used.
    """
    raw = raw or dmi("bios_version")
    digits = "".join(c for c in raw.replace("N3CN", "", 1).split("WW")[0] if c.isdigit())
    try:
        return int(digits)
    except ValueError:
        return 0


def kernel_release() -> str:
    try:
        with open("/proc/sys/kernel/osrelease") as f:
            return f.read().strip()
    except OSError:
        return ""


# Backend identifiers, in the order they are preferred when a device lists more
# than one. "wmi" is the in-kernel Lenovo firmware-attributes interface,
# "acpi" is the same firmware reached through acpi_call when that driver is
# absent, and "ryzenadj" pokes the SMU directly.
BACKEND_WMI = "wmi"
BACKEND_ACPI = "acpi"
BACKEND_RYZENADJ = "ryzenadj"


# -- Preset ladders, in watts -------------------------------------------------
#
# Spaced against what each machine's firmware actually accepts, so "Max" is the
# top of that machine's hardware rather than a number carried over from another
# device. Every ladder is clamped again at runtime against the range the
# firmware reports, so a ladder can never push a slider past the hardware.

# The original Legion Go (83E1, Ryzen Z1 Extreme, Phoenix).
#
# Lenovo's own modes on this machine are quiet 8 W, balanced 15 W,
# performance 20 W, and custom anywhere from 5 W to 30 W - the same 30 / 32 / 41
# ceiling Handheld Daemon uses for it. The ladder below sits on those numbers
# rather than on the Legion Go 2's, whose firmware goes to 35 / 37 / 45.
PRESETS_LEGION_GO_1 = {
    "minimum":     {"spl": 5,  "sppt": 7,  "fppt": 10},
    "silent":      {"spl": 8,  "sppt": 10, "fppt": 14},
    "balanced":    {"spl": 15, "sppt": 17, "fppt": 22},
    "performance": {"spl": 20, "sppt": 22, "fppt": 28},
    "max":         {"spl": 30, "sppt": 32, "fppt": 41},
}

# Legion Go 2 and anything unrecognised: the upstream ladder.
PRESETS_DEFAULT = {
    "minimum":     {"spl": 5,  "sppt": 5,  "fppt": 10},
    "silent":      {"spl": 8,  "sppt": 10, "fppt": 15},
    "balanced":    {"spl": 15, "sppt": 18, "fppt": 25},
    "performance": {"spl": 25, "sppt": 28, "fppt": 35},
    "max":         {"spl": 35, "sppt": 37, "fppt": 45},
}

# Legion Go S: 40 / 43 / 53 W is exactly what its firmware reports.
PRESETS_LEGION_GO_S = {
    "minimum":     {"spl": 5,  "sppt": 8,  "fppt": 10},
    "silent":      {"spl": 8,  "sppt": 10, "fppt": 15},
    "balanced":    {"spl": 18, "sppt": 20, "fppt": 25},
    "performance": {"spl": 33, "sppt": 33, "fppt": 35},
    "max":         {"spl": 40, "sppt": 43, "fppt": 53},
}


class DeviceProfile:
    """What one machine can do, and how to talk to it.

    `fallback_caps` is only consulted when the firmware will not report its own
    range - the in-kernel interface publishes min_value/max_value per parameter
    and that always wins. On the acpi_call path there is no equivalent to read
    (capability data lives behind a WMI data block the driver reads, not behind
    a GZFD method), so the documented firmware range is used instead and every
    write is verified by reading it back.
    """

    def __init__(self, key, label, short, products=(), versions=(), families=(),
                 presets=None, fallback_caps=None, extras_caps=None,
                 backends=(BACKEND_WMI, BACKEND_RYZENADJ),
                 ac_settle=(0.5, 1.5, 3.0, 6.0), cpu_label="", notes=(),
                 bios_baseline=0, bios_withdrawn=()):
        self.key = key
        self.label = label
        self.short = short
        self.products = tuple(p.lower() for p in products)
        self.versions = tuple(v.lower() for v in versions)
        self.families = tuple(f.lower() for f in families)
        self.presets = presets or PRESETS_DEFAULT
        self.fallback_caps = fallback_caps or {
            "spl": (5, 35), "sppt": (5, 37), "fppt": (5, 45)}
        self.extras_caps = extras_caps
        self.backends = tuple(backends)
        self.ac_settle = tuple(ac_settle)
        self.cpu_label = cpu_label
        self.notes = tuple(notes)
        # The firmware this build is written against, and any release the
        # vendor has taken back. Both are numbers from the N3CN<nn>WW scheme.
        self.bios_baseline = bios_baseline
        self.bios_withdrawn = tuple(bios_withdrawn)

    def bios_status(self, number: int = -1) -> str:
        """How the installed BIOS relates to the one this build targets.

        Reported, never acted on: the plugin does not change its behaviour
        based on this, it only says what it sees. "withdrawn" is the one worth
        surfacing - Lenovo pulled N3CN42WW after boot failures were reported,
        and a machine running it cannot get back to 40 through the vendor.
        """
        if number < 0:
            number = bios_number()
        if not number or not self.bios_baseline:
            return "unknown"
        if number in self.bios_withdrawn:
            return "withdrawn"
        if number == self.bios_baseline:
            return "baseline"
        return "older" if number < self.bios_baseline else "newer"

    # -- capability queries ---------------------------------------------------

    @property
    def firmware_only(self) -> bool:
        """True when this machine is driven through its firmware alone."""
        return BACKEND_RYZENADJ not in self.backends

    @property
    def supports_acpi_call(self) -> bool:
        return BACKEND_ACPI in self.backends

    def matches(self, product: str, version: str, family: str) -> bool:
        """Each DMI field is matched on its own.

        Joining them first would let a name straddle the seam - "Legion Go"
        followed by a version starting with "S" would read as "legion go s" and
        take a Go 2 down the wrong path.
        """
        product, version, family = product.lower(), version.lower(), family.lower()
        if any(product == p for p in self.products):
            return True
        if any(v in version for v in self.versions):
            return True
        if any(f in family for f in self.families):
            return True
        return False

    def fallback_range(self, key: str) -> tuple:
        return self.fallback_caps.get(key, (5, 30))

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "short": self.short,
            "cpu_label": self.cpu_label,
            "backends": list(self.backends),
            "firmware_only": self.firmware_only,
            "fallback_caps": {k: {"min": v[0], "max": v[1]}
                              for k, v in self.fallback_caps.items()},
            "extras_caps": dict(self.extras_caps) if self.extras_caps else {},
            "presets": self.presets,
            "notes": list(self.notes),
        }


# -- The device table ---------------------------------------------------------
#
# DMI product_name is the SKU code and is the primary key; product_version is
# the human-readable name Lenovo puts next to it ("Legion Go 8APU1"), and is
# matched as a fallback for firmware revisions that leave the SKU blank.

LEGION_GO_1 = DeviceProfile(
    key="legion_go_1",
    label="Lenovo Legion Go 1 (Z1 Extreme)",
    short="Legion Go 1",
    products=("83e1",),
    versions=("legion go 8apu1",),
    cpu_label="AMD Ryzen Z1 Extreme",
    presets=PRESETS_LEGION_GO_1,
    # 30 / 32 / 41 W is what this firmware accepts in custom mode. The floor is
    # 5 W: Lenovo's own custom mode bottoms out there.
    fallback_caps={"spl": (5, 30), "sppt": (5, 32), "fppt": (5, 41)},
    # Only reachable through ryzenadj, only after the user unlocks it, and
    # deliberately modest: this chassis has a 30 W firmware ceiling for a
    # reason and the point of the switch is headroom, not a bigger number.
    extras_caps={"spl": 40, "sppt": 43, "fppt": 50},
    backends=(BACKEND_WMI, BACKEND_ACPI, BACKEND_RYZENADJ),
    # The Legion Go 1 firmware re-applies its own power profile on a charger
    # transition, and does it late, so the re-settle ladder needs a longer tail
    # than the one that suffices on a Go S.
    ac_settle=(0.5, 1.5, 3.0, 6.0, 10.0),
    # N3CN40WW, January 2026, is what this build is written against. N3CN42WW
    # (June 2026) was withdrawn by Lenovo after handhelds failed to boot, and
    # the download is gone, so a machine on it has no vendor path back.
    bios_baseline=40,
    bios_withdrawn=(42,),
    notes=(
        "Custom TDP is only honoured while the firmware is in its custom power "
        "mode; the plugin selects that mode before every write.",
        "The BIOS lowers TDP by itself when the SoC gets hot. That is thermal "
        "protection, not drift, and the plugin stands down rather than fight it.",
    ),
)

LEGION_GO_2 = DeviceProfile(
    key="legion_go_2",
    label="Lenovo Legion Go 2",
    short="Legion Go 2",
    products=("83n0", "83n1"),
    cpu_label="AMD Ryzen Z2 Extreme",
    presets=PRESETS_DEFAULT,
    fallback_caps={"spl": (5, 35), "sppt": (5, 37), "fppt": (5, 45)},
    extras_caps={"spl": 50, "sppt": 50, "fppt": 50},
    backends=(BACKEND_WMI, BACKEND_RYZENADJ),
)

LEGION_GO_S = DeviceProfile(
    key="legion_go_s",
    label="Lenovo Legion Go S",
    short="Legion Go S",
    products=("83l3", "83n6", "83q2", "83q3"),
    families=("legion go s",),
    presets=PRESETS_LEGION_GO_S,
    fallback_caps={"spl": (5, 40), "sppt": (5, 43), "fppt": (5, 53)},
    # Firmware alone. ryzenadj is not downloaded here, so there is no second
    # tool to hand an out-of-range request to.
    backends=(BACKEND_WMI,),
)

GENERIC = DeviceProfile(
    key="generic",
    label="Unrecognised AMD handheld",
    short="Generic",
    presets=PRESETS_DEFAULT,
    fallback_caps={"spl": (5, 35), "sppt": (5, 37), "fppt": (5, 45)},
    extras_caps={"spl": 50, "sppt": 50, "fppt": 50},
    backends=(BACKEND_WMI, BACKEND_RYZENADJ),
)

DEVICES = (LEGION_GO_1, LEGION_GO_2, LEGION_GO_S)

_cached = None


def detect(dmi_reader=dmi):
    """The profile for the hardware in front of us.

    Read once per process: DMI does not change while the machine is running.
    `dmi_reader` is injectable so the tests can drive every branch.
    """
    global _cached
    if _cached is None:
        product = dmi_reader("product_name")
        version = dmi_reader("product_version")
        family = dmi_reader("product_family")
        _cached = next(
            (d for d in DEVICES if d.matches(product, version, family)), GENERIC)
    return _cached


def reset_cache() -> None:
    global _cached
    _cached = None
