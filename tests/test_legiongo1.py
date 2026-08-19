# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# Legion Go 1 port
# https://github.com/Rayekkk/LeGoTDP

"""The Legion Go 1 half of the suite: device table, backends, ranges.

Nothing here touches hardware. The DMI reader, the firmware attributes and the
acpi_call transport are all replaced, so every branch runs the same way on a
build machine as it does on the device - which is the point, because the whole
reason this file exists is that a Legion Go 1 must not be handed a Legion Go 2's
numbers.
"""
import unittest

from _harness import main, seed, FIXTURE

import ltdp_acpi
import ltdp_device


class DeviceIdentity(unittest.TestCase):
    """Each machine has to land on its own profile, and only its own."""

    GO_1 = {"product_name": "83E1", "product_version": "Legion Go 8APU1",
            "product_family": "Legion Go"}
    GO_2 = {"product_name": "83N0", "product_version": "Legion Go 2",
            "product_family": "Legion Go 2"}
    GO_S_Z1 = {"product_name": "83N6", "product_version": "Legion Go S 8APU1",
               "product_family": "Legion Go S 8APU1"}
    GO_S_Z2 = {"product_name": "83L3", "product_version": "Legion Go S",
               "product_family": "Legion Go S 8ARP1"}
    STEAM_DECK = {"product_name": "Jupiter", "product_version": "1",
                  "product_family": "Sephiroth"}

    def _as(self, dmi: dict):
        main._dmi = lambda field: dmi.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()

    def tearDown(self):
        main._dmi = lambda field: ""
        main._wmi_only_cache = None
        ltdp_device.reset_cache()

    def test_the_original_legion_go_gets_its_own_profile(self):
        self._as(self.GO_1)
        self.assertEqual(main._device().key, "legion_go_1")

    def test_the_sku_code_is_enough_on_its_own(self):
        """Some firmware revisions leave product_version blank."""
        self._as({"product_name": "83E1"})
        self.assertEqual(main._device().key, "legion_go_1")

    def test_the_marketing_name_is_enough_on_its_own(self):
        self._as({"product_version": "Legion Go 8APU1"})
        self.assertEqual(main._device().key, "legion_go_1")

    def test_a_legion_go_2_is_not_a_legion_go_1(self):
        self._as(self.GO_2)
        self.assertEqual(main._device().key, "legion_go_2")

    def test_a_legion_go_s_z1_extreme_is_not_a_legion_go_1(self):
        """Same CPU, different machine, and a different firmware range."""
        self._as(self.GO_S_Z1)
        self.assertEqual(main._device().key, "legion_go_s")

    def test_a_legion_go_s_z2_go_is_not_a_legion_go_1(self):
        self._as(self.GO_S_Z2)
        self.assertEqual(main._device().key, "legion_go_s")

    def test_the_go_s_family_string_cannot_swallow_a_go_1(self):
        """'Legion Go' is a prefix of 'Legion Go S'; the match must not be."""
        self._as(self.GO_1)
        self.assertFalse(main._wmi_only())

    def test_unknown_hardware_falls_back_to_generic(self):
        self._as(self.STEAM_DECK)
        self.assertEqual(main._device().key, "generic")

    def test_only_the_go_s_is_firmware_only(self):
        self._as(self.GO_S_Z1)
        self.assertTrue(main._wmi_only())
        self._as(self.GO_1)
        self.assertFalse(main._wmi_only())


class LegionGo1Ranges(unittest.TestCase):
    """The Go 1 firmware takes 30 / 32 / 41 W, and nothing here may exceed it."""

    def setUp(self):
        seed(FIXTURE)
        self._caps = main._wmi_caps
        main._dmi = lambda field: {"product_name": "83E1"}.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()
        main._wmi_caps = lambda: {}          # firmware will not answer
        main._ryzenadj_available = False

    def tearDown(self):
        main._wmi_caps = self._caps
        main._dmi = lambda field: ""
        main._wmi_only_cache = None
        main._ryzenadj_available = False
        ltdp_device.reset_cache()

    def test_the_fallback_range_is_the_go_1_range(self):
        self.assertEqual(main._standard_ceilings_mw(), (30000, 32000, 41000))

    def test_the_floor_is_five_watts(self):
        self.assertEqual(main._fallback_min_w(), 5)

    def test_a_go_2_profile_is_clamped_down_to_go_1_hardware(self):
        """35 / 37 / 45 W is a Legion Go 2 preset. This machine takes 30 / 32 / 41.

        A profile copied over from another machine - or carried across by a
        settings file - has to come back inside this firmware's range before it
        reaches the hardware.
        """
        self.assertEqual(main._clamp_for_settings({}, 35000, 37000, 45000),
                         (30000, 32000, 41000))

    def test_the_absolute_clamp_stops_at_the_go_1_extras_ceiling(self):
        """Even the widest bound on this machine is 40 W, not the 50 W a Go 2 takes."""
        self.assertEqual(main._clamp_triplet(60000, 60000, 60000),
                         (40000, 43000, 50000))

    def test_the_firmware_range_wins_over_the_table_when_it_answers(self):
        main._wmi_caps = lambda: {"spl":  {"min": 5, "max": 28},
                                  "sppt": {"min": 5, "max": 30},
                                  "fppt": {"min": 5, "max": 38}}
        self.assertEqual(main._standard_ceilings_mw(), (28000, 30000, 38000))

    def test_extras_stops_at_forty_watts_not_fifty(self):
        """A Go 2 unlocks to 50 W. This chassis does not, and must not be offered it."""
        main._ryzenadj_available = True
        self.assertEqual(main._ceilings_mw(), (40000, 43000, 50000))

    def test_extras_is_unavailable_without_ryzenadj(self):
        state = {"extras_unlocked": True}
        self.assertEqual(main._allowed_ceilings_mw(state), (30000, 32000, 41000))

    def test_the_preset_ladder_is_the_go_1_ladder(self):
        presets = main._presets()
        self.assertEqual(presets["max"], {"spl": 30, "sppt": 32, "fppt": 41})
        self.assertEqual(presets["balanced"], {"spl": 15, "sppt": 17, "fppt": 22})
        self.assertNotEqual(presets, main.PRESETS_DEFAULT)
        self.assertNotEqual(presets, main.PRESETS_LEGION_GO_S)

    def test_every_preset_fits_inside_the_firmware_range(self):
        spl_max, sppt_max, fppt_max = main._standard_ceilings_mw()
        for name, values in main._presets().items():
            self.assertLessEqual(values["spl"] * 1000, spl_max, name)
            self.assertLessEqual(values["sppt"] * 1000, sppt_max, name)
            self.assertLessEqual(values["fppt"] * 1000, fppt_max, name)

    def test_every_preset_holds_spl_le_sppt_le_fppt(self):
        for name, values in main._presets().items():
            self.assertLessEqual(values["spl"], values["sppt"], name)
            self.assertLessEqual(values["sppt"], values["fppt"], name)

    def test_a_fresh_install_starts_on_the_go_1_balanced_preset(self):
        defaults = main._defaults()
        self.assertEqual((defaults["spl"], defaults["sppt"], defaults["fppt"]),
                         (15000, 17000, 22000))

    def test_the_charger_ladder_has_the_longer_go_1_tail(self):
        self.assertEqual(main._ac_settle_delays()[-1], 10.0)


class BiosBaseline(unittest.TestCase):
    """N3CN40WW is what this build targets; N3CN42WW is the one Lenovo pulled."""

    def test_the_version_number_is_parsed_out_of_the_lenovo_string(self):
        self.assertEqual(ltdp_device.bios_number("N3CN40WW"), 40)
        self.assertEqual(ltdp_device.bios_number("N3CN38WW"), 38)

    def test_an_unparseable_string_is_zero_rather_than_a_guess(self):
        self.assertEqual(ltdp_device.bios_number("garbage"), 0)
        self.assertEqual(ltdp_device.bios_number(""), 0)

    def test_the_baseline_is_recognised(self):
        self.assertEqual(ltdp_device.LEGION_GO_1.bios_status(40), "baseline")

    def test_the_withdrawn_release_is_called_out(self):
        self.assertEqual(ltdp_device.LEGION_GO_1.bios_status(42), "withdrawn")

    def test_older_and_newer_are_told_apart(self):
        self.assertEqual(ltdp_device.LEGION_GO_1.bios_status(38), "older")
        self.assertEqual(ltdp_device.LEGION_GO_1.bios_status(45), "newer")

    def test_an_unknown_version_says_so(self):
        self.assertEqual(ltdp_device.LEGION_GO_1.bios_status(0), "unknown")

    def test_a_device_with_no_baseline_never_claims_one(self):
        """Only the Legion Go 1 has been pinned to a firmware release."""
        self.assertEqual(ltdp_device.LEGION_GO_2.bios_status(40), "unknown")


class AcpiWireFormat(unittest.TestCase):
    """The encoding has to match drivers/platform/x86/lenovo/wmi-other.c exactly."""

    def test_attribute_ids_match_the_kernel_driver(self):
        self.assertEqual(ltdp_acpi.FEATURE_IDS["spl"],  0x0102FF00)
        self.assertEqual(ltdp_acpi.FEATURE_IDS["sppt"], 0x0101FF00)
        self.assertEqual(ltdp_acpi.FEATURE_IDS["fppt"], 0x0103FF00)

    def test_the_id_is_device_feature_mode_type(self):
        self.assertEqual(ltdp_acpi.attr_id(0x01, 0x02, 0xFF, 0x00), 0x0102FF00)
        self.assertEqual(ltdp_acpi.attr_id(0x04, 0x01, 0x00, 0x02), 0x04010002)

    def test_a_call_is_rendered_the_way_acpi_call_expects(self):
        rendered = ltdp_acpi._encode(
            ltdp_acpi.METHOD_OTHER,
            [0, ltdp_acpi.OM_GET_VALUE, (0x0102FF00).to_bytes(4, "little")])
        self.assertEqual(rendered, r"\_SB.GZFD.WMAE 0x00 0x11 b00ff0201")

    def test_an_integer_result_is_parsed(self):
        self.assertEqual(self._parsed("0x0000001e\x00"), 30)

    def test_a_buffer_result_is_parsed(self):
        self.assertEqual(self._parsed("{0x1e, 0x00}\x00"), b"\x1e\x00")

    def test_a_failed_call_reads_as_nothing(self):
        self.assertIsNone(self._parsed("Error: AE_NOT_FOUND\x00"))
        self.assertIsNone(self._parsed("not called\x00"))

    def _parsed(self, payload: str):
        import io

        def fake_open(path, mode="r"):
            self.assertEqual(path, ltdp_acpi.PROC_CALL)
            return io.BytesIO(payload.encode())

        real_open = ltdp_acpi.open if hasattr(ltdp_acpi, "open") else open
        ltdp_acpi.open = fake_open
        try:
            return ltdp_acpi._read()
        finally:
            ltdp_acpi.open = real_open


class AcpiApply(unittest.TestCase):
    """The write order has to keep SPL <= SPPT <= FPPT true at every step."""

    def setUp(self):
        self.state = {"spl": 15, "sppt": 17, "fppt": 22}
        self.writes = []
        self.mode = ltdp_acpi.MODE_CUSTOM

        self._real = (ltdp_acpi.available, ltdp_acpi.get_mode, ltdp_acpi.set_mode,
                      ltdp_acpi.get_feature, ltdp_acpi.set_feature)
        by_id = {v: k for k, v in ltdp_acpi.FEATURE_IDS.items()}

        ltdp_acpi.available = lambda force=False: True
        ltdp_acpi.get_mode = lambda: self.mode
        ltdp_acpi.set_mode = self._set_mode
        ltdp_acpi.get_feature = lambda fid: self.state.get(by_id.get(fid))
        ltdp_acpi.set_feature = lambda fid, value: self._set(by_id[fid], value)

    def tearDown(self):
        (ltdp_acpi.available, ltdp_acpi.get_mode, ltdp_acpi.set_mode,
         ltdp_acpi.get_feature, ltdp_acpi.set_feature) = self._real

    def _set_mode(self, mode):
        self.mode = mode
        return True

    def _set(self, key, value):
        self.writes.append((key, value))
        self.state[key] = value
        return True

    def test_raising_moves_the_ceiling_first(self):
        self.assertTrue(ltdp_acpi.apply_limits(30, 32, 41)["success"])
        self.assertEqual([k for k, _ in self.writes], ["fppt", "sppt", "spl"])

    def test_lowering_moves_the_floor_first(self):
        self.assertTrue(ltdp_acpi.apply_limits(8, 10, 14)["success"])
        self.assertEqual([k for k, _ in self.writes], ["spl", "sppt", "fppt"])

    def test_custom_mode_is_selected_before_anything_is_written(self):
        self.mode = ltdp_acpi.MODE_BALANCED
        self.assertTrue(ltdp_acpi.apply_limits(20, 22, 28)["success"])
        self.assertEqual(self.mode, ltdp_acpi.MODE_CUSTOM)

    def test_a_refused_custom_mode_is_reported_not_written_through(self):
        self.mode = ltdp_acpi.MODE_BALANCED
        ltdp_acpi.set_mode = lambda mode: False
        result = ltdp_acpi.apply_limits(20, 22, 28)
        self.assertFalse(result["success"])
        self.assertEqual(self.writes, [])

    def test_a_value_the_firmware_clamps_is_a_failure_not_a_success(self):
        """The firmware answers a too-high request with its own maximum."""
        def clamped(key, value):
            self.writes.append((key, value))
            self.state[key] = min(value, 30 if key == "spl" else value)
            return True
        by_id = {v: k for k, v in ltdp_acpi.FEATURE_IDS.items()}
        ltdp_acpi.set_feature = lambda fid, value: clamped(by_id[fid], value)
        result = ltdp_acpi.apply_limits(35, 37, 45)
        self.assertFalse(result["success"])
        self.assertIn("spl=30 want 35", result["stderr"])


class BackendSelection(unittest.TestCase):
    """Firmware first, in whichever form is present; ryzenadj last."""

    def setUp(self):
        seed(FIXTURE)
        self._caps, self._path = main._wmi_caps, main._profile_path
        self._acpi = main._acpi_available
        main._dmi = lambda field: {"product_name": "83E1"}.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()

    def tearDown(self):
        main._wmi_caps, main._profile_path = self._caps, self._path
        main._acpi_available = self._acpi
        main._ryzenadj_available = False
        main._dmi = lambda field: ""
        main._wmi_only_cache = None
        main._last_source = ""
        ltdp_device.reset_cache()

    def test_the_kernel_driver_wins_when_it_is_there(self):
        main._wmi_caps = lambda: {"spl": {"min": 5, "max": 30},
                                  "sppt": {"min": 5, "max": 32},
                                  "fppt": {"min": 5, "max": 41}}
        main._profile_path = lambda: "/sys/class/platform-profile/x/profile"
        main._acpi_available = True
        main._ryzenadj_available = True
        self.assertEqual(main._active_backend(), "wmi")

    def test_acpi_call_is_next_when_the_driver_is_absent(self):
        main._wmi_caps = lambda: {}
        main._profile_path = lambda: None
        main._acpi_available = True
        main._ryzenadj_available = True
        self.assertEqual(main._active_backend(), "acpi")

    def test_ryzenadj_is_the_last_resort(self):
        main._wmi_caps = lambda: {}
        main._profile_path = lambda: None
        main._acpi_available = False
        main._ryzenadj_available = True
        self.assertEqual(main._active_backend(), "ryzenadj")

    def test_nothing_available_reports_nothing(self):
        main._wmi_caps = lambda: {}
        main._profile_path = lambda: None
        main._acpi_available = False
        main._ryzenadj_available = False
        self.assertEqual(main._active_backend(), "")

    def test_a_kernel_driver_without_a_custom_profile_is_not_usable(self):
        """The attributes only bind while the platform profile is 'custom'."""
        main._wmi_caps = lambda: {"spl": {"min": 5, "max": 30},
                                  "sppt": {"min": 5, "max": 32},
                                  "fppt": {"min": 5, "max": 41}}
        main._profile_path = lambda: None
        main._acpi_available = True
        main._ryzenadj_available = True
        self.assertEqual(main._active_backend(), "acpi")

    def test_the_go_s_never_reaches_for_acpi_call(self):
        """Writing to /proc/acpi/call is only ever attempted where it belongs."""
        main._dmi = lambda field: {"product_family": "Legion Go S 8APU1"}.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()
        main._acpi_available = True
        self.assertFalse(main._acpi_ready())


class GlobalPowerSourceProfiles(unittest.TestCase):
    """The charger switches the global profile, not only the per-game one."""

    def setUp(self):
        seed(FIXTURE)
        self._ac = main._get_ac_online

    def tearDown(self):
        main._get_ac_online = self._ac

    def _settings(self, **extra):
        state = {"spl": 15000, "sppt": 17000, "fppt": 22000, "enabled": True}
        state.update(extra)
        return state

    def test_without_the_switch_the_charger_changes_nothing(self):
        state = self._settings()
        main._get_ac_online = lambda: True
        self.assertEqual(main._global_triplet(state), (15000, 17000, 22000))

    def test_with_the_switch_the_charger_selects_the_ac_values(self):
        state = self._settings(ac_separate=True, ac_spl=25000,
                               ac_sppt=27000, ac_fppt=33000)
        main._get_ac_online = lambda: True
        self.assertEqual(main._global_triplet(state), (25000, 27000, 33000))

    def test_on_battery_the_battery_values_are_used(self):
        state = self._settings(ac_separate=True, ac_spl=25000,
                               ac_sppt=27000, ac_fppt=33000)
        main._get_ac_online = lambda: False
        self.assertEqual(main._global_triplet(state), (15000, 17000, 22000))

    def test_a_switch_with_no_ac_values_saved_falls_back_to_the_battery_set(self):
        state = self._settings(ac_separate=True)
        main._get_ac_online = lambda: True
        self.assertEqual(main._global_triplet(state), (15000, 17000, 22000))

    def test_the_ac_triplet_is_clamped_on_load_like_every_other_target(self):
        seed({
            "schema_version": main.CURRENT_SCHEMA,
            "settings": {"spl": 15000, "sppt": 17000, "fppt": 22000, "enabled": True,
                         "ac_separate": True, "ac_spl": 99000,
                         "ac_sppt": 99000, "ac_fppt": 99000},
        })
        loaded = main._load_settings()
        self.assertLessEqual(loaded["ac_spl"], main.HARD_MAX_MW)
        self.assertLessEqual(loaded["ac_spl"], loaded["ac_sppt"])
        self.assertLessEqual(loaded["ac_sppt"], loaded["ac_fppt"])


class RenameMigration(unittest.TestCase):
    """The plugin was called LeGoTDP-LegionGo1 before it was called LTDP.

    Decky keys the settings directory on the plugin name, so without this the
    rename would have read to the user as "it deleted all my game profiles".
    """

    def setUp(self):
        import os
        import shutil
        import tempfile
        self.root = tempfile.mkdtemp(prefix="ltdp-rename-")
        self.previous = os.path.join(self.root, "LeGoTDP-LegionGo1")
        os.makedirs(self.previous)
        self._settings_dir = main.decky.DECKY_PLUGIN_SETTINGS_DIR
        self._path = main.settings.path
        main.decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(self.root, "LTDP")
        os.makedirs(main.decky.DECKY_PLUGIN_SETTINGS_DIR)
        main.settings.path = os.path.join(
            main.decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(setattr, main.decky, "DECKY_PLUGIN_SETTINGS_DIR",
                        self._settings_dir)
        self.addCleanup(setattr, main.settings, "path", self._path)
        self.addCleanup(main.settings.read)

    def _write_previous(self, blob: dict):
        import json
        import os
        with open(os.path.join(self.previous, "settings.json"), "w") as handle:
            json.dump(blob, handle)

    def test_settings_and_profiles_come_across(self):
        self._write_previous({
            "schema_version": 2,
            "settings": {"spl": 20000, "sppt": 22000, "fppt": 28000, "enabled": True},
            "game_profiles": {"292030": {"spl": 25000, "sppt": 27000, "fppt": 33000}},
        })
        main.settings.data = {}
        main.settings.commit()
        main._migrate()
        self.assertEqual(main._load_settings()["spl"], 20000)
        self.assertIn("292030", main._load_profiles())

    def test_an_existing_store_is_not_overwritten(self):
        self._write_previous({"settings": {"spl": 20000, "sppt": 22000, "fppt": 28000}})
        main.settings.data = {
            "settings": {"spl": 8000, "sppt": 10000, "fppt": 14000, "enabled": True}}
        main.settings.commit()
        main._migrate()
        self.assertEqual(main._load_settings()["spl"], 8000)

    def test_nothing_to_adopt_is_not_an_error(self):
        main.settings.data = {}
        main.settings.commit()
        main._migrate()
        self.assertEqual(main.settings.getSetting("schema_version", 0),
                         main.CURRENT_SCHEMA)

    def test_upstream_legotdp_settings_are_left_alone(self):
        """Those belong to a Go 2 / Go S device table, not to this plugin."""
        import json
        import os
        upstream = os.path.join(self.root, "LeGoTDP")
        os.makedirs(upstream)
        with open(os.path.join(upstream, "settings.json"), "w") as handle:
            json.dump({"settings": {"spl": 35000, "sppt": 37000, "fppt": 45000}}, handle)
        main.settings.data = {}
        main.settings.commit()
        main._migrate()
        self.assertIsNone(main.settings.getSetting("settings", None))


class ChargeLimit(unittest.TestCase):
    """80 % conservation, through the kernel ABI where there is one."""

    def setUp(self):
        import os
        import shutil
        import tempfile
        seed(FIXTURE)
        self.root = tempfile.mkdtemp(prefix="ltdp-charge-")
        self.node = os.path.join(self.root, "charge_control_end_threshold")
        self._glob = main.CHARGE_LIMIT_GLOB
        self._ready = main._acpi_ready
        self._read = main._acpi_charge_limit
        self._set = ltdp_acpi.set_charge_limit
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(setattr, main, "CHARGE_LIMIT_GLOB", self._glob)
        self.addCleanup(setattr, main, "_acpi_ready", self._ready)
        self.addCleanup(setattr, main, "_acpi_charge_limit", self._read)
        self.addCleanup(setattr, ltdp_acpi, "set_charge_limit", self._set)
        main.CHARGE_LIMIT_GLOB = os.path.join(self.root, "charge_control_end_threshold")
        main._acpi_ready = lambda: False

    def _write_node(self, value: int):
        with open(self.node, "w") as handle:
            handle.write(str(value))

    def _node(self) -> int:
        with open(self.node) as handle:
            return int(handle.read().strip())

    def test_a_full_threshold_reads_as_off(self):
        self._write_node(100)
        state = main._read_charge_limit()
        self.assertTrue(state["supported"])
        self.assertFalse(state["enabled"])
        self.assertEqual(state["source"], "sysfs")

    def test_a_lowered_threshold_reads_as_on(self):
        self._write_node(80)
        state = main._read_charge_limit()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["threshold"], 80)

    def test_turning_it_on_writes_eighty(self):
        self._write_node(100)
        self.assertTrue(main._apply_charge_limit(True)["success"])
        self.assertEqual(self._node(), 80)

    def test_turning_it_off_writes_a_hundred(self):
        self._write_node(80)
        self.assertTrue(main._apply_charge_limit(False)["success"])
        self.assertEqual(self._node(), 100)

    def test_the_firmware_path_is_used_when_the_kernel_offers_nothing(self):
        main.CHARGE_LIMIT_GLOB = "/nonexistent/charge_control_end_threshold"
        applied = []
        main._acpi_ready = lambda: True
        main._acpi_charge_limit = lambda: bool(applied and applied[-1])
        ltdp_acpi.set_charge_limit = lambda enabled: (applied.append(enabled), True)[1]
        self.assertTrue(main._apply_charge_limit(True)["success"])
        self.assertEqual(applied, [True])
        state = main._read_charge_limit()
        self.assertEqual(state["source"], "acpi")
        self.assertTrue(state["enabled"])

    def test_a_system_with_neither_reports_unsupported(self):
        main.CHARGE_LIMIT_GLOB = "/nonexistent/charge_control_end_threshold"
        state = main._read_charge_limit()
        self.assertFalse(state["supported"])
        self.assertFalse(state["enabled"])

    def test_a_system_with_neither_refuses_rather_than_pretending(self):
        main.CHARGE_LIMIT_GLOB = "/nonexistent/charge_control_end_threshold"
        result = main._apply_charge_limit(True)
        self.assertFalse(result["success"])
        self.assertIn("no charge limit control", result["stderr"])


class ChargeLimitThroughThePlugin(unittest.IsolatedAsyncioTestCase):
    """The RPC persists the choice; it must not touch the TDP settings."""

    def setUp(self):
        import os
        import shutil
        import tempfile
        seed(FIXTURE)
        self.root = tempfile.mkdtemp(prefix="ltdp-charge-rpc-")
        self.node = os.path.join(self.root, "charge_control_end_threshold")
        with open(self.node, "w") as handle:
            handle.write("100")
        self._glob = main.CHARGE_LIMIT_GLOB
        main.CHARGE_LIMIT_GLOB = self.node
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(setattr, main, "CHARGE_LIMIT_GLOB", self._glob)
        self.plugin = main.Plugin()
        main.Plugin._ready = True
        self.addCleanup(setattr, main.Plugin, "_ready", False)

    async def test_the_choice_is_persisted(self):
        self.assertTrue((await self.plugin.set_charge_limit(True))["success"])
        self.assertTrue((await self.plugin.get_settings())["charge_limit"])
        self.assertTrue((await self.plugin.get_charge_limit())["enabled"])

    async def test_it_leaves_the_tdp_settings_alone(self):
        before = await self.plugin.get_settings()
        await self.plugin.set_charge_limit(True)
        after = await self.plugin.get_settings()
        self.assertEqual((before["spl"], before["sppt"], before["fppt"]),
                         (after["spl"], after["sppt"], after["fppt"]))

    async def test_diagnostics_report_it(self):
        await self.plugin.set_charge_limit(True)
        diag = await self.plugin.get_diagnostics()
        self.assertTrue(diag["charge_limit"]["supported"])
        self.assertTrue(diag["charge_limit"]["enabled"])


class ReleaseTags(unittest.TestCase):
    """A release has to be tagged like 1.6.0 or it cannot be compared at all."""

    def _check(self, tag: str, assets=()):
        import io
        import json as _json
        payload = _json.dumps({"tag_name": tag, "assets": list(assets)}).encode()
        real_open = main.updater.open_url
        main.updater.open_url = lambda *a, **k: io.BytesIO(payload)
        try:
            return main.updater.check()
        finally:
            main.updater.open_url = real_open

    def test_a_version_tag_with_the_matching_asset_is_offered(self):
        result = self._check("9.9.9", [{"name": "LTDP-9.9.9.zip",
                                        "browser_download_url": "https://example/x.zip"}])
        self.assertTrue(result["update_available"])
        self.assertEqual(result["asset_name"], "LTDP-9.9.9.zip")

    def test_a_tag_that_is_not_a_version_is_refused_not_guessed(self):
        """Upstream read any such tag as 'newer' and then failed on the asset."""
        result = self._check("LDTP")
        self.assertFalse(result["update_available"])
        self.assertIn("not a version number", result["error"])

    def test_an_older_release_is_not_an_update(self):
        self.assertFalse(self._check("0.1.0")["update_available"])


class ConflictDetection(unittest.TestCase):
    """Another tool on the same three limits is the usual cause of 'it will not stay'."""

    def setUp(self):
        main._conflict_cache_ts = 0.0
        self._names = main._running_process_names

    def tearDown(self):
        main._running_process_names = self._names
        main._conflict_cache_ts = 0.0

    def test_a_running_handheld_daemon_is_reported(self):
        main._running_process_names = lambda: {"hhd", "steam"}
        found = main._detect_conflicts()
        self.assertTrue(any("Handheld Daemon" in c["params"]["name"] for c in found))

    def test_a_conflict_is_a_key_not_a_sentence(self):
        """The panel speaks three languages; the backend speaks none of them."""
        main._running_process_names = lambda: {"hhd"}
        found = main._detect_conflicts()
        self.assertEqual(found[0]["key"], "conflict.process")
        self.assertIn("name", found[0]["params"])

    def test_a_quiet_system_reports_nothing(self):
        main._running_process_names = lambda: {"steam", "gamescope"}
        main._conflict_cache_ts = 0.0
        self.assertEqual(
            [c for c in main._detect_conflicts() if c["key"] == "conflict.process"], [])

    def test_the_answer_is_cached_rather_than_rescanning_proc(self):
        calls = []

        def counted():
            calls.append(1)
            return {"hhd"}

        main._running_process_names = counted
        main._detect_conflicts()
        main._detect_conflicts()
        self.assertEqual(len(calls), 1)


class GlobalAcThroughThePlugin(unittest.IsolatedAsyncioTestCase):
    """The RPCs the panel actually calls, with the hardware layer replaced."""

    def setUp(self):
        seed({
            "schema_version": main.CURRENT_SCHEMA,
            "settings": {"spl": 15000, "sppt": 17000, "fppt": 22000,
                         "enabled": True, "active_preset": "balanced"},
        })
        self.applied = []
        self._apply, self._ac, self._appid = (
            main._apply_limits, main._get_ac_online, main._get_running_appid)
        main._apply_limits = self._fake_apply
        main._get_running_appid = lambda: ""
        main._get_ac_online = lambda: False
        main._dmi = lambda field: {"product_name": "83E1"}.get(field, "")
        main._wmi_only_cache = None
        ltdp_device.reset_cache()
        self.plugin = main.Plugin()
        main.Plugin._ready = True

    def tearDown(self):
        (main._apply_limits, main._get_ac_online,
         main._get_running_appid) = self._apply, self._ac, self._appid
        main._dmi = lambda field: ""
        main._wmi_only_cache = None
        main.Plugin._ready = False
        ltdp_device.reset_cache()

    def _fake_apply(self, spl, sppt, fppt):
        self.applied.append((spl, sppt, fppt))
        return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    async def test_the_ac_slot_is_saved_without_disturbing_the_battery_one(self):
        await self.plugin.set_global_ac_separate(True)
        self.applied.clear()
        await self.plugin.apply_tdp(25000, 27000, 33000, "", "performance", None, "ac")
        state = main._load_settings()
        self.assertEqual((state["ac_spl"], state["ac_sppt"], state["ac_fppt"]),
                         (25000, 27000, 33000))
        self.assertEqual((state["spl"], state["sppt"], state["fppt"]),
                         (15000, 17000, 22000))
        # On battery, editing the charger profile must not change what runs.
        self.assertEqual(self.applied, [(15000, 17000, 22000)])

    async def test_editing_the_ac_slot_on_ac_applies_it_immediately(self):
        main._get_ac_online = lambda: True
        await self.plugin.set_global_ac_separate(True)
        self.applied.clear()
        await self.plugin.apply_tdp(25000, 27000, 33000, "", "performance", None, "ac")
        self.assertEqual(self.applied[-1], (25000, 27000, 33000))

    async def test_switching_the_charger_profile_on_seeds_it_from_the_battery_one(self):
        await self.plugin.set_global_ac_separate(True)
        state = main._load_settings()
        self.assertTrue(state["ac_separate"])
        self.assertEqual((state["ac_spl"], state["ac_sppt"], state["ac_fppt"]),
                         (15000, 17000, 22000))

    async def test_switching_it_off_puts_the_battery_profile_back_on_ac(self):
        await self.plugin.set_global_ac_separate(True)
        await self.plugin.apply_tdp(25000, 27000, 33000, "", "performance", None, "ac")
        main._get_ac_online = lambda: True
        self.applied.clear()
        await self.plugin.set_global_ac_separate(False)
        self.assertEqual(self.applied[-1], (15000, 17000, 22000))
        self.assertFalse(main._load_settings()["ac_separate"])

    async def test_a_running_game_profile_is_not_disturbed_by_the_global_switch(self):
        main._get_running_appid = lambda: "292030"
        main._save_profiles({"292030": {"spl": 30000, "sppt": 32000, "fppt": 41000}})
        self.applied.clear()
        await self.plugin.set_global_ac_separate(True)
        self.assertEqual(self.applied, [])

    async def test_the_caps_report_names_the_device_and_the_range(self):
        caps = await self.plugin.get_caps()
        self.assertEqual(caps["device"]["key"], "legion_go_1")
        self.assertEqual(caps["presets"]["max"], {"spl": 30, "sppt": 32, "fppt": 41})
        self.assertLessEqual(caps["std"]["spl"], 30)

    async def test_diagnostics_answer_with_the_device_and_its_ranges(self):
        diag = await self.plugin.get_diagnostics()
        self.assertEqual(diag["device_key"], "legion_go_1")
        self.assertEqual(diag["bios"]["baseline"], 40)
        self.assertIn(diag["bios"]["status"],
                      ("baseline", "older", "newer", "withdrawn", "unknown"))
        self.assertIn("spl", diag["ranges"])
        self.assertIn(diag["ranges"]["spl"]["source"], ("firmware", "device profile"))
        self.assertIn("wmi", diag["backends"])

    async def test_the_language_is_remembered(self):
        self.assertTrue((await self.plugin.set_language("ru"))["success"])
        self.assertEqual((await self.plugin.get_settings())["language"], "ru")
        self.assertTrue((await self.plugin.set_language("en"))["success"])
        self.assertEqual((await self.plugin.get_settings())["language"], "en")

    async def test_spanish_is_offered_too(self):
        self.assertTrue((await self.plugin.set_language("es"))["success"])
        self.assertEqual((await self.plugin.get_settings())["language"], "es")

    async def test_an_unknown_language_is_refused_rather_than_stored(self):
        result = await self.plugin.set_language("kl")
        self.assertFalse(result["success"])
        self.assertNotIn("language", await self.plugin.get_settings())

    async def test_setting_the_language_leaves_the_limits_alone(self):
        self.applied.clear()
        await self.plugin.set_language("ru")
        self.assertEqual(self.applied, [])
        state = await self.plugin.get_settings()
        self.assertEqual((state["spl"], state["sppt"], state["fppt"]),
                         (15000, 17000, 22000))

    async def test_update_checks_point_at_this_fork(self):
        """Not upstream's releases: those carry a different device table."""
        self.assertIn("iLordel/LEGOTDP", main.GITHUB_RELEASES_URL)
        self.assertTrue(main.UPDATE_CHECKS_ENABLED)

    async def test_the_check_is_reported_as_the_updater_answers_it(self):
        """No network here - the transport is the updater's own concern."""
        real = main.updater.check
        main.updater.check = lambda: {"current_version": "1.6.0",
                                      "latest_version": "1.7.0",
                                      "update_available": True}
        try:
            info = await self.plugin.check_for_updates()
        finally:
            main.updater.check = real
        self.assertTrue(info["update_available"])
        self.assertEqual(info["latest_version"], "1.7.0")


if __name__ == "__main__":
    unittest.main()
