#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证界面按钮背后那条通路（不打开窗口）。"""

import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import fm26_core as core
import fm26_face_gui as gui

TESTS = []


def test(func):
    TESTS.append(func)
    return func


def make_image(path, size=(300, 300), mode="RGB", color=(30, 90, 150)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path)
    return path


@test
def install_flow_writes_face_and_config():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = tmp / "Sports Interactive" / "Football Manager 2026"
        (game / "graphics" / "faces").mkdir(parents=True)
        pack = core.default_pack_dir(game)
        source = make_image(tmp / "photo.jpg", size=(400, 250))

        result, conflicts = gui.run_install(
            source, "2000043406", pack, faces_root=core.faces_root_for(game)
        )

        assert result.png.name == "2000043406.png"
        with Image.open(result.png) as im:
            assert im.size == (250, 250)
        assert conflicts == []
        assert 'to="graphics/pictures/person/2000043406/portrait"' in result.config.read_text(
            encoding="utf-8"
        )


@test
def install_flow_reports_conflicting_pack():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = tmp / "Sports Interactive" / "Football Manager 2026"
        faces = game / "graphics" / "faces"
        faces.mkdir(parents=True)
        pack = core.default_pack_dir(game)

        other = faces / "MegaFacepack"
        other.mkdir()
        (other / "config.xml").write_text(
            '<record><list id="maps">'
            '<record from="55" to="graphics/pictures/person/55/portrait"/>'
            "</list></record>",
            encoding="utf-8",
        )

        source = make_image(tmp / "photo.png", size=(250, 250), mode="RGBA")
        result, conflicts = gui.run_install(
            source, "55", pack, faces_root=core.faces_root_for(game)
        )

        assert [item.parent.name for item in conflicts] == ["MegaFacepack"], conflicts
        assert result.total == 1


@test
def install_flow_rejects_bad_id():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source = make_image(tmp / "photo.png", size=(120, 120), mode="RGBA")
        try:
            gui.run_install(source, "player-55", tmp / "pack")
        except ValueError:
            return
        raise AssertionError("非法 ID 应当报错")


def main() -> int:
    failed = []
    for func in TESTS:
        try:
            func()
        except Exception:
            failed.append(func.__name__)
            print("FAIL  %s" % func.__name__)
            traceback.print_exc()
        else:
            print("PASS  %s" % func.__name__)
    print()
    print("通过 %d / %d" % (len(TESTS) - len(failed), len(TESTS)))
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
