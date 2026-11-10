"""The version the public text names is the package's (notes/release-checklist.md)."""

import os
import re

from xp_gliding import __version__

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        return f.read()


def test_the_public_text_names_the_packages_version():
    assert f"**Version {__version__}.**" in read("README.md")
    assert f"current version is {__version__}." in read("docs/README.md")
    guide = read("docs/pilot-guide.md")
    assert f"This guide is for version {__version__}." in guide
    assert f"`xp-gliding-{__version__}.zip`" in guide


def test_the_changelog_has_the_version_or_it_is_unreleased():
    headings = re.findall(r"^## (.+)$", read("CHANGELOG.md"), flags=re.MULTILINE)
    released = [h.split(" ")[0] for h in headings if h != "Unreleased"]
    assert released[0] == __version__, "the newest released heading is the package's version"
