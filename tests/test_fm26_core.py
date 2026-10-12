#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fm26_core 的单元测试，不依赖 pytest，直接运行即可。"""

import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import fm26_core as core

TESTS = []


def test(func):
    TESTS.append(func)
    return func


def make_image(path, size=(300, 200), mode="RGB", color=(20, 60, 120)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path)
    return path


def build_game_root(base: Path, version="Football Manager 2026") -> Path:
    """在临时目录里造一个假的 FM 用户数据目录。"""
    base = Path(base) / "Documents" / "Sports Interactive" / version
    (base / "graphics" / "faces").mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------- uid

@test
def uid_accepts_digits_only():
    assert core.parse_uid("2000043406") == "2000043406"
    assert core.parse_uid("  42 ") == "42"
    assert core.parse_uid("12a") is None
    assert core.parse_uid("") is None
    assert core.parse_uid("12 34") is None


@test
def uid_validation_raises_on_bad_input():
    for bad in ("abc", "", "12x", "1" * 11):
        try:
            core.validate_uid(bad)
        except ValueError:
            continue
        raise AssertionError("应当拒绝：%r" % bad)
    assert core.validate_uid(" 12345 ") == "12345"


# ---------------------------------------------------------- 图片处理

@test
def normalize_produces_square_transparent_png():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = make_image(tmp / "raw.jpg", size=(300, 200))
        dst = tmp / "out.png"
        core.normalize_image(src, dst, 250)

        with Image.open(dst) as im:
            assert im.format == "PNG", im.format
            assert im.size == (250, 250), im.size
            assert "A" in im.getbands(), im.mode
            alpha = im.getchannel("A")
            assert alpha.getextrema()[1] > 0, "内容不应全透明"
            # 上下应当留出透明边（原图更宽），角落保持全透明
            assert alpha.getpixel((0, 0)) == 0


@test
def normalize_keeps_aspect_ratio():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 宽图：上下留透明边，左右充满
        wide = make_image(tmp / "wide.png", size=(400, 100), mode="RGB")
        wide_out = tmp / "wide_out.png"
        core.normalize_image(wide, wide_out, 100)
        with Image.open(wide_out) as im:
            alpha = im.getchannel("A")
            assert alpha.getpixel((50, 0)) == 0, "上下应留透明边"
            assert alpha.getpixel((50, 50)) == 255, "中间应是不透明内容"

        # 高图：左右留透明边，上下充满
        tall = make_image(tmp / "tall.png", size=(100, 400), mode="RGB")
        tall_out = tmp / "tall_out.png"
        core.normalize_image(tall, tall_out, 100)
        with Image.open(tall_out) as im:
            alpha = im.getchannel("A")
            assert alpha.getpixel((0, 50)) == 0, "左右应留透明边"
            assert alpha.getpixel((50, 50)) == 255, "中间应是不透明内容"


# ------------------------------------------------------- config 生成

@test
def rebuild_config_maps_every_png():
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp)
        make_image(pack / "2000043406.png", size=(250, 250), mode="RGBA")
        make_image(pack / "100.png", size=(250, 250), mode="RGBA")
        (pack / "not-a-uid.png").write_bytes(b"")

        count, config_path = core.rebuild_config(pack)

        assert count == 2, count
        text = config_path.read_text(encoding="utf-8")
        assert 'from="100" to="graphics/pictures/person/100/portrait"' in text
        assert 'from="2000043406" to="graphics/pictures/person/2000043406/portrait"' in text
        assert "not-a-uid" not in text
        assert text.index('from="100"') < text.index('from="2000043406"'), "应按数字大小排序"


@test
def rebuild_config_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp)
        make_image(pack / "7.png", size=(250, 250), mode="RGBA")
        core.rebuild_config(pack)
        first = (pack / "config.xml").read_text(encoding="utf-8")
        core.rebuild_config(pack)
        second = (pack / "config.xml").read_text(encoding="utf-8")
        assert first == second


@test
def config_maps_real_players_and_newgens():
    """真实球员和随机人的查表路径不同，两条都要写。"""
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp)
        make_image(pack / "2002075255.png", size=(250, 250), mode="RGBA")
        count, config_path = core.rebuild_config(pack)
        text = config_path.read_text(encoding="utf-8")

        assert count == 1
        assert 'to="graphics/pictures/person/2002075255/portrait"' in text
        assert 'to="graphics/pictures/person/r-2002075255/portrait"' in text
        assert text.count("<record from=") == 2


@test
def scan_conflicts_reads_inside_fmf_pack():
    """随机人整合包是 .fmf，冲突检查要能读进去。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = build_game_root(tmp)
        faces_root = core.faces_root_for(game)
        managed = core.default_pack_dir(game)

        pack = faces_root / "01.随机人头像包.fmf"
        payload = (
            b"..fmf....r................<record>\n<record from=\"Mj_1\" "
            b'to="graphics/pictures/person/r-2002075255/portrait"/>\n'
        )
        pack.write_bytes(payload + b"\x00" * 4096)

        hits = core.scan_conflicts(faces_root, "2002075255", ignore_dirs=[managed])
        assert [item.name for item in hits] == ["01.随机人头像包.fmf"], hits
        assert core.scan_conflicts(faces_root, "1234567890", ignore_dirs=[managed]) == []


@test
def empty_pack_still_writes_valid_config():
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp)
        count, config_path = core.rebuild_config(pack)
        assert count == 0
        text = config_path.read_text(encoding="utf-8")
        assert text.startswith("<record>")
        assert "<list id=\"maps\">" in text


# --------------------------------------------------------- 一键安装

@test
def install_face_writes_png_and_config():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = build_game_root(tmp)
        pack = core.default_pack_dir(game)
        src = make_image(tmp / "some-player.jpg", size=(320, 320))

        result = core.install_face(src, "2000043406", pack, size=250)

        assert result.uid == "2000043406"
        assert result.total == 1
        assert result.png.exists() and result.png.name == "2000043406.png"
        with Image.open(result.png) as im:
            assert im.size == (250, 250)
        text = result.config.read_text(encoding="utf-8")
        assert 'to="graphics/pictures/person/2000043406/portrait"' in text


@test
def install_face_accumulates_and_overwrites_same_id():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = build_game_root(tmp)
        pack = core.default_pack_dir(game)

        core.install_face(make_image(tmp / "a.png", size=(100, 100), mode="RGBA"), "111", pack)
        core.install_face(make_image(tmp / "b.png", size=(100, 100), mode="RGBA"), "222", pack)
        result = core.install_face(make_image(tmp / "c.png", size=(400, 400)), "111", pack)

        assert result.total == 2, result.total
        text = result.config.read_text(encoding="utf-8")
        assert text.count("person/111/portrait") == 1
        assert text.count("person/222/portrait") == 1


@test
def install_face_rejects_bad_id():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pack = Path(tmp) / "pack"
        src = make_image(tmp / "a.png", size=(50, 50), mode="RGBA")
        try:
            core.install_face(src, "not-an-id", pack)
        except ValueError:
            return
        raise AssertionError("非法 ID 应当报错")


# -------------------------------------------------------- 目录与冲突

@test
def find_game_dirs_locates_user_data_folder():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        expected = build_game_root(tmp)
        build_game_root(tmp, version="Football Manager 2024")

        found = core.find_game_dirs(extra_roots=[tmp / "Documents"], include_default=False)
        names = [item.name for item in found]

        assert expected.name in names, names
        assert names == ["Football Manager 2026", "Football Manager 2024"], names


@test
def find_game_dirs_puts_fm26_before_older_years():
    """FM26 的目录叫 Football Manager 26，不能因为 2024 数字更大就排在前面。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for version in ("Football Manager 2024", "Football Manager 2025", "Football Manager 26"):
            build_game_root(tmp, version=version)

        found = core.find_game_dirs(extra_roots=[tmp / "Documents"], include_default=False)
        names = [item.name for item in found]
        assert names == [
            "Football Manager 26",
            "Football Manager 2025",
            "Football Manager 2024",
        ], names


@test
def pack_version_handles_year_and_short_forms():
    assert core.pack_version("Football Manager 26") == 26
    assert core.pack_version("Football Manager 2026") == 26
    assert core.pack_version("Football Manager 2024") == 24
    assert core.pack_version("Editor 2023") == 23
    assert core.pack_version("Sports Interactive") is None
    assert core.CURRENT_PACK_VERSION == 26


@test
def find_game_dirs_returns_empty_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        assert core.find_game_dirs(extra_roots=[Path(tmp)], include_default=False) == []


@test
def find_game_dirs_ignores_unrelated_folders():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        si = tmp / "Documents" / "Sports Interactive"
        (si / "Football Manager 2026").mkdir(parents=True)
        (si / "SomeOtherGame").mkdir()
        (si / "not-a-folder.txt").write_text("x", encoding="utf-8")

        found = core.find_game_dirs(extra_roots=[tmp / "Documents"], include_default=False)
        assert [item.name for item in found] == ["Football Manager 2026"], found


@test
def scan_conflicts_finds_other_packs_only():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = build_game_root(tmp)
        faces_root = core.faces_root_for(game)
        managed = core.default_pack_dir(game)

        other = faces_root / "BigFacepack"
        other.mkdir(parents=True)
        (other / "config.xml").write_text(
            '<record><list id="maps">'
            '<record from="777" to="graphics/pictures/person/777/portrait"/>'
            "</list></record>",
            encoding="utf-8",
        )

        core.install_face(make_image(tmp / "a.png", size=(60, 60), mode="RGBA"), "777", managed)
        conflicts = core.scan_conflicts(faces_root, "777", ignore_dirs=[managed])
        assert [item.name for item in conflicts] == ["config.xml"], conflicts
        assert conflicts[0].parent.name == "BigFacepack"

        assert core.scan_conflicts(faces_root, "778", ignore_dirs=[managed]) == []
        # 不排除自己的时候，自己的包也在结果里
        everyone = {item.parent.name for item in core.scan_conflicts(faces_root, "777")}
        assert everyone == {"BigFacepack", "MyFaces"}, everyone


# ------------------------------------------------------------- 设置

@test
def settings_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        assert core.load_settings(path) == {}
        core.save_settings({"game_dir": "D:/x", "last_uid": "123"}, path)
        loaded = core.load_settings(path)
        assert loaded["game_dir"] == "D:/x"
        assert loaded["last_uid"] == "123"


@test
def settings_survive_corrupt_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text("{not json", encoding="utf-8")
        assert core.load_settings(path) == {}


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
        print("失败：%s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
