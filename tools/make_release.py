"""Build the release zip that pilots install from.

Usage:
    python tools/make_release.py [--out dist] [--allow-dirty]

Writes `dist/xp-gliding-<version>.zip` with one folder inside, `xp-gliding-<version>/`,
holding what a pilot copies into `Resources/plugins/PythonPlugins/`
(`PI_xp_gliding.py` and the `xp_gliding` package, without caches) and, beside them,
`README.txt` (how to install it) and `LICENSE`. The tools, tests, notes and the
flight logger stay out. The version is `xp_gliding.__version__`.

The zip is built from the working tree, so it refuses to build while anything that goes into it
differs from the last commit or is not tracked by git (`--allow-dirty` builds anyway, for a try).
The maintainer's release checklist covers the steps around it.

License: GPL-3.0-or-later.
"""

import argparse
import os
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "PI_xp_gliding.py"
PACKAGE = "xp_gliding"
README = os.path.join(REPO, "tools", "release", "README.txt")
SKIP_DIRS = {"__pycache__"}
SKIP_EXT = (".pyc", ".pyo")


def version():
    """__version__ from the package, read as text so that nothing is imported."""
    with open(os.path.join(REPO, PACKAGE, "__init__.py"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("no __version__ in xp_gliding/__init__.py")


def package_files():
    """(path on disk, path in the zip under the top folder) for the plugin itself."""
    yield os.path.join(REPO, ENTRY), ENTRY
    root = os.path.join(REPO, PACKAGE)
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(SKIP_EXT):
                continue
            path = os.path.join(folder, name)
            yield path, os.path.relpath(path, REPO).replace(os.sep, "/")


def uncommitted():
    """What goes into the zip and differs from the last commit, or is not tracked: git's lines."""
    paths = [ENTRY, PACKAGE, "LICENSE", os.path.relpath(README, REPO)]
    result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
                            cwd=REPO, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines()
            if "__pycache__" not in line and not line.endswith(SKIP_EXT)]


def build(out_dir):
    ver = version()
    top = f"xp-gliding-{ver}"
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, top + ".zip")
    with open(README, encoding="utf-8") as f:
        readme = f.read().replace("{version}", ver)
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        # Windows line endings, so that Notepad shows the text as written.
        z.writestr(f"{top}/README.txt", readme.replace("\r\n", "\n").replace("\n", "\r\n"))
        z.write(os.path.join(REPO, "LICENSE"), f"{top}/LICENSE")
        for path, name in package_files():
            z.write(path, f"{top}/{name}")
            count += 1
    print(f"wrote {target}: {count} plugin files, README.txt and LICENSE")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the xp-gliding release zip")
    parser.add_argument("--out", default=os.path.join(REPO, "dist"), help="output folder (default: dist)")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="build even with uncommitted or untracked files in what is packaged")
    args = parser.parse_args(argv)
    dirty = uncommitted()
    if dirty and not args.allow_dirty:
        raise SystemExit("not building: these differ from the last commit or are untracked:\n  "
                         + "\n  ".join(dirty))
    build(args.out)


if __name__ == "__main__":
    sys.exit(main())
