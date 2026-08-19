# Tests

Plain `unittest`, no dependencies to install.

```bash
python -m unittest discover -s tests -v
```

`test_logic.py` and `test_legiongo1.py` need nothing but Python and run in CI.
`test_legiongo1.py` is the Legion Go 1 half: the device table, the per-machine
ranges and preset ladder, the acpi_call wire format, backend selection and the
global charger profile - all with DMI and both transports stubbed, so it proves
the same things on a build machine as on the device.

`test_device.py` needs a real Legion Go. Its WMI classes want the in-kernel
Lenovo firmware attributes; its acpi_call class wants `/proc/acpi/call` and a
firmware that answers GameZone. Each **skips itself** when its interface is
absent, so the command above is correct everywhere. The device tests apply real
TDP limits and put the previous ones back afterwards - the fans reacting is
expected, not a failure.

Both files import the backend through `_harness.py`, which stubs the `decky`
and `settings` modules that only exist inside DeckyLoader, and points the
settings manager at a throwaway directory. Your real settings are never read
or written.

## Running against the device

Copy the repo across and run it there:

```bash
scp -r main.py ltdp_device.py ltdp_acpi.py ltdp_updater.py plugin.json tests     deck@<legion>:/tmp/ltdp-tests/
ssh deck@<legion> 'cd /tmp/ltdp-tests && sudo python3 -m unittest discover -s tests -v'
```

Or, since the suite ships inside the plugin:

```bash
cd /home/deck/homebrew/plugins/LTDP
sudo LTDP_PLUGIN_DIR=$PWD python3 -m unittest discover -s tests -t tests -v
```

`sudo` is required: the firmware attributes under `/sys/class/firmware-attributes/`,
the platform profile node and `/proc/acpi/call` are all root-only, exactly as
they are for the plugin itself.

**Stop the plugin first.** `test_device.py` sets real limits and reads them back,
and a running plugin defends its own target every five seconds - the two fight
and the results are random:

```bash
sudo systemctl stop plugin_loader
# ... run the tests ...
sudo systemctl start plugin_loader
```

`test_logic.py` needs none of this; it touches no hardware and passes with or
without `/sys` present.

To exercise the copy DeckyLoader actually loaded rather than a fresh checkout,
point the harness at it:

```bash
LTDP_PLUGIN_DIR=/home/deck/homebrew/plugins/LeGoTDP \
  sudo -E python3 -m unittest discover -s tests -v
```

## What these cannot cover

- Anything in `src/index.tsx`. There is no frontend test setup; the UI is
  verified by hand on the device.
- The ryzenadj fallback path. It only engages for the Extras range, and
  exercising it means letting the plugin download and run the binary:
  `sudo ~/homebrew/plugins/LeGoTDP/bin/ryzenadj --info`.
- Drift enforcement. `_enforce_target` is driven by the hardware wandering off
  a target on its own, which cannot be staged; watch
  `journalctl -u plugin_loader | grep legotdp` under load instead.
- Suspend and resume. `reapply()` is covered, but the thing that calls it is
  Steam's `RegisterForOnResumeFromSuspend` in the frontend - Decky has no
  backend resume hook - so actually sleeping the console is a manual check.
- `_uninstall()`. Removing the plugin is the only way to fire it; the check is
  that the platform profile is back on `balanced` afterwards.
- The update download, which needs a newer release to exist on GitHub.
- The settings migration against a real pre-1.5.0 install. `Migration` in
  `test_logic.py` covers the logic with temporary files; the real check is
  installing 1.5.0 over an older copy and confirming the per-game profiles are
  still there.
