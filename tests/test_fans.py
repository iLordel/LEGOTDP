# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# Legion Go 1 port
# https://github.com/Rayekkk/LeGoTDP

"""Fans and temperatures, with the transport and hwmon replaced.

The fan curve is the one place in this plugin where a wrong number is felt
rather than merely reported, so the shape of the payload, the floor under every
curve and the standing-down behaviour are all pinned here.
"""
import os
import shutil
import tempfile
import unittest

from _harness import FIXTURE, main, seed

import ltdp_acpi


class FanCurve(unittest.TestCase):
    """Ten points, never below what the firmware itself allows."""

    def test_the_floor_is_the_firmwares_own_minimum(self):
        self.assertEqual(ltdp_acpi.clamp_fan_curve([0] * 10),
                         list(ltdp_acpi.FAN_CURVE_MIN))

    def test_a_short_curve_is_filled_from_the_floor(self):
        filled = ltdp_acpi.clamp_fan_curve([60, 60])
        self.assertEqual(len(filled), 10)
        self.assertEqual(filled[2:], list(ltdp_acpi.FAN_CURVE_MIN[2:]))

    def test_nothing_may_exceed_the_hardware_maximum(self):
        self.assertEqual(ltdp_acpi.clamp_fan_curve([250] * 10),
                         [ltdp_acpi.FAN_CURVE_MAX_VALUE] * 10)

    def test_every_shipped_curve_clears_the_floor(self):
        for name, curve in main.FAN_CURVES.items():
            self.assertEqual(list(curve), ltdp_acpi.clamp_fan_curve(curve), name)

    def test_every_shipped_curve_rises_with_temperature(self):
        for name, curve in main.FAN_CURVES.items():
            self.assertEqual(list(curve), sorted(curve), name)

    def test_a_close_read_back_counts_as_a_match(self):
        """The firmware rounds; chasing the last percent would never settle."""
        self.assertTrue(ltdp_acpi.curves_match([44] * 10, [45] * 10))
        self.assertFalse(ltdp_acpi.curves_match([44] * 10, [55] * 10))
        self.assertFalse(ltdp_acpi.curves_match([44] * 10, []))

    def test_the_write_payload_is_the_shape_the_firmware_expects(self):
        sent = {}
        saved = (ltdp_acpi.call, ltdp_acpi.get_fan_curve, ltdp_acpi.available)
        curve = [50, 55, 60, 65, 75, 80, 90, 95, 100, 100]
        try:
            ltdp_acpi.available = lambda force=False: True
            ltdp_acpi.get_fan_curve = lambda: curve
            ltdp_acpi.call = lambda method, args: sent.update(
                {"method": method, "args": args})
            self.assertTrue(ltdp_acpi.set_fan_curve(curve))
        finally:
            ltdp_acpi.call, ltdp_acpi.get_fan_curve, ltdp_acpi.available = saved

        self.assertEqual(sent["method"], ltdp_acpi.METHOD_FAN)
        payload = sent["args"][2]
        self.assertEqual(len(payload), 52)
        # Ten speeds as little-endian pairs, right after the six-byte header.
        self.assertEqual([payload[6 + i * 2] for i in range(10)], curve)
        # Then the ten temperature points the curve is indexed by.
        self.assertEqual([payload[31 + i * 2] for i in range(10)],
                         list(ltdp_acpi.FAN_CURVE_TEMPS))


class FanModes(unittest.TestCase):
    """Mode changes reach the firmware, and are defended once they have."""

    def setUp(self):
        seed(FIXTURE)
        self.calls = []
        self.curve = list(ltdp_acpi.FAN_CURVE_MIN)
        self.full = False
        self._saved = (main._fan_available, ltdp_acpi.set_fan_curve,
                       ltdp_acpi.get_fan_curve, ltdp_acpi.set_full_fan_speed,
                       ltdp_acpi.get_full_fan_speed, ltdp_acpi.reset_fan_curve)
        main._fan_available = lambda: True
        ltdp_acpi.set_fan_curve = self._set_curve
        ltdp_acpi.get_fan_curve = lambda: list(self.curve)
        ltdp_acpi.set_full_fan_speed = self._set_full
        ltdp_acpi.get_full_fan_speed = lambda: self.full
        ltdp_acpi.reset_fan_curve = self._reset
        main._fan_target = ()
        main._fan_attempts = 0

    def tearDown(self):
        (main._fan_available, ltdp_acpi.set_fan_curve, ltdp_acpi.get_fan_curve,
         ltdp_acpi.set_full_fan_speed, ltdp_acpi.get_full_fan_speed,
         ltdp_acpi.reset_fan_curve) = self._saved
        main._fan_target = ()
        main._fan_attempts = 0

    def _set_curve(self, curve):
        self.calls.append(("curve", list(curve)))
        self.curve = list(curve)
        return True

    def _set_full(self, enabled):
        self.calls.append(("full", enabled))
        self.full = enabled
        return True

    def _reset(self):
        self.calls.append(("reset",))
        self.curve = list(ltdp_acpi.FAN_CURVE_MIN)
        return True

    def test_a_curve_mode_writes_that_curve(self):
        self.assertTrue(main._apply_fan_mode("cool")["success"])
        self.assertEqual(self.curve, list(main.FAN_CURVES["cool"]))

    def test_auto_hands_the_curve_back_to_the_firmware(self):
        self.assertTrue(main._apply_fan_mode("auto")["success"])
        self.assertIn(("reset",), self.calls)
        self.assertEqual(main._fan_target, ())

    def test_max_turns_on_full_speed(self):
        self.assertTrue(main._apply_fan_mode("max")["success"])
        self.assertTrue(self.full)

    def test_leaving_max_turns_it_off_before_writing_a_curve(self):
        main._apply_fan_mode("max")
        self.calls.clear()
        main._apply_fan_mode("quiet")
        self.assertEqual(self.calls[0], ("full", False))
        self.assertFalse(self.full)

    def test_an_unknown_mode_is_refused(self):
        self.assertFalse(main._apply_fan_mode("turbo")["success"])

    def test_the_curve_is_written_back_when_the_firmware_wipes_it(self):
        main._apply_fan_mode("balanced")
        # Every TDP apply moves the power mode, and that resets the curve.
        self.curve = list(ltdp_acpi.FAN_CURVE_MIN)
        self.calls.clear()
        main._enforce_fan()
        self.assertEqual(self.curve, list(main.FAN_CURVES["balanced"]))

    def test_a_curve_that_still_matches_is_left_alone(self):
        main._apply_fan_mode("balanced")
        self.calls.clear()
        main._enforce_fan()
        self.assertEqual(self.calls, [])

    def test_it_stands_down_rather_than_rewriting_forever(self):
        main._apply_fan_mode("balanced")
        ltdp_acpi.set_fan_curve = lambda curve: False
        ltdp_acpi.get_fan_curve = lambda: list(ltdp_acpi.FAN_CURVE_MIN)
        for _ in range(6):
            main._enforce_fan()
        self.assertEqual(main._fan_attempts, main.FAN_MAX_ATTEMPTS)

    def test_auto_needs_no_defending(self):
        main._apply_fan_mode("auto")
        self.calls.clear()
        main._enforce_fan()
        self.assertEqual(self.calls, [])

    def test_a_system_without_the_firmware_interface_says_so(self):
        main._fan_available = lambda: False
        result = main._apply_fan_mode("quiet")
        self.assertFalse(result["success"])
        self.assertIn("acpi_call", result["stderr"])


class Temperatures(unittest.TestCase):
    """Read from hwmon, so they work whichever backend drives the limits."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ltdp-hwmon-")
        self._glob = main.HWMON_GLOB
        main._hwmon_cache.clear()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(setattr, main, "HWMON_GLOB", self._glob)
        self.addCleanup(main._hwmon_cache.clear)
        main.HWMON_GLOB = os.path.join(self.root, "hwmon*")

    def _hwmon(self, name: str, files: dict):
        base = os.path.join(self.root, f"hwmon{len(os.listdir(self.root))}")
        os.makedirs(base)
        with open(os.path.join(base, "name"), "w") as handle:
            handle.write(name)
        for leaf, value in files.items():
            with open(os.path.join(base, leaf), "w") as handle:
                handle.write(str(value))

    def test_millidegrees_become_degrees(self):
        self._hwmon("k10temp", {"temp1_input": 57200})
        self.assertEqual(main._cpu_temp(), 57.2)

    def test_an_unrelated_sensor_is_ignored(self):
        self._hwmon("acpitz", {"temp1_input": 25000})
        self.assertIsNone(main._cpu_temp())

    def test_fan_speeds_come_from_the_lenovo_driver(self):
        self._hwmon("lenovo_wmi_other", {"fan1_input": 2400, "fan2_input": 2600})
        self.assertEqual(main._fan_rpms(), [2400, 2600])

    def test_no_sensors_is_not_an_error(self):
        self.assertIsNone(main._cpu_temp())
        self.assertEqual(main._fan_rpms(), [])


if __name__ == "__main__":
    unittest.main()
