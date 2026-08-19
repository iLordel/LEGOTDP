# Changelog

All notable changes to LTDP, newest first. The upstream LeGoTDP history this
fork is built on is kept at the bottom of the file.

## [1.7.0] - 2026-08-19

### Added

- **Tabs, paged with the shoulder buttons.** R1 and R2 move forward, L1 and L2
  back, and the strip at the top stays clickable: Steam is free to consume a
  bumper before it reaches the panel, and a tab reachable only by a button the
  system swallowed would be a tab nobody can open.
- **An Enhancers tab** listing the tools on this machine that change how a game
  looks or how many frames it produces: MAKO and its renderer, Lossless
  Scaling, MangoHud, vkBasalt. Each shows installed or not, and where it was
  found.

  It reports; it does not drive. MAKO is a separate Decky plugin with its own
  backend and a Vulkan layer of its own, under GPL-3.0 against this project's
  BSD-3-Clause, and it needs a licensed copy of Lossless Scaling. A Decky plugin
  cannot render or control another one, and copying its code here would relicense
  everything. What is useful next to a TDP limit is knowing whether frame
  generation is present at all - generated frames are what let the limit come down.
- All of it in English, Russian and Spanish, like the rest of the panel.

## [1.6.1] - 2026-08-19

### Fixed

- **acpi_call is looked for again, not only at startup.** It is a DKMS module,
  and on SteamOS installing it is something the user does by hand long after
  boot - so a single probe at startup meant the fan section stayed unavailable
  until the plugin was reloaded, with the message giving no hint that anything
  had changed. Opening the panel now re-probes when the interface is missing,
  rate-limited to once a minute. The paths that run constantly - applying
  limits, the enforce pass - still read the cached answer: probing means a
  modprobe and a write to /proc/acpi/call, which is not something to do every
  five seconds on a machine that will never have the module.
- The "never probed" sentinel is `None`, not `0.0`. `time.monotonic()` counts
  from boot, so on a freshly started machine zero is a timestamp seconds in the
  past rather than never, and the first re-probe never happened - the same trap
  `_wmi_verified_at` already carried a comment about. A CI runner caught it.

## [1.6.0] - 2026-08-19

### Added

- **Update checks are on**, pointed at this project's own releases
  (`iLordel/LEGOTDP`). The Updates section is back in the panel, in all three
  languages: it reports the installed and the latest version, downloads the
  release archive, and then stops. Installing stays a deliberate act in Decky -
  this plugin runs as root, and replacing its own code over the network without
  the user pressing anything is not a power it should hold.

### Fixed

- `bios_number("")` read the machine's own DMI instead of answering zero. An
  explicit empty string means there is nothing to parse; only `None` means "go
  and look". Harmless on a Legion Go, wrong anywhere else - a CI runner with a
  BIOS of its own answered 41 to a question about an empty string.
- **A release tagged with something that is not a version is refused rather
  than guessed at.** Upstream compared such a tag as a string, which reads
  anything unequal as "newer": a release tagged `LDTP` was announced as an
  available update whose asset could never exist, and the download failed with
  a missing-asset error. It now says the tag is not a version number and offers
  nothing.

## [1.5.0] - 2026-08-19

### Added

- **SoC temperature and fan speeds** in the panel, from hwmon - so they work
  whichever backend is driving the limits. The temperature earns its place on
  this machine: the BIOS trims TDP by itself when the SoC gets hot, and without
  it a limit that is not being reached looks the same as a limit somebody else
  moved.
- **Fan modes** - Auto, Quiet, Balanced, Cool and Max. The curves are ten points
  at 10 °C intervals, clamped at or above the firmware's own minimum. Auto hands
  the curve back by bouncing the power mode, which is what resets it. Max is the
  firmware's full-speed flag. The enforce pass rewrites the curve when a power
  mode change wipes it, and stands down after three refusals rather than
  fighting the firmware. Fans are handed back on uninstall.

### Fixed

- **Text produced by the backend is now translated.** The backend detail lines
  in Diagnostics and the conflict warning were built as English sentences in
  Python and rendered as-is, so they stayed English whatever language the panel
  was set to. They travel as `{key, params}` now and are worded in the string
  table like everything else - in all three languages.

## [1.4.0] - 2026-08-19

### Added

- **The BIOS this build targets is now recorded and checked: N3CN40WW**
  (January 2026), the release Lenovo currently offers. Diagnostics and the
  script both say how the installed firmware relates to it, and flag
  **N3CN42WW** - withdrawn by Lenovo in August 2026 after handhelds failed to
  boot, with no vendor path back down. Reported, never acted on: the plugin
  does not change what it does based on the BIOS version.

## [1.3.0] - 2026-08-19

### Added

- **Charge limit.** One switch that holds the battery at 80 %, which is the
  threshold the firmware itself uses - a percentage slider would only be a lie
  told with more precision. The kernel's own
  `charge_control_end_threshold` is preferred wherever a driver publishes it,
  because other tools understand it and it outlives this plugin; the GZFD
  feature is the fallback where no driver does. It is deliberately independent
  of the Enable switch, and removed on uninstall so nothing is left holding the
  battery back invisibly.
- **Spanish**, alongside English and Russian.

### Changed

- The language selector is a dropdown rather than a row of buttons - three
  entries no longer fit side by side, and a list scales.

## [1.2.0] - 2026-08-19

### Verified

- Run on a Legion Go 1 (83E1, Ryzen Z1 Extreme): limits apply and hold, per-game
  profiles switch, and neither a charger transition nor suspend/resume knocks
  them off.

### Changed

- **Renamed to LTDP.** The plugin, its directory, its zip, its log prefix and
  its Python modules all carry the short name now; upstream LeGoTDP keeps its
  own name everywhere it is credited.
- Decky keys the settings directory on the plugin name, so the rename would
  have looked like every per-game profile had been wiped. Schema 3 adopts the
  store this plugin wrote as `LeGoTDP-LegionGo1` on first run - and only that
  one, never upstream's, whose numbers belong to a different device table.
- An install left behind under the old name is reported as a conflict, because
  that is exactly what it is: a second copy driving the same three limits.

## [1.1.0] - 2026-08-19

### Added

- **Interface language**, English or Russian, chosen in the panel and remembered
  in the settings store. The first run adopts the Steam client's own language;
  after that the choice is the user's. The Russian table is checked against the
  English one at build time, so a missing string is a compile error rather than
  a blank label on the device.
- A **status card** at the top of the panel: the limit and the actual package
  draw side by side, with a bar between them, plus the device and the backend
  that is driving it. A limit and a measurement are different numbers and now
  look it.
- **by LORDEL** in the footer.

### Changed

- Presets are a two-column grid of chips instead of six stacked full-width
  buttons, each showing the watts it stands for. Battery / AC and the language
  are segmented controls in the same style. All of them are `Focusable` with
  horizontal flow, so the gamepad reaches every one.
- The panel title carries the device it was built for.

## [1.0.0] - 2026-08-18

Fork of upstream 1.6.1, adapted to the original Lenovo Legion Go (83E1,
Ryzen Z1 Extreme).

### Added

- A device table with one profile per machine: Legion Go 1, Legion Go 2,
  Legion Go S (both variants) and a generic fallback. Each carries its own
  firmware range, preset ladder, backend order, Extras ceiling and charger
  re-settle ladder, so no machine is handed another machine's numbers.
- A third backend: the Lenovo GameZone firmware interface through `acpi_call`,
  for the kernels that do not carry `lenovo-wmi-other` yet - which includes the
  kernel SteamOS 3.7 ships. Attribute ids, the custom-mode requirement and the
  read-back verification all follow the mainline driver.
- Backend probing at startup, with the result in the log and in the panel:
  which interfaces exist, which one is active, and why the others are not.
- A Diagnostics section in the panel and `scripts/ltdp-diagnostics.sh` on
  disk: DMI, BIOS, kernel, Lenovo modules, firmware attributes with their
  min/max, platform profile, the acpi_call probe, ryzenadj, RAPL draw,
  conflicts, and the backend conclusion. `--write-test` proves writes land and
  asks the firmware for its real ceiling.
- A global separate charger profile, alongside the existing per-game one. The
  charger now selects between two sets of global values as well.
- Detection of other TDP controllers (hhd, adjustor, PowerStation,
  SimpleDeckyTDP, PowerControl, upstream LeGoTDP), reported in the panel and
  the log rather than silently fought.

### Changed

- Preset ladder for the Legion Go 1: 5/7/10, 8/10/14, 15/17/22, 20/22/28 and
  30/32/41 W, spaced against Lenovo's own quiet / balanced / performance modes
  instead of the Go 2 ladder.
- The Extras ceiling on this machine is 40 W, not 50 W.
- Firmware writes are ordered so `SPL <= SPPT <= FPPT` holds at every
  intermediate step, not only at the end.
- An unreadable firmware now falls back to the device profile's documented
  range rather than to the Extras ceiling.
- The powercap package counter is found by name across every provider, not only
  under `intel-rapl:*`.
- The firmware-attributes directory is globbed rather than pinned to instance 0.
- If the verified ryzenadj download fails, a copy already installed on the
  system is used instead - on a Legion Go 1 without either firmware path it is
  the only way to set anything at all. The fallback is logged and reported as
  unverified.
- Update checks are disabled: the upstream releases this would find carry a
  different device table.


---

# Upstream LeGoTDP changelog

Everything below belongs to [LeGoTDP](https://github.com/Rayekkk/LeGoTDP), the
Legion Go 2 / Legion Go S plugin this fork started from. Version numbers there
are its own and unrelated to LTDP's.

### [1.6.1] - 2026-08-09

#### Fixed

- TDP changes are serialised as complete hardware-and-settings transactions. Simultaneous UI actions, game changes, charger events and enforcement passes can no longer interleave, lose an unrelated setting or persist a target different from the one that reached the hardware.
- Turning the plugin off restores firmware defaults before the disabled state is saved, and applying TDP while it is disabled is rejected. The UI now treats backend refusals as errors instead of showing a successful toggle or profile change.
- A delayed charger re-settle pass cannot put back an obsolete target after a newer manual change, game switch or power-source transition.
- The drift retry budget resets after the requested target is confirmed. Separate later drifts each get their own recovery attempts instead of the fourth event being silently accepted.
- Per-game profile requests carry the foreground app they were created for. A slow response for game A can no longer overwrite game B after the foreground game changes.
- Extras is only offered when a verified RyzenAdj binary is actually available. Locking it again clamps the global target, active target and every battery and AC game profile to the firmware ceilings in one transaction.
- Update checks require the exact `LeGoTDP-<version>.zip` release asset. Source archives and ZIPs belonging to another project are no longer selected, and a release missing the plugin archive shows an error instead of a download button that cannot work.

#### Security

- The pinned RyzenAdj archive and extracted executable are both verified with SHA-256 before the executable can run as root. An old binary that fails verification is removed, and a failed replacement leaves the extended path unavailable.
- Update downloads no longer accept a URL or filename from the frontend. The configured XDG download directory must resolve inside the desktop user's home, redirects are checked against the host allowlist, and the final ZIP atomically replaces any older archive without following a destination symlink.

#### Internal

- Added regression coverage for concurrent mutations, stale game and charger work, drift recovery, runtime Extras availability, updater path and asset validation, atomic downloads and both RyzenAdj integrity checks.
- Updated vulnerable transitive development dependencies; `npm audit` reports no known vulnerabilities.

### [1.6.0] - 2026-07-28

#### Added

- Support for the Lenovo Legion Go S with the Ryzen Z1 Extreme, which is the variant this was measured and tested on. It drives the same Lenovo firmware interface as the Go 2, so everything except the extended range works there unchanged.
- Other Legion Go S variants, including the Ryzen Z2 Go, take the same firmware-only path but are untested. Nothing there is assumed: the limits come from what that machine's own firmware reports, so a variant with different ceilings gets its own rather than the Z1 Extreme's.

#### Fixed

- TDP is restored after the charger is plugged in. The firmware applies a profile of its own on that transition and it lands after the plugin's, so a single write at the moment the state changed was overwritten a fraction of a second later - measured on a Legion Go S as 40/43/53 W asked for and 10/15/20 W in place. The limits are now re-asserted over the following seconds until they stop being overwritten, and each pass is skipped once the hardware already agrees.

#### Changed

- The Current TDP panel is always shown, including while the plugin is switched off. With it off that reading is the only way to see what the firmware settled on, which is exactly when it is worth having.
- Presets are spaced against the ceilings of the machine they run on and served by the backend, so there is one place that knows them. A Legion Go S gets 5/8/10, 8/10/15, 18/20/25, 33/33/35 and 40/43/53 W - its Max asks for everything the firmware reports. The Legion Go 2 ladder is unchanged.
- Slider ceilings are taken per parameter from what the firmware reports it accepts, instead of one shared limit. A Legion Go S answers 40 / 43 / 53 W for SPL / SPPT / FPPT, and the sliders now stop at each of those rather than at the highest.
- Profiles carried over from another machine are clamped to what the hardware in front of you actually takes, so a 50 W profile no longer arrives as a request the firmware will refuse.
- The Extras section is hidden on hardware driven through the firmware alone, and `ryzenadj` is not downloaded there. The plugin fetches that binary itself when the extended range needs it, and on those machines it is not wanted - the firmware range is the whole range.
- A firmware apply that falls outside the accepted range now says so, instead of failing over to a tool that was never installed.

#### Internal

- Hardware is recognised by DMI product family rather than model number, so other SKUs in the same family are covered. Anything unrecognised keeps the behaviour it had, which is what leaves the Legion Go 2 path untouched.
- Backend tests up to 104 from 93.

### [1.5.0] - 2026-07-25

#### Added

- Settings and per-game profiles now live in Decky's own settings directory, so reinstalling the plugin keeps them.
- The limits are cross-checked against a second, independent reading twice a minute. The firmware only reports back what the plugin last wrote to it, so anything that moved the limits behind its back went unnoticed and uncorrected.
- The installed version is shown in the panel before you check for updates.
- Uninstalling hands the platform profile back to the firmware, instead of leaving it pinned to the last TDP the plugin set. See Known issues.

#### Changed

- TDP is re-applied the moment the console wakes, rather than within the following five seconds.
- Game detection reacts to Steam's own launch and exit events instead of polling, and keeps working while the plugin menu is closed.
- Current TDP readings are pushed from the backend as they are taken, instead of being fetched twice a second by the panel.
- Failures raise a notification, rather than only a line in a panel you may not be looking at.
- Colours follow the Steam theme instead of being hardcoded.

#### Fixed

- The SPL row in Current TDP showed the FPPT value whenever the Extras range was in use. The chip reports its sustained limit as a copy of the fast limit, and the plugin was taking that at face value.
- Every change in the Extras range cost three redundant re-applies before the plugin stopped chasing a number the hardware was never going to return.
- Moving a slider was briefly reported as unexpected drift and corrected a second time, because the panel's cached reading predated the change.
- Monitoring could keep running after the Steam interface went away, reading power counters every two seconds for the rest of the session.

#### Known issues

- **Upgrading from 1.4.0 or earlier loses your saved values.** Decky deletes the old plugin folder before the new version ever starts, and that folder is where they used to live. Write them down first, or see the README for how to hand the old file back. Every update after this one keeps them automatically.
- Decky does not reliably give a plugin the chance to run its uninstall step, so the platform profile is not guaranteed to be handed back. **Turn the plugin off before uninstalling** and it always is.

#### Internal

- Update and download code is shared with LeGo Vibe Control, so a fix to certificate handling, the download allowlist or the release check lands in both plugins at once.
- Settings migration moved to Decky's `_migration()` lifecycle hook, so it finishes before anything can read the store.
- Backend test suite, run in CI on every push.

### [1.4.0] - 2026-07-24

#### Added

- Firmware-first TDP control. Limits are applied through the Lenovo firmware (WMI) interface, which is more stable and survives sleep; `ryzenadj` is used only as a fallback for the extended range.
- SPPT and FPPT are set as offsets above SPL. SPL is the main TDP dial, and the other two are headroom above it (up to +10 W and +15 W); the sliders clamp against each other live, so no combination can exceed the limit.
- Live package power draw, read from RAPL and shown in the Current TDP panel next to each limit.

#### Changed

- Maximum TDP lowered from 60 W to 50 W. 60 W was never actually reachable on this hardware; profiles saved above 50 W are migrated down automatically.

#### Fixed

- Charging state no longer flickers. Power detection now counts only the mains adapter and ignores the USB-C port's PD role, which had made the state jump back to "charging" right after unplugging.
- Per-game battery and AC profiles switch reliably. The running game is detected even inside Proton and gamescope, so unplugging the charger applies the game's battery profile instead of falling back to the global one.
- TDP survives suspend and resume; the limits are re-applied after the console wakes.
- No more constant re-applying and log spam on extended-range (Extras) targets.
- Failed TDP changes no longer appear as a green "success" message.
- The downloaded update file is owned by you instead of by root.

### [1.3.2] - 2026-05-21

#### Fixed

- Update downloads respect the system language. The ZIP is saved to your actual XDG download directory - `Scaricati`, `Téléchargements` and so on - instead of a hardcoded `Downloads` folder.

### [1.3.1] - 2026-05-21

#### Fixed

- The plugin failed to load after a fresh install. `package.json` is now included in the release ZIP; without it Decky Loader fell back to legacy script loading, which is incompatible with the ES module bundle, and showed a syntax error instead of the UI.

### [1.3.0] - 2026-05-20

#### Added

- Separate AC profile. Set independent TDP limits for battery and AC; the plugin switches automatically when the charger is plugged or unplugged. Works for both global settings and per-game profiles.
- Extended TDP range. A new Extras section with an unlock toggle raises the Custom slider limits to 60 W for SPL, SPPT and FPPT, for advanced users.
- The preset name is shown as a label below the preset buttons, so you always know which preset is active.

#### Fixed

- The settings file is written atomically - to a temporary file, then replaced - to prevent corruption on an unexpected shutdown.
- The ryzenadj lock now correctly serialises all hardware calls across the enforce and info loops.

### [1.2.0] - 2026-05-18

#### Added

- In-plugin update system. Check for updates and download the new version directly from the plugin menu.
- The downloaded ZIP is saved to `~/Downloads`, with install instructions shown in the UI.

### [1.1.0] - 2026-05-18

#### Added

- Minimum preset (5/5/10 W).

#### Changed

- The Live TDP panel only polls ryzenadj while the panel is visible.

#### Fixed

- The device froze when opening or closing the Live TDP panel. ryzenadj calls are now handled entirely in the backend, decoupled from frontend IPC.

### [1.0.0] - 2026-05-17

Initial release. Requires a Lenovo Legion Go 2 (Ryzen Z2 Extreme) with DeckyLoader installed.

#### Added

- SPL, SPPT and FPPT power limits, set via preset buttons or custom sliders.
- Presets: Silent (8/10/15 W), Balanced (15/18/25 W), Performance (25/28/35 W), Max (35/37/45 W).
- Per-game profiles, saved per Steam App ID and applied automatically in the background when a game launches, with no need to open the plugin menu.
- Global settings restored automatically when a game exits.
- Live TDP panel showing the current limits and real-time power draw via ryzenadj.
- Drift enforcement, re-applying your settings every 5 seconds if the system overrides them.
- Enable/disable toggle, restoring firmware defaults when turned off.
- The ryzenadj binary is downloaded automatically on first run.
