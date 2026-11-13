"""Cloud styles: how the cumulus look, chosen in the menu as a livery is for an aircraft.

A style is a folder holding `cumulus.obj`, the object each cloud is an instance of, with the
particle system and texture it names beside it, and an optional `style.txt`:

    name: Soft cumulus
    author: Someone
    license: CC-BY-4.0

The styles that come with the plugin are in `xp_gliding/assets/clouds/`, `standard` first, made
by `tools/make_cloud_objs.py`. The pilot's own go in `Output/xp-gliding/cloud-styles/` under
X-Plane's folder, which a new version of the plugin does not replace. A style only changes how
the clouds look: where they are, how big, how high and how long they live stay the engine's,
through the instance's rate and scale datarefs (`clouds.py`). How to make one is in
`docs/cloud-styles.md`.

Read once, when the plugin starts: a style added later shows after X-Plane restarts.

Pure Python: no `xp`.
"""

import os
import unicodedata

OBJECT_FILE = "cumulus.obj"
INFO_FILE = "style.txt"
DEFAULT_STYLE = "standard"
OWN_FOLDER = "cloud-styles"  # under Output/xp-gliding/
MAX_STYLES = 40  # more than a menu can show well; the rest are left out, and the log says so
MAX_LABEL = 60
MAX_INFO_BYTES = 4096


class CloudStyle:
    """One style: key is its folder's name, what config.json keeps."""

    __slots__ = ("key", "name", "author", "license", "folder", "own")

    def __init__(self, key, folder, own, name=None, author="", license=""):
        self.key = key
        self.folder = folder
        self.own = own  # the pilot's, from Output/xp-gliding/cloud-styles/
        self.name = name or key
        self.author = author
        self.license = license

    @property
    def object_path(self):
        return os.path.join(self.folder, OBJECT_FILE)

    @property
    def label(self):
        """What the menu shows: plain ASCII, since a menu may not draw other characters."""
        text = f"{self.name}, by {self.author}" if self.author else self.name
        return ascii_label(text)

    def __repr__(self):
        return f"CloudStyle({self.key!r}, {self.folder!r})"


def ascii_label(text):
    """Accents dropped, anything else outside ASCII left out, and no longer than MAX_LABEL."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    plain = " ".join(plain.split())
    return plain if len(plain) <= MAX_LABEL else plain[:MAX_LABEL - 3].rstrip() + "..."


def read_info(folder):
    """The name, author and license from the folder's style.txt: `key: value` lines, other keys
    and lines left out. Empty where there is no such file or it cannot be read."""
    path = os.path.join(folder, INFO_FILE)
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_INFO_BYTES)
    except OSError:
        return {}
    info = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        key, sep, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if sep and key in ("name", "author", "license") and value and key not in info:
            info[key] = value
    return info


def styles_in(root, own):
    """(styles, notes) for the folders under root that hold a cumulus.obj, by folder name; notes
    say what was left out, for the log. Nothing where root does not exist."""
    try:
        names = sorted(os.listdir(root), key=str.lower)
    except OSError:
        return [], []
    styles, notes = [], []
    for name in names:
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or name.startswith("."):
            continue
        if not os.path.isfile(os.path.join(folder, OBJECT_FILE)):
            notes.append(f"{folder} has no {OBJECT_FILE}, left out")
            continue
        styles.append(CloudStyle(name, folder, own, **read_info(folder)))
    return styles, notes


def find_styles(bundled_root, own_root):
    """(styles, notes): the plugin's styles, `standard` first, then the pilot's. A pilot's style
    with the folder name of one of the plugin's is left out, so a choice always means one style."""
    bundled, notes = styles_in(bundled_root, own=False)
    bundled.sort(key=lambda s: (s.key != DEFAULT_STYLE, s.key.lower()))
    own, own_notes = styles_in(own_root, own=True) if own_root else ([], [])
    notes += own_notes
    taken = {s.key.lower() for s in bundled}
    styles = list(bundled)
    for style in own:
        if style.key.lower() in taken:
            notes.append(f"{style.folder}: a style of the plugin has that folder name, left out")
        else:
            taken.add(style.key.lower())
            styles.append(style)
    if len(styles) > MAX_STYLES:
        notes.append(f"{len(styles)} cloud styles; the menu shows the first {MAX_STYLES}")
        styles = styles[:MAX_STYLES]
    return styles, notes


def style_named(styles, key):
    """The style with this key; `standard` if there is none, or the first if `standard` is gone too."""
    by_key = {s.key: s for s in styles}
    return by_key.get(key) or by_key.get(DEFAULT_STYLE) or (styles[0] if styles else None)
