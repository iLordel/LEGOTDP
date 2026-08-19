# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk
# Legion Go 1 port
# https://github.com/Rayekkk/LeGoTDP

"""Detection of the other tools that change how a game looks or runs.

Read-only by design: LTDP reports these, it does not drive them. MAKO in
particular is a separate Decky plugin with its own backend and a Vulkan layer,
under a different licence - one plugin cannot render or control another.
"""
import os
import shutil
import tempfile
import unittest

from _harness import main


class EnhancerDetection(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ltdp-enhancers-")
        self.home = os.path.join(self.root, "home")
        self.plugins = os.path.join(self.root, "plugins")
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        os.makedirs(os.path.join(self.plugins, "LTDP"))
        self._home = main._user_home
        self._dir = main.PLUGIN_DIR
        main._user_home = lambda: self.home
        main.PLUGIN_DIR = os.path.join(self.plugins, "LTDP")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(setattr, main, "_user_home", self._home)
        self.addCleanup(setattr, main, "PLUGIN_DIR", self._dir)

    def _entry(self, key):
        return next(e for e in main._detect_enhancers() if e["key"] == key)

    def _touch(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("")

    def test_nothing_installed_is_reported_as_nothing(self):
        for entry in main._detect_enhancers():
            self.assertFalse(entry["installed"], entry["key"])
            self.assertEqual(entry["path"], "", entry["key"])

    def test_the_mako_plugin_is_found_whatever_decky_called_its_folder(self):
        """Its plugin.json calls it "MAKO - Frame Generation"; the directory
        name follows whatever the zip carried, so the match is on the word."""
        os.makedirs(os.path.join(self.plugins, "MAKO - Frame Generation"))
        entry = self._entry("mako")
        self.assertTrue(entry["installed"])
        self.assertIn("MAKO", entry["path"])

    def test_the_renderer_is_found_in_the_user_home_not_roots(self):
        """The plugin runs as root; expanduser("~") would be the wrong home."""
        self._touch(os.path.join(self.home, ".local/bin/mako-run"))
        self.assertTrue(self._entry("mako_renderer")["installed"])

    def test_lossless_scaling_is_looked_for_where_steam_puts_it(self):
        self._touch(os.path.join(
            self.home, ".steam/steam/steamapps/common/Lossless Scaling/Lossless.dll"))
        self.assertTrue(self._entry("lossless")["installed"])

    def test_a_second_steam_library_is_looked_at_too(self):
        self._touch(os.path.join(
            self.home,
            ".local/share/Steam/steamapps/common/Lossless Scaling/Lossless.dll"))
        self.assertTrue(self._entry("lossless")["installed"])

    def test_every_entry_names_a_string_key_rather_than_a_sentence(self):
        """The panel speaks three languages; the backend speaks none of them."""
        for entry in main._detect_enhancers():
            self.assertTrue(entry["note"].startswith("enhancer."), entry["key"])

    def test_mako_carries_a_link_because_it_cannot_be_installed_from_here(self):
        entry = self._entry("mako")
        self.assertIn("github.com/eugeniosegala/MAKO", entry["url"])

    def test_our_own_plugin_directory_is_not_mistaken_for_one_of_them(self):
        keys = {e["key"] for e in main._detect_enhancers() if e["installed"]}
        self.assertEqual(keys, set())


class MakoRelease(unittest.TestCase):
    """Only the release metadata is read here; Decky downloads the archive."""

    def _releases(self, payload):
        import io
        import json
        real = main.updater.open_url
        main.updater.open_url = lambda *a, **k: io.BytesIO(json.dumps(payload).encode())
        try:
            return main._mako_release()
        finally:
            main.updater.open_url = real

    def test_the_plugin_asset_is_what_identifies_a_plugin_release(self):
        result = self._releases([
            {"tag_name": "render-v3.1.0",
             "assets": [{"name": "mako-render-v3.1.0-linux.tar.xz",
                         "browser_download_url": "https://example/engine", "size": 1}]},
            {"tag_name": "plugin-v2.0.0",
             "assets": [{"name": "MAKO-Decky-v2.0.0.zip",
                         "browser_download_url": "https://example/plugin", "size": 23}]},
        ])
        self.assertTrue(result["available"])
        self.assertEqual(result["asset"], "MAKO-Decky-v2.0.0.zip")
        self.assertEqual(result["url"], "https://example/plugin")

    def test_the_tag_prefix_is_stripped_from_the_version(self):
        result = self._releases([{"tag_name": "plugin-v2.0.0", "assets": [
            {"name": "MAKO-Decky-v2.0.0.zip", "browser_download_url": "u", "size": 1}]}])
        self.assertEqual(result["version"], "v2.0.0")

    def test_drafts_and_prereleases_are_skipped(self):
        result = self._releases([
            {"tag_name": "plugin-v9.9.9", "draft": True, "assets": [
                {"name": "MAKO-Decky-v9.9.9.zip", "browser_download_url": "d", "size": 1}]},
            {"tag_name": "plugin-v2.0.0", "assets": [
                {"name": "MAKO-Decky-v2.0.0.zip", "browser_download_url": "r", "size": 1}]},
        ])
        self.assertEqual(result["url"], "r")

    def test_engine_only_releases_are_not_offered_as_a_plugin(self):
        result = self._releases([{"tag_name": "render-v3.1.0", "assets": [
            {"name": "mako-render-v3.1.0-linux.tar.xz", "browser_download_url": "e",
             "size": 1}]}])
        self.assertFalse(result["available"])
        self.assertIn("no MAKO Decky release", result["error"])

    def test_a_network_failure_is_reported_not_raised(self):
        real = main.updater.open_url

        def explode(*a, **k):
            raise OSError("no route to host")

        main.updater.open_url = explode
        try:
            result = main._mako_release()
        finally:
            main.updater.open_url = real
        self.assertFalse(result["available"])
        self.assertIn("no route to host", result["error"])


if __name__ == "__main__":
    unittest.main()
