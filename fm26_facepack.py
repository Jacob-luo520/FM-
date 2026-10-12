#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FM26 真实球员头像 config.xml 生成工具（命令行版）

用法：
    python fm26_facepack.py "D:\\faces"                     就地生成 config.xml
    python fm26_facepack.py "D:\\raw" --prepare "D:\\ready"  先规整为 250x250 PNG 再生成

规则：图片文件名（不含扩展名）必须是球员 UID，例如 2000043406.png
图形界面版本见 fm26_face_gui.py。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fm26_core as core
from fm26_core import (
    CONFIG_NAME,
    DEFAULT_SIZE,
    REPORT_NAME,
    build_config,
    collect_images,
    inspect_image,
    normalize_image,
    parse_uid,
    pick_best,
    write_text,
)


def log(message: str = "") -> None:
    print(message)


def relax_console_encoding() -> None:
    """编码受限的控制台上，避免中文输出直接抛异常中断流程。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FM26 真实球员头像 config.xml 生成工具")
    parser.add_argument("folder", nargs="?", default=".", help="存放头像图片的文件夹")
    parser.add_argument(
        "--prepare",
        metavar="OUT_DIR",
        default=None,
        help="把图片统一裁剪缩放为方形透明 PNG 并输出到该文件夹（需要 Pillow）",
    )
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE, help="头像边长，默认 250")
    parser.add_argument("--preload", action="store_true", help="在 config 中开启预加载")
    parser.add_argument("--dry-run", action="store_true", help="只检查不写文件")
    parser.add_argument("--no-backup", action="store_true", help="不备份已存在的 config.xml")
    parser.add_argument("--no-pause", action="store_true", help="跑完后不暂停等待按键")
    return parser


def main(argv=None) -> int:
    relax_console_encoding()
    args = build_parser().parse_args(argv)

    # 直接双击 exe 时，默认处理 exe 所在的文件夹
    if getattr(sys, "frozen", False) and args.folder == ".":
        args.folder = str(Path(sys.executable).parent)

    source = Path(args.folder).expanduser()
    if source.is_file():
        source = source.parent
    if not source.is_dir():
        log("找不到文件夹：%s" % source)
        return 1
    source = source.resolve()

    prepare_dir = Path(args.prepare).expanduser().resolve() if args.prepare else None
    if prepare_dir and core.Image is None:
        log("整理图片需要 Pillow，请先运行：pip install pillow")
        return 1

    log("=" * 60)
    log("FM26 头像工具")
    log("图片文件夹：%s" % source)
    if prepare_dir:
        log("输出文件夹：%s" % prepare_dir)
    log("=" * 60)

    images = collect_images(source, skip_dirs=[prepare_dir] if prepare_dir else [])
    if not images:
        log("没有找到任何图片，请确认图片已经放进这个文件夹。")
        return 1

    buckets = {}
    bad_names = []
    for path in images:
        uid = parse_uid(path.stem)
        if uid is None:
            bad_names.append(path)
        else:
            buckets.setdefault(uid, []).append(path)

    duplicates = {uid: paths for uid, paths in buckets.items() if len(paths) > 1}
    chosen = {uid: pick_best(paths) for uid, paths in buckets.items()}
    problems = {}
    for uid, path in chosen.items():
        issues = inspect_image(path, args.size)
        if issues:
            problems[uid] = (path, issues)
    ordered_uids = sorted(chosen.keys(), key=lambda value: int(value))

    log("扫描到图片：%d 张" % len(images))
    log("可用头像：%d 个" % len(chosen))
    if core.Image is None:
        log("提示：未安装 Pillow，本次跳过图片规格检查")
    if duplicates:
        log("重复 UID：%d 个（每个只保留一张）" % len(duplicates))
    if bad_names:
        log("文件名不是 UID 的图片：%d 张（已忽略）" % len(bad_names))
    if problems:
        log("规格有问题的头像：%d 个" % len(problems))
    log()

    if args.dry_run:
        log("dry-run 模式，未写入任何文件。")
        return 0

    if prepare_dir:
        prepare_dir.mkdir(parents=True, exist_ok=True)
        done = 0
        failed = []
        for uid in ordered_uids:
            try:
                normalize_image(chosen[uid], prepare_dir / ("%s.png" % uid), args.size)
                done += 1
            except Exception as exc:
                failed.append((uid, chosen[uid], exc))
        log("已输出规整头像：%d 张 → %s" % (done, prepare_dir))
        for uid, path, reason in failed:
            log("  处理失败 %s（%s）：%s" % (uid, path.name, reason))
        config_dir = prepare_dir
        entries = [
            (uid, uid) for uid in ordered_uids if (prepare_dir / ("%s.png" % uid)).exists()
        ]
    else:
        config_dir = source
        entries = [
            (uid, chosen[uid].relative_to(source).with_suffix("").as_posix())
            for uid in ordered_uids
        ]

    config_path = config_dir / CONFIG_NAME
    if config_path.exists() and not args.no_backup:
        shutil.copy2(config_path, config_path.with_name(CONFIG_NAME + ".bak"))
        log("已备份原有 config.xml → config.xml.bak")
    write_text(config_path, build_config(entries, args.preload))
    log("已生成：%s（%d 条映射）" % (config_path, len(entries)))

    report = [
        "FM26 头像检查报告",
        "生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "图片文件夹：%s" % source,
        "扫描到图片：%d 张" % len(images),
        "写入 config.xml 的头像：%d 个" % len(entries),
        "",
        "【重复 UID】",
    ]
    if duplicates:
        for uid in sorted(duplicates.keys(), key=lambda value: int(value)):
            keep = chosen[uid]
            report.append("  %s：保留 %s" % (uid, keep.name))
            for path in duplicates[uid]:
                if path != keep:
                    report.append("      忽略 %s" % path.name)
    else:
        report.append("  无")
    report.append("")
    report.append("【文件名不是 UID，已忽略】")
    if bad_names:
        report.extend("  %s" % path.relative_to(source).as_posix() for path in bad_names)
    else:
        report.append("  无")
    report.append("")
    report.append("【图片规格问题】")
    if problems:
        for uid in sorted(problems.keys(), key=lambda value: int(value)):
            path, issues = problems[uid]
            report.append("  %s（%s）" % (uid, path.name))
            report.extend("      - %s" % item for item in issues)
    else:
        report.append("  无")
    report.append("")
    report.append("【下一步】")
    report.append("  1. 把头像文件夹（含 config.xml）复制到：")
    report.append("     文档\\Sports Interactive\\Football Manager 2026\\graphics\\faces\\")
    report.append("  2. 游戏内 Preferences → Interface：取消勾选 Use caching to decrease page loading times")
    report.append("  3. 点击 Reload Skin（或按 Shift+R）")
    report.append("  4. 若仍不显示：退出游戏，删除 Football Manager 2026\\cache 文件夹后重进")

    report_path = config_dir / REPORT_NAME
    write_text(report_path, "\n".join(report) + "\n")
    log("已生成检查报告：%s" % report_path)
    log()
    log("完成。把该文件夹整个复制到 FM26 的 graphics\\faces 里，再重载皮肤即可。")
    return 0


if __name__ == "__main__":
    exit_code = main()
    if getattr(sys, "frozen", False) and "--no-pause" not in sys.argv:
        try:
            input("处理完毕，按回车键关闭窗口...")
        except EOFError:
            pass
    sys.exit(exit_code)
