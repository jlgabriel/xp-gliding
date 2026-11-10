# Release checklist

The steps for a release, written down after three releases in two days (2026-11-08 and 09) done from memory, at the suggestion of the [audit](audit-2026-11-09.md#22-el-proceso-de-release). Juan Luis decides when a version goes out and publishes it; the rest is prepared for him.

1. **Tests:** `.venv/Scripts/python.exe -m pytest` passes, and CI on GitHub is green for the commit.
2. **In X-Plane** (by the test pilot): an air start in the ASK 21 with the version installed by `tools/install_plugin.py`; no traceback in `XPPython3Log.txt`, the menu's status line says *Active*, and anything new in this version tried once.
3. **Version** in `xp_gliding/__init__.py`. `tests/test_release.py` fails until the public text says the same: `README.md`, `docs/README.md` and `docs/pilot-guide.md` (two places).
4. **CHANGELOG.md:** the *Unreleased* section becomes the version, with its date.
5. **Commit and push** (Juan Luis asks for it). `tools/make_release.py` refuses to build while what it packages differs from the commit.
6. **Zip:** `python tools/make_release.py` writes `dist/xp-gliding-<version>.zip`.
7. **Install from the zip** as a pilot would: delete `PythonPlugins/xp_gliding`, copy the zip's two items, start X-Plane, and see `<version> starting` in the log and the plugin active.
8. **Release notes** in `dist/release-notes-<version>.md`, from the changelog, with how to update from the last version.
9. **Publish** (Juan Luis): the GitHub release with the zip and its notes, tagged on the commit; then `git fetch --tags` here.
10. **Forum** (Juan Luis): edit the thread's first post for the version and add a short reply ([thread](https://forums.x-plane.org/forums/topic/353728-xp-gliding-xppython3-plugin-for-x-plane-12/)).
11. **Spec:** record the version under [To package and publish](SPEC.md#stage-1-first-release).
