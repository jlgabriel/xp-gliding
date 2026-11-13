"""Cloud styles: finding them, reading their style.txt, and the menu's labels (adapter/styles.py)."""

import os

from xp_gliding.adapter import config, styles

BUNDLED = os.path.join(os.path.dirname(os.path.dirname(__file__)), "xp_gliding", "assets", "clouds")


def make_style(root, key, info=None, obj=True):
    folder = root / key
    folder.mkdir(parents=True)
    if obj:
        (folder / "cumulus.obj").write_text("A\n800\nOBJ\n")
    if info is not None:
        (folder / "style.txt").write_bytes(info.encode("utf-8"))
    return folder


def test_the_plugin_ships_the_standard_style():
    found, notes = styles.find_styles(BUNDLED, None)
    assert notes == []
    assert found[0].key == styles.DEFAULT_STYLE and found[0].label == "Standard"
    assert found[0].license == "GPL-3.0-or-later" and not found[0].own
    assert os.path.isfile(found[0].object_path)


def test_the_standard_style_first_then_the_pilots_by_name(tmp_path):
    bundled, own = tmp_path / "bundled", tmp_path / "own"
    for key in ("zeta", "standard", "Alpha"):
        make_style(bundled, key)
    for key in ("soft", "Grey"):
        make_style(own, key)
    found, notes = styles.find_styles(str(bundled), str(own))
    assert [s.key for s in found] == ["standard", "Alpha", "zeta", "Grey", "soft"]
    assert [s.own for s in found] == [False, False, False, True, True]
    assert notes == []


def test_a_folder_with_no_object_or_a_taken_name_is_left_out_and_said(tmp_path):
    bundled, own = tmp_path / "bundled", tmp_path / "own"
    make_style(bundled, "standard")
    make_style(own, "empty", obj=False)
    make_style(own, "Standard")  # the plugin's own name, in another case
    (own / "loose.png").write_bytes(b"")  # a file, not a style
    found, notes = styles.find_styles(str(bundled), str(own))
    assert [s.key for s in found] == ["standard"]
    assert len(notes) == 2 and "no cumulus.obj" in notes[0] and "folder name" in notes[1]


def test_no_folder_for_the_pilots_styles_is_no_style(tmp_path):
    found, notes = styles.find_styles(BUNDLED, str(tmp_path / "missing"))
    assert [s.key for s in found] == ["standard"] and notes == []


def test_style_txt_gives_name_author_and_license_and_nothing_else(tmp_path):
    folder = make_style(tmp_path, "soft", "# a comment\nName:  Soft cumulus \nauthor: Ana Pérez\n"
                                          "license: CC-BY-4.0\nname: a second name\nwhatever: x\nno colon\n")
    assert styles.read_info(str(folder)) == {"name": "Soft cumulus", "author": "Ana Pérez",
                                             "license": "CC-BY-4.0"}
    style = styles.styles_in(str(tmp_path), own=True)[0][0]
    assert style.label == "Soft cumulus, by Ana Perez"  # plain ASCII for the menu


def test_a_style_with_no_or_unreadable_style_txt_goes_by_its_folder(tmp_path):
    make_style(tmp_path, "plain")
    folder = make_style(tmp_path, "binary")
    (folder / "style.txt").write_bytes(b"\xff\xfe\x00name\x00")
    found = {s.key: s for s in styles.styles_in(str(tmp_path), own=True)[0]}
    assert found["plain"].label == "plain" and found["binary"].label == "binary"


def test_a_label_is_ascii_and_short():
    assert styles.ascii_label("Cúmulos  de\tÑuñoa ☁") == "Cumulos de Nunoa"
    long = styles.ascii_label("x" * 100)
    assert len(long) == styles.MAX_LABEL and long.endswith("...")


def test_the_menu_shows_at_most_max_styles(tmp_path):
    for k in range(styles.MAX_STYLES + 3):
        make_style(tmp_path / "own", f"s{k:02d}")
    found, notes = styles.find_styles(BUNDLED, str(tmp_path / "own"))
    assert len(found) == styles.MAX_STYLES and found[0].key == "standard"
    assert any("menu shows the first" in note for note in notes)


def test_a_style_that_is_gone_is_the_standard_one(tmp_path):
    found, _ = styles.find_styles(BUNDLED, None)
    assert styles.style_named(found, "gone").key == "standard"
    assert styles.style_named([], "standard") is None
    other = make_style(tmp_path, "other")
    only = [styles.CloudStyle("other", str(other), own=True)]
    assert styles.style_named(only, "gone").key == "other"


def test_the_setting_takes_a_folder_name_and_nothing_else():
    assert config.Settings().cloud_style == "standard"
    assert config.Settings({"cloud_style": "soft"}).cloud_style == "soft"
    for bad in (3, "", "   ", None, ["soft"], "x" * 300):
        s = config.Settings()
        assert s.update({"cloud_style": bad}) == [f"cloud_style {bad!r} left out"]
        assert s.cloud_style == "standard"
