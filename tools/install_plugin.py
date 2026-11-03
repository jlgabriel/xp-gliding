"""Install the xp-gliding plugin into X-Plane's PythonPlugins folder.

Usage:
    python tools/install_plugin.py [--xplane "D:/.../X-Plane 12"] [--dry-run]

Copies `PI_xp_gliding.py` and the `xp_gliding` package (without caches) into
`Resources/plugins/PythonPlugins/`, replacing a previous copy of the package
so that deleted modules do not linger. X-Plane must be restarted afterwards:
XPPython3's "Reload scripts" does not reload submodules and is unreliable
with numpy (SPEC, XPPython3 platform facts). The X-Plane folder defaults to
the XPLANE_DIR environment variable.

License: GPL-3.0-or-later.
"""

import argparse
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "PI_xp_gliding.py"
PACKAGE = "xp_gliding"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def install(xplane_dir, dry_run=False):
    dest = os.path.join(xplane_dir, "Resources", "plugins", "PythonPlugins")
    if not os.path.isdir(dest):
        raise SystemExit(f"not found: {dest} (is XPPython3 installed and run once?)")
    pkg_dest = os.path.join(dest, PACKAGE)
    if os.path.exists(pkg_dest) and not os.path.isfile(os.path.join(pkg_dest, "__init__.py")):
        raise SystemExit(f"{pkg_dest} exists but is not a Python package; not touching it")
    actions = [f"copy {ENTRY} -> {dest}"]
    if os.path.exists(pkg_dest):
        actions.append(f"replace {pkg_dest}")
    else:
        actions.append(f"create {pkg_dest}")
    for line in actions:
        print(("[dry run] " if dry_run else "") + line)
    if dry_run:
        return
    shutil.copy2(os.path.join(REPO, ENTRY), os.path.join(dest, ENTRY))
    if os.path.exists(pkg_dest):
        shutil.rmtree(pkg_dest)
    shutil.copytree(os.path.join(REPO, PACKAGE), pkg_dest, ignore=IGNORE)
    count = sum(len(files) for _, _, files in os.walk(pkg_dest))
    print(f"installed {count} package files; restart X-Plane to load them")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install xp-gliding into X-Plane 12")
    parser.add_argument("--xplane", default=os.environ.get("XPLANE_DIR"),
                        help="X-Plane 12 folder (default: $XPLANE_DIR)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.xplane:
        parser.error("give --xplane or set XPLANE_DIR")
    install(args.xplane, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
