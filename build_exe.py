#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包脚本：装依赖 → 打包两个 exe → 跑自测。

直接双击 build_exe.bat 也行，命令行跑 python build_exe.py 也行。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / "build"
REQUIREMENTS = ["pyinstaller", "pillow", "tkinterdnd2"]

TARGETS = [
    {
        "name": "FM26-头像助手",
        "script": "fm26_face_gui.py",
        "mode": "--windowed",
        "label": "图形界面版",
    },
    {
        "name": "FM26-Face-Tool",
        "script": "fm26_facepack.py",
        "mode": "--console",
        "label": "命令行版",
    },
]

TESTS = ["tests/test_fm26_core.py", "tests/test_fm26_gui_flow.py"]


def main() -> int:
    print("=" * 60)
    print("FM26 头像工具 打包脚本")
    print("Python：%s" % sys.executable)
    print("目录：%s" % HERE)
    print("=" * 60)

    print()
    print("[1/3] 检查并安装依赖 ...")
    code = subprocess.run([sys.executable, "-m", "pip", "install", *REQUIREMENTS]).returncode
    if code != 0:
        print("依赖安装失败，请检查网络后重试。")
        return 1

    print()
    print("[2/3] 开始打包 ...")
    for target in TARGETS:
        print()
        print("  正在打包%s：%s" % (target["label"], target["name"]))
        workpath = BUILD_DIR / target["name"]
        workpath.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            target["mode"],
            "--name",
            target["name"],
            "--distpath",
            str(HERE),
            "--workpath",
            str(workpath),
            "--specpath",
            str(workpath),
            str(HERE / target["script"]),
        ]
        print("  > %s" % " ".join(command[2:]))
        code = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
        ).returncode
        exe = HERE / ("%s.exe" % target["name"])
        if code != 0 or not exe.exists():
            print("  %s 打包失败。" % target["label"])
            return 1
        print("  完成：%s（%.1f MB）" % (exe.name, exe.stat().st_size / 1024 / 1024))

    print()
    print("[3/3] 跑自测 ...")
    failed = []
    for item in TESTS:
        result = subprocess.run(
            [sys.executable, str(HERE / item)],
            capture_output=True,
            text=True,
            errors="replace",
        )
        print("  %s  %s" % ("通过" if result.returncode == 0 else "失败", item))
        if result.returncode != 0:
            failed.append(item)
            tail = (result.stdout or "").strip().splitlines()[-15:]
            for line in tail:
                print("      %s" % line)

    print()
    print("=" * 60)
    if failed:
        print("自测未全部通过：%s" % "、".join(failed))
        return 1
    print("全部完成。生成的文件：")
    for target in TARGETS:
        print("  %s" % (HERE / ("%s.exe" % target["name"])))
    print()
    print("build 文件夹是打包过程中的临时文件，可以随时删掉。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
