#!/usr/bin/env node
/**
 * Builds the release zip that Decky's "Install Plugin from ZIP" accepts.
 *
 * Files are staged into build/<PLUGIN_NAME>/ first, so the archive always has
 * the right root folder regardless of what the checkout directory is called,
 * and only runtime files ever make it in.
 *
 * bin/ryzenadj is deliberately excluded so a fresh install downloads it on
 * first run (and so we never ship an unverified binary in the archive).
 *
 * Zipping is delegated to 7-Zip on Windows and `zip` elsewhere. PowerShell's
 * Compress-Archive is deliberately not used: it stores backslash separators
 * and the resulting archive fails to extract on Linux.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, cpSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(repoRoot, "plugin.json"), "utf8"));

// Decky installs the folder as-is, and it is also what tells this build apart
// from an upstream LeGoTDP already on the machine - they are different device
// tables and must not land in the same directory.
const PLUGIN_DIR_NAME = "LTDP";
const version = manifest.version;

const buildDir = join(repoRoot, "build");
const stageDir = join(buildDir, PLUGIN_DIR_NAME);
const zipPath = join(repoRoot, `${PLUGIN_DIR_NAME}-${version}.zip`);

/** Runtime payload only - no sources, lockfiles, git, node_modules, or bin/. */
const CONTENTS = [
  "main.py",
  "ltdp_device.py",
  "ltdp_acpi.py",
  "ltdp_updater.py",
  "plugin.json",
  "package.json",
  "README.md",
  "README.ru.md",
  "LICENSE",
  "NOTICE",
  "dist",
  // Shipped so the device half of the suite can be run where the device is.
  "tests",
];

/**
 * Shipped as well, at a path of its own: the on-device diagnostic script. It is
 * the thing a user is asked to run when something does not apply, so it has to
 * be inside the installed plugin rather than only in the repository.
 */
const EXTRA_FILES = [["scripts/ltdp-diagnostics.sh", "scripts/ltdp-diagnostics.sh"]];

function fail(message) {
  console.error(`error: ${message}`);
  process.exit(1);
}

if (!existsSync(join(repoRoot, "dist", "index.js"))) {
  fail("dist/index.js is missing - run `npm run build` first");
}

rmSync(buildDir, { recursive: true, force: true });
rmSync(zipPath, { force: true });
mkdirSync(stageDir, { recursive: true });

for (const entry of CONTENTS) {
  const from = join(repoRoot, entry);
  if (!existsSync(from)) fail(`required file missing: ${entry}`);
  cpSync(from, join(stageDir, entry), {
    recursive: true,
    // Keep build artefacts and caches out of the archive.
    filter: (src) => !/(__pycache__|\.pyc$|\.DS_Store|node_modules)/.test(src),
  });
}

for (const [from, to] of EXTRA_FILES) {
  const source = join(repoRoot, from);
  if (!existsSync(source)) fail(`required file missing: ${from}`);
  const target = join(stageDir, to);
  mkdirSync(dirname(target), { recursive: true });
  cpSync(source, target);
}

function sevenZip() {
  const candidates = [
    "C:\\Program Files\\7-Zip\\7z.exe",
    "C:\\Program Files (x86)\\7-Zip\\7z.exe",
  ];
  return candidates.find(existsSync);
}

/**
 * Last-resort archiver: Python's zipfile, which every machine that can run the
 * test-suite already has. It writes forward slashes like any other zip tool,
 * and unlike them it can set the mode bits - so the diagnostic script arrives
 * on the device executable instead of needing a chmod first.
 */
const PY_ZIP = `
import os, sys, zipfile
root, name, out = sys.argv[1], sys.argv[2], sys.argv[3]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for folder, _dirs, files in os.walk(os.path.join(root, name)):
        for filename in sorted(files):
            path = os.path.join(folder, filename)
            arcname = os.path.relpath(path, root).replace(os.sep, "/")
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            mode = 0o755 if filename.endswith(".sh") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(path, "rb") as source:
                archive.writestr(info, source.read())
print(out)
`;

function tryZip(run) {
  try {
    run();
    return true;
  } catch (err) {
    lastError = err;
    return false;
  }
}

let lastError = null;
const sevenZipPath = sevenZip();
const packed =
  (sevenZipPath &&
    tryZip(() => execFileSync(sevenZipPath, ["a", "-tzip", "-mx=9", zipPath, PLUGIN_DIR_NAME],
      { cwd: buildDir, stdio: "inherit" }))) ||
  tryZip(() => execFileSync("zip", ["-r", "-9", "-q", zipPath, PLUGIN_DIR_NAME],
    { cwd: buildDir, stdio: "inherit" })) ||
  ["python3", "python"].some((python) =>
    tryZip(() => execFileSync(python, ["-c", PY_ZIP, buildDir, PLUGIN_DIR_NAME, zipPath],
      { stdio: "inherit" })));

if (!packed) {
  fail(
    "no archiver worked. Install 7-Zip (Windows), the 'zip' package " +
    `(Linux/macOS), or Python 3: ${lastError?.message ?? "unknown error"}`,
  );
}

rmSync(buildDir, { recursive: true, force: true });
console.log(`packaged v${version} -> ${zipPath}`);
