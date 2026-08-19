# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# Legion Go 1 port
# https://github.com/Rayekkk/LeGoTDP

"""acpi_call can arrive after the plugin has started.

It is a DKMS module and, on SteamOS, one the user installs by hand long after
boot. Probing once at startup and never again meant the fan section stayed
greyed out until the plugin was reloaded, with nothing on screen to say why.
"""
import unittest

from _harness import main

import ltdp_acpi
import ltdp_device


class AcpiRescan(unittest.TestCase):
    def setUp(self):
        self.probes = []
        self._saved = (main._acpi_available, main._acpi_probed_at,
                       ltdp_acpi.available, ltdp_acpi.reset_cache)
        main._dmi = lambda field: {"product_name": "83E1"}.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()
        main._acpi_available = False
        main._acpi_probed_at = None
        self.answer = False
        ltdp_acpi.available = self._probe
        ltdp_acpi.reset_cache = lambda: None

    def tearDown(self):
        (main._acpi_available, main._acpi_probed_at,
         ltdp_acpi.available, ltdp_acpi.reset_cache) = self._saved
        main._dmi = lambda field: ""
        main._wmi_only_cache = None
        ltdp_device.reset_cache()

    def _probe(self, force=False):
        self.probes.append(force)
        return self.answer

    def test_the_cached_answer_is_used_on_the_hot_path(self):
        """Applying limits must not modprobe and poke /proc every few seconds."""
        self.assertFalse(main._acpi_ready())
        self.assertEqual(self.probes, [])

    def test_asking_on_behalf_of_the_user_re_probes(self):
        self.assertFalse(main._acpi_ready(rescan=True))
        self.assertEqual(self.probes, [True])

    def test_a_module_installed_after_startup_is_picked_up(self):
        main._acpi_ready(rescan=True)
        self.answer = True                       # the user installed acpi_call
        main._acpi_probed_at = None               # and looked again later
        self.assertTrue(main._acpi_ready(rescan=True))
        self.assertTrue(main._acpi_ready())      # and it stays known

    def test_a_freshly_booted_machine_still_probes(self):
        """monotonic() counts from boot, so "never" cannot be spelled 0.0."""
        real = main.time.monotonic
        main.time.monotonic = lambda: 2.0        # two seconds of uptime
        try:
            main._acpi_probed_at = None
            self.assertFalse(main._acpi_ready(rescan=True))
        finally:
            main.time.monotonic = real
        self.assertEqual(self.probes, [True])

    def test_re_probing_is_rate_limited(self):
        main._acpi_ready(rescan=True)
        main._acpi_ready(rescan=True)
        main._acpi_ready(rescan=True)
        self.assertEqual(len(self.probes), 1)

    def test_a_working_interface_is_never_re_probed(self):
        main._acpi_available = True
        main._acpi_probed_at = None
        self.assertTrue(main._acpi_ready(rescan=True))
        self.assertEqual(self.probes, [])

    def test_hardware_that_does_not_speak_gamezone_is_never_probed(self):
        """Writing a method name into /proc/acpi/call is not for every machine."""
        main._dmi = lambda field: {"product_family": "Legion Go S 8APU1"}.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()
        main._acpi_probed_at = None
        self.assertFalse(main._acpi_ready(rescan=True))
        self.assertEqual(self.probes, [])

    def test_the_fan_state_asks_for_a_re_probe(self):
        """The panel reads this when it opens - which is when the user looks."""
        main._read_fan_state()
        self.assertEqual(self.probes, [True])


if __name__ == "__main__":
    unittest.main()
