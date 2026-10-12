#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FM26 头像助手（图形界面版）

选一张图片，填上球员 ID，点一下就把头像装进游戏。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import fm26_core as core
from fm26_core import DEFAULT_SIZE, MANAGED_PACK_NAME

try:
    from PIL import Image, ImageGrab, ImageTk
except Exception:  # pragma: no cover
    Image = ImageGrab = ImageTk = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND_LIB = True
except Exception:  # pragma: no cover - 没装拖拽库时自动降级
    DND_FILES = None
    TkinterDnD = None
    HAS_DND_LIB = False

TITLE = "FM26 头像助手"
PREVIEW_SIZE = 168
IMAGE_FILETYPES = [
    ("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tga *.tif *.tiff"),
    ("所有文件", "*.*"),
]


def run_install(image_path, uid, pack_dir, size=DEFAULT_SIZE, faces_root=None):
    """界面和命令行自检都走这条通路：写图片 + 重建 config + 查冲突。"""
    result = core.install_face(image_path, uid, pack_dir, size=size)
    conflicts = []
    if faces_root is not None:
        conflicts = core.scan_conflicts(faces_root, result.uid, ignore_dirs=[pack_dir])
    return result, conflicts


def make_root():
    """有拖拽库就用它，没有或初始化失败就退回普通窗口。"""
    if HAS_DND_LIB:
        try:
            return TkinterDnD.Tk(), True
        except Exception:
            pass
    return tk.Tk(), False


def log_path() -> Path:
    """崩溃日志写到程序旁边，方便出问题时排查。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "fm26-error.log"
    return Path(__file__).resolve().parent / "fm26-error.log"


def write_error_log(detail: str) -> None:
    try:
        log_path().write_text(detail, encoding="utf-8")
    except Exception:
        pass


def safe_print(text: str) -> None:
    """打包成窗口程序后没有控制台，这里要能优雅降级。"""
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        stream.write(text + "\n")
        stream.flush()
    except Exception:
        pass


class FaceAssistant:
    def __init__(self):
        self.root, self.dnd_enabled = make_root()
        self.root.title(TITLE)
        self.root.geometry("760x660")
        self.root.minsize(700, 600)

        self.settings = core.load_settings()
        self.user_data_dir = None
        self.image_path = None
        self.preview_image = None
        self.preview_source = None
        self.queue = queue.Queue()
        self.busy = False

        self._build_style()
        self._build_widgets()
        self._restore_state()
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------ 构建界面

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Main.TButton", font=("Microsoft YaHei UI", 12), padding=(10, 8))
        style.configure("Big.TButton", font=("Microsoft YaHei UI", 13, "bold"), padding=(10, 12))
        style.configure("Hint.TLabel", foreground="#666666")

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        self._build_game_row(outer)
        self._build_image_area(outer)
        self._build_id_row(outer)
        self._build_action_row(outer)
        self._build_log(outer)

    def _build_game_row(self, parent):
        box = ttk.LabelFrame(parent, text="游戏目录（FM 的用户数据目录）", padding=10)
        box.pack(fill="x")

        row = ttk.Frame(box)
        row.pack(fill="x")

        self.game_var = tk.StringVar()
        self.game_box = ttk.Combobox(row, textvariable=self.game_var, values=[])
        self.game_box.pack(side="left", fill="x", expand=True)
        self.game_box.bind("<<ComboboxSelected>>", self._on_game_selected)

        ttk.Button(row, text="浏览…", command=self.choose_game_dir, style="Main.TButton").pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(row, text="打开文件夹", command=self.open_pack_folder, style="Main.TButton").pack(
            side="left", padx=(6, 0)
        )

        self.game_hint = ttk.Label(box, text="", style="Hint.TLabel")
        self.game_hint.pack(fill="x", pady=(6, 0))

    def _build_image_area(self, parent):
        box = ttk.LabelFrame(parent, text="头像图片", padding=10)
        box.pack(fill="x", pady=(10, 0))

        left = ttk.Frame(box)
        left.pack(side="left")

        self.preview = tk.Label(
            left,
            width=0,
            bg="#f0f0f0",
            relief="solid",
            borderwidth=1,
            text="把图片拖到这里\n或点右边的按钮选择",
            font=("Microsoft YaHei UI", 9),
            fg="#888888",
            compound="center",
        )
        self.preview.configure(width=24, height=9)
        self.preview.pack()

        right = ttk.Frame(box)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        ttk.Button(right, text="选择图片…", command=self.choose_image, style="Main.TButton").pack(
            fill="x"
        )
        ttk.Button(
            right, text="从剪贴板粘贴", command=self.paste_image, style="Main.TButton"
        ).pack(fill="x", pady=(6, 0))
        ttk.Button(right, text="清除", command=self.clear_image, style="Main.TButton").pack(
            fill="x", pady=(6, 0)
        )

        self.image_info = ttk.Label(right, text="还没有选择图片", style="Hint.TLabel", wraplength=380)
        self.image_info.pack(fill="x", pady=(10, 0))

        if self.dnd_enabled:
            for widget in (self.root, self.preview):
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                except Exception:
                    pass

    def _build_id_row(self, parent):
        box = ttk.LabelFrame(parent, text="球员 ID", padding=10)
        box.pack(fill="x", pady=(10, 0))

        row = ttk.Frame(box)
        row.pack(fill="x")

        validate = (self.root.register(self._only_digits), "%P")
        self.uid_var = tk.StringVar()
        self.uid_entry = ttk.Entry(
            row, textvariable=self.uid_var, width=18, font=("Consolas", 12),
            validate="key", validatecommand=validate,
        )
        self.uid_entry.pack(side="left", ipady=4)

        ttk.Label(row, text="只填数字，例如 2000043406", style="Hint.TLabel").pack(
            side="left", padx=(10, 0)
        )

        ttk.Label(
            box,
            text="游戏里怎么查：Preferences → Interface 勾选 Show Unique IDs，再打开球员档案页，名字下方就是这串数字。",
            style="Hint.TLabel",
            wraplength=690,
        ).pack(fill="x", pady=(6, 0))

    def _build_action_row(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(12, 0))

        self.install_button = ttk.Button(
            row, text="安装到游戏", command=self.on_install, style="Big.TButton"
        )
        self.install_button.pack(side="left")

        self.status_var = tk.StringVar(value="准备就绪")
        ttk.Label(row, textvariable=self.status_var, font=("Microsoft YaHei UI", 10)).pack(
            side="left", padx=(12, 0)
        )

    def _build_log(self, parent):
        box = ttk.LabelFrame(parent, text="日志", padding=6)
        box.pack(fill="both", expand=True, pady=(10, 0))

        self.log_text = tk.Text(box, height=8, wrap="word", font=("Microsoft YaHei UI", 9))
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set, state="disabled")
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self.log_text.tag_configure("ok", foreground="#1a7f37")
        self.log_text.tag_configure("warn", foreground="#b26a00")
        self.log_text.tag_configure("err", foreground="#c0392b")
        self.log_text.tag_configure("info", foreground="#333333")

    # ------------------------------------------------------------ 状态恢复

    def _restore_state(self):
        found = core.find_game_dirs()
        if found:
            self.game_box.configure(values=[str(item) for item in found])

        saved = self.settings.get("game_dir")
        if saved and Path(saved).is_dir():
            self.set_game_dir(Path(saved), quiet=True)

        if not self.user_data_dir:
            if found:
                self.set_game_dir(found[0])
                if len(found) > 1:
                    self.log(
                        "另外还发现：%s，可在上面的下拉框里切换。"
                        % "、".join(item.name for item in found[1:]),
                        "info",
                    )
            else:
                self.log("没有自动找到 FM26 的用户数据目录，请点“浏览…”手动选择。", "warn")
                self.log(
                    "一般位置：文档\\Sports Interactive\\Football Manager 26", "info"
                )

        last_uid = self.settings.get("last_uid")
        if last_uid:
            self.uid_var.set(last_uid)

        self.log("选一张图片、填上球员 ID，然后点“安装到游戏”。", "info")

    # -------------------------------------------------------------- 小工具

    def _only_digits(self, proposed):
        return proposed == "" or (proposed.isdigit() and len(proposed) <= 10)

    def log(self, message, tag="info"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.install_button.configure(state=state)

    # ---------------------------------------------------------- 游戏目录

    def set_game_dir(self, path, quiet=False):
        path = Path(path)
        if not str(path).strip():
            return
        self.user_data_dir = path
        self.game_var.set(str(path))
        pack = core.default_pack_dir(path)
        hint = "头像会装到：%s" % pack
        version = core.pack_version(path.name)
        if version is not None and version != core.CURRENT_PACK_VERSION:
            hint += "　（注意：这不是 FM26 的目录，玩 FM26 的话请切换）"
        self.game_hint.configure(text=hint)
        if not quiet:
            self.log("游戏目录已设为：%s" % path, "info")
        self.save_settings()

    def _on_game_selected(self, event=None):
        value = self.game_var.get().strip()
        if value:
            self.set_game_dir(Path(value))

    def choose_game_dir(self):
        initial = str(self.user_data_dir) if self.user_data_dir else str(Path.home())
        chosen = filedialog.askdirectory(title="选择 Football Manager 26 的用户数据目录", initialdir=initial)
        if not chosen:
            return
        path = Path(chosen)
        if path.name.lower().startswith("graphics"):
            path = path.parent
        values = list(self.game_box.cget("values"))
        if str(path) not in values:
            values.append(str(path))
            self.game_box.configure(values=values)
        self.set_game_dir(path)

    def pack_dir(self):
        if not self.user_data_dir:
            return None
        return core.default_pack_dir(self.user_data_dir)

    def open_pack_folder(self):
        pack = self.pack_dir()
        if not pack:
            messagebox.showwarning(TITLE, "还没有选定游戏目录。")
            return
        try:
            pack.mkdir(parents=True, exist_ok=True)
            os.startfile(str(pack))
        except Exception as exc:
            messagebox.showerror(TITLE, "打不开文件夹：%s" % exc)

    # ---------------------------------------------------------------- 图片

    def on_drop(self, event):
        try:
            items = self.root.tk.splitlist(event.data)
        except Exception:
            items = [event.data]
        for item in items:
            path = Path(item)
            if path.is_file():
                self.set_image(path, from_disk=True)
                return
            if path.is_dir():
                for child in sorted(path.iterdir()):
                    if child.suffix.lower() in core.IMAGE_EXTS:
                        self.set_image(child, from_disk=True)
                        return
                self.log("这个文件夹里没有图片。", "warn")
                return
        self.log("拖进来的东西不是图片文件。", "warn")

    def choose_image(self):
        chosen = filedialog.askopenfilename(title="选择头像图片", filetypes=IMAGE_FILETYPES)
        if chosen:
            self.set_image(Path(chosen), from_disk=True)

    def paste_image(self):
        if ImageGrab is None:
            messagebox.showerror(TITLE, "缺少 Pillow，无法读取剪贴板。")
            return
        try:
            data = ImageGrab.grabclipboard()
        except Exception as exc:
            self.log("读取剪贴板失败：%s" % exc, "err")
            return
        if data is None:
            self.log("剪贴板里没有图片。", "warn")
            return
        if isinstance(data, list):
            for item in data:
                path = Path(item)
                if path.is_file() and path.suffix.lower() in core.IMAGE_EXTS:
                    self.set_image(path, from_disk=True)
                    return
            self.log("剪贴板里是文件，但不是图片。", "warn")
            return
        self.set_image(data, from_disk=False)

    def set_image(self, payload, from_disk=True):
        if Image is None:
            messagebox.showerror(TITLE, "缺少 Pillow，无法预览图片。")
            return
        try:
            if from_disk:
                payload = Path(payload)
                with Image.open(payload) as im:
                    im.load()
                    image = im.convert("RGBA")
                original = image.size
                has_alpha = True
                name = payload.name
                self.image_path = payload
            else:
                image = payload.convert("RGBA")
                original = image.size
                has_alpha = True
                name = "剪贴板图片"
                self.image_path = None
        except Exception as exc:
            self.log("读不了这张图片：%s" % exc, "err")
            return

        self.preview_source = image
        self._render_preview(image)

        notes = ["%s（%d×%d）" % (name, original[0], original[1])]
        if original[0] != original[1]:
            notes.append("不是正方形，装进游戏时会自动居中留透明边")
        else:
            notes.append("正方形，比例最合适")
        self.image_info.configure(text="　".join(notes))
        self.log("已选择图片：%s" % notes[0], "info")

        if from_disk and self.image_path is not None:
            uid = core.parse_uid(self.image_path.stem)
            if uid and not self.uid_var.get():
                self.uid_var.set(uid)
                self.log("文件名正好是 ID，已经帮你填好了：%s" % uid, "ok")

    def _render_preview(self, image):
        box = PREVIEW_SIZE
        canvas = Image.new("RGBA", (box, box), (240, 240, 240, 255))
        work = image.copy()
        work.thumbnail((box, box), core.RESAMPLE)
        canvas.alpha_composite(work, ((box - work.width) // 2, (box - work.height) // 2))
        self.preview_image = ImageTk.PhotoImage(canvas)
        self.preview.configure(image=self.preview_image, text="", width=box, height=box)

    def clear_image(self):
        self.image_path = None
        self.preview_source = None
        self.preview_image = None
        self.preview.configure(
            image="",
            text="把图片拖到这里\n或点右边的按钮选择",
            width=24,
            height=9,
            fg="#888888",
        )
        self.image_info.configure(text="还没有选择图片")
        self.log("已清除图片。", "info")

    # ---------------------------------------------------------------- 安装

    def on_install(self):
        if self.busy:
            return
        pack = self.pack_dir()
        if not pack:
            messagebox.showwarning(TITLE, "先选好 FM26 的用户数据目录。")
            return
        raw_uid = self.uid_var.get().strip()
        try:
            uid = core.validate_uid(raw_uid)
        except ValueError as exc:
            messagebox.showwarning(TITLE, str(exc))
            return
        if self.preview_source is None:
            messagebox.showwarning(TITLE, "先选一张图片。")
            return

        image = self.preview_source.copy()
        source_name = self.image_path.name if self.image_path else "剪贴板图片"
        faces_root = core.faces_root_for(self.user_data_dir)

        self.set_busy(True)
        self.set_status("正在处理…")
        self.log("")
        self.log("开始安装：ID %s ← %s" % (uid, source_name), "info")
        self.save_settings(uid)

        thread = threading.Thread(
            target=self._install_worker, args=(image, uid, pack, faces_root), daemon=True
        )
        thread.start()

    def _install_worker(self, image, uid, pack, faces_root):
        temp_path = None
        try:
            if self.image_path is not None:
                source = self.image_path
            else:
                temp_dir = Path(os.environ.get("TEMP") or ".")
                temp_path = temp_dir / ("fm26_face_%s.png" % uid)
                image.save(temp_path, format="PNG")
                source = temp_path
            result, conflicts = run_install(
                source, uid, pack, size=DEFAULT_SIZE, faces_root=faces_root
            )
            self.queue.put(("done", result, conflicts))
        except Exception as exc:
            self.queue.put(("error", exc, None))
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _poll_queue(self):
        try:
            while True:
                kind, payload, extra = self.queue.get_nowait()
                if kind == "done":
                    self._on_success(payload, extra or [])
                else:
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _on_success(self, result, conflicts):
        self.set_busy(False)
        self.set_status("安装完成")
        self.log("已写入图片：%s" % result.png, "ok")
        with Image.open(result.png) as im:
            self.log("已处理成 %d×%d 透明 PNG" % im.size, "ok")
        self.log("config.xml 已更新，自定义头像共 %d 个" % result.total, "ok")

        for conflict in conflicts:
            self.log(
                "注意：%s 里已经有 ID %s 的头像，游戏可能仍显示那个包的图片。"
                % (conflict.parent.name, result.uid),
                "warn",
            )
            self.log("　　要么删掉那个包里的对应记录，要么换一个 ID 位置。", "warn")
        if not conflicts:
            self.log("没有发现其它头像包占用这个 ID。", "info")

        self.log("回游戏按 Shift+R 重载皮肤，就能看到新头像。", "ok")
        if not messagebox.askyesno(
            TITLE,
            "头像已装好：%s\n（自定义头像共 %d 个）\n\n现在打开头像文件夹看一眼吗？"
            % (result.uid, result.total),
        ):
            return
        self.open_pack_folder()

    def _on_error(self, exc):
        self.set_busy(False)
        self.set_status("出错了")
        self.log("安装失败：%s" % exc, "err")
        messagebox.showerror(TITLE, "安装失败：\n%s" % exc)

    # ---------------------------------------------------------------- 设置

    def save_settings(self, uid=None):
        data = dict(self.settings)
        if self.user_data_dir:
            data["game_dir"] = str(self.user_data_dir)
        if uid is None:
            uid = self.uid_var.get().strip()
        if uid:
            data["last_uid"] = uid
        self.settings = data
        core.save_settings(data)

    def run(self):
        self.root.mainloop()


def selftest(out_path=None):
    """无人工干预地建一遍窗口，用于打包后的冒烟检查。"""
    import json

    app = FaceAssistant()
    app.root.update_idletasks()
    app.root.update()
    info = {
        "ok": True,
        "dnd": bool(app.dnd_enabled),
        "game_dir": str(app.user_data_dir) if app.user_data_dir else None,
        "pack_dir": str(app.pack_dir()) if app.pack_dir() else None,
        "log_lines": len(app.log_text.get("1.0", "end").strip().splitlines()),
    }
    app.root.destroy()
    if out_path:
        Path(out_path).write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    safe_print(json.dumps(info, ensure_ascii=False))
    return info


def headless_install(image, uid, game_dir, out_path=None):
    """不开窗口跑一遍安装通路，给自动化和排查用。"""
    import json

    game_dir = Path(game_dir)
    pack = core.default_pack_dir(game_dir)
    result, conflicts = run_install(
        Path(image), uid, pack, faces_root=core.faces_root_for(game_dir)
    )
    info = {
        "ok": True,
        "uid": result.uid,
        "png": str(result.png),
        "config": str(result.config),
        "total": result.total,
        "conflicts": [str(item) for item in conflicts],
    }
    if out_path:
        Path(out_path).write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    safe_print(json.dumps(info, ensure_ascii=False))
    return info


def _arg_value(argv, name):
    if name not in argv:
        return None
    index = argv.index(name)
    return argv[index + 1] if index + 1 < len(argv) else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if "--headless-install" in argv:
            headless_install(
                _arg_value(argv, "--image"),
                _arg_value(argv, "--uid"),
                _arg_value(argv, "--game-dir"),
                _arg_value(argv, "--out"),
            )
            return 0
        if "--selftest" in argv:
            selftest(_arg_value(argv, "--selftest-out"))
            return 0
        FaceAssistant().run()
        return 0
    except Exception:
        detail = traceback.format_exc()
        write_error_log(detail)
        safe_print(detail)
        try:
            messagebox.showerror(
                TITLE,
                "程序启动出错。\n\n详情已写入：\n%s\n\n%s" % (log_path(), detail[-600:]),
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
