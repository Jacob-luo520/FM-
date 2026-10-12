#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FM26 头像工具的公共逻辑。

这里放的是不依赖界面的部分：UID 校验、图片规整、config.xml 读写、
游戏目录探测、冲突检查、设置读写。命令行工具和图形界面都调用这里的函数。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

try:
    from PIL import Image
except Exception:  # pragma: no cover - 缺少 Pillow 时只跳过图片处理
    Image = None

RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS if Image is not None else None

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tga", ".tif", ".tiff"}
UID_RE = re.compile(r"^(\d{1,10})$")
CONFIG_NAME = "config.xml"
REPORT_NAME = "facepack-report.txt"
DEFAULT_SIZE = 250

# 工具自己在 graphics/faces 下使用的文件夹，不去碰别人的头像包
MANAGED_PACK_NAME = "MyFaces"
SETTINGS_ENV = "FM26FA_SETTINGS"
USER_DATA_PREFIX = "football manager"

# FM26 的用户数据目录叫 "Football Manager 26"，旧版本用四位年份
CURRENT_PACK_VERSION = 26

# 头像资源的两种查表路径：
#   真实球员  graphics/pictures/person/<UID>/portrait
#   随机人    graphics/pictures/person/r-<UID>/portrait
PORTRAIT_PATHS = (
    "graphics/pictures/person/{uid}/portrait",
    "graphics/pictures/person/r-{uid}/portrait",
)

# 头像包常见格式：散装文件夹里的 config.xml，以及打包成 .fmf 的整合包
PACK_FILE_SUFFIX = ".fmf"
PACK_SCAN_BYTES = 256 * 1024 * 1024
SCAN_CHUNK = 8 * 1024 * 1024


# ------------------------------------------------------------------ 基础

def parse_uid(stem: str) -> Optional[str]:
    match = UID_RE.match(str(stem).strip())
    return match.group(1) if match else None


def validate_uid(value: str) -> str:
    uid = parse_uid(value)
    if uid is None:
        raise ValueError("球员 ID 只能是 1 到 10 位数字，当前是：%r" % (value,))
    return uid


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def portrait_paths(uid: str) -> List[str]:
    """同一个 ID 需要同时写两条映射，覆盖真实球员和随机人两种查表方式。"""
    return [item.format(uid=uid) for item in PORTRAIT_PATHS]


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


# -------------------------------------------------------------- 图片处理

def normalize_image(src: Path, dst: Path, size: int = DEFAULT_SIZE) -> Tuple[int, int]:
    """把任意图片规整成方形透明 PNG，返回原始尺寸。"""
    if Image is None:
        raise RuntimeError("缺少 Pillow，无法处理图片")
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        original = im.size
        im = im.convert("RGBA")
        width, height = im.size
        if width <= 0 or height <= 0:
            raise ValueError("图片尺寸无效")
        scale = min(size / width, size / height)
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        if new_size != (width, height):
            im = im.resize(new_size, RESAMPLE)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(im, ((size - new_size[0]) // 2, (size - new_size[1]) // 2), im)
        canvas.save(dst, format="PNG", optimize=True)
    return original


def collect_images(root: Path, skip_dirs: Sequence[Path] = ()) -> List[Path]:
    root = Path(root)
    skip = [Path(item).resolve() for item in skip_dirs]
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if any(resolved == item or item in resolved.parents for item in skip):
            continue
        if path.name.lower() in (CONFIG_NAME, REPORT_NAME) or path.name.startswith("."):
            continue
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        found.append(path)
    return found


def inspect_image(path: Path, size: int = DEFAULT_SIZE) -> List[str]:
    """检查图片是否适合做头像，返回问题列表。"""
    if Image is None:
        return []
    try:
        with Image.open(path) as im:
            fmt = (im.format or "").lower()
            width, height = im.size
            has_alpha = ("A" in im.getbands()) or (im.mode == "P" and "transparency" in im.info)
    except Exception as exc:
        return ["图片无法读取：%s" % exc]

    problems = []
    if fmt != "png":
        problems.append("不是 PNG 格式（FM 只读取 PNG）")
    if width != height:
        problems.append("不是正方形（当前 %d×%d）" % (width, height))
    if size and (width != size or height != size):
        problems.append("尺寸不是 %d×%d（当前 %d×%d）" % (size, size, width, height))
    if not has_alpha:
        problems.append("没有透明通道（不会是抠图效果）")
    return problems


def pick_best(paths: Iterable[Path]) -> Path:
    def sort_key(path: Path):
        return (0 if path.suffix.lower() == ".png" else 1, len(path.name), str(path).lower())

    return sorted(paths, key=sort_key)[0]


# ---------------------------------------------------------- config 读写

def build_config(entries: Sequence[Tuple[str, str]], preload: bool = False) -> str:
    lines = [
        "<record>",
        '\t<boolean id="preload" value="%s"/>' % ("true" if preload else "false"),
        '\t<boolean id="amap" value="true"/>',
        '\t<list id="maps">',
    ]
    for uid, relative in entries:
        for target in portrait_paths(uid):
            lines.append(
                '\t\t<record from="%s" to="%s"/>' % (xml_escape(relative), target)
            )
    lines.append("\t</list>")
    lines.append("</record>")
    return "\n".join(lines) + "\n"


def pack_entries(pack_dir: Path) -> List[Tuple[str, str]]:
    """扫描一个头像文件夹，得到 (uid, 文件名) 列表。"""
    pack_dir = Path(pack_dir)
    entries = []
    if not pack_dir.is_dir():
        return entries
    for path in sorted(pack_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        uid = parse_uid(path.stem)
        if uid:
            entries.append((uid, path.stem))
    return sorted(entries, key=lambda item: int(item[0]))


def rebuild_config(pack_dir: Path, preload: bool = False) -> Tuple[int, Path]:
    """按文件夹里的 PNG 重建 config.xml，返回 (数量, 配置文件路径)。"""
    pack_dir = Path(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    entries = pack_entries(pack_dir)
    config_path = pack_dir / CONFIG_NAME
    write_text(config_path, build_config(entries, preload))
    return len(entries), config_path


# ---------------------------------------------------------- 游戏目录探测

def documents_dirs(
    extra_roots: Optional[Sequence[Path]] = None, include_default: bool = True
) -> List[Path]:
    """列出可能的"文档"目录，兼容 OneDrive 重定向。"""
    candidates: List[Path] = []
    for item in extra_roots or []:
        candidates.append(Path(item))
    if not include_default:
        return _existing_unique(candidates)

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Personal")
        candidates.append(Path(os.path.expandvars(value)))
    except Exception:
        pass

    home = Path.home()
    candidates += [
        home / "Documents",
        home / "OneDrive" / "Documents",
        home / "OneDrive" / "文档",
    ]
    return _existing_unique(candidates)


def _existing_unique(candidates: Sequence[Path]) -> List[Path]:
    result: List[Path] = []
    for item in candidates:
        try:
            resolved = Path(item).expanduser()
        except Exception:
            continue
        if resolved.is_dir() and resolved not in result:
            result.append(resolved)
    return result


def pack_version(name: str) -> Optional[int]:
    """从目录名里取出 FM 版本号。

    "Football Manager 26" 和 "Football Manager 2026" 都算 26，
    这样旧版本的 2024 不会被排到 26 前面。
    """
    numbers = re.findall(r"\d+", str(name))
    if not numbers:
        return None
    value = int(numbers[-1])
    if value >= 1900:
        value -= 2000
    return value


def user_data_dir_sort_key(path: Path):
    name = path.name.lower()
    version = pack_version(path.name)
    if version is None:
        return (1, 0, name)
    return (0, -version, name)


def find_game_dirs(
    extra_roots: Optional[Sequence[Path]] = None, include_default: bool = True
) -> List[Path]:
    """找到 Sports Interactive 下的各版本用户数据目录，新版在前。"""
    found: List[Path] = []
    for base in documents_dirs(extra_roots, include_default=include_default):
        si_root = base / "Sports Interactive"
        if not si_root.is_dir():
            continue
        try:
            children = list(si_root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and child.name.lower().startswith(USER_DATA_PREFIX):
                if child not in found:
                    found.append(child)
    return sorted(found, key=user_data_dir_sort_key)


def faces_root_for(user_data_dir: Path) -> Path:
    return Path(user_data_dir) / "graphics" / "faces"


def default_pack_dir(user_data_dir: Path) -> Path:
    return faces_root_for(user_data_dir) / MANAGED_PACK_NAME


def _file_contains(path: Path, needles: Sequence[bytes], head_bytes: int) -> bool:
    """在文件（或前 head_bytes 字节）里查找目标字符串，流式读取，避免整包读进内存。"""
    tail = max(len(item) for item in needles) - 1
    carry = b""
    remaining = head_bytes
    try:
        with open(path, "rb") as handle:
            while remaining > 0:
                block = handle.read(min(SCAN_CHUNK, remaining))
                if not block:
                    break
                remaining -= len(block)
                data = carry + block
                for needle in needles:
                    if needle in data:
                        return True
                carry = data[-tail:] if tail else b""
    except OSError:
        return False
    return False


def scan_conflicts(faces_root: Path, uid: str, ignore_dirs: Sequence[Path] = ()) -> List[Path]:
    """找出其它头像包里已经占用了这个 UID 的文件。

    既看散装的 config.xml，也看打包成 .fmf 的整合包（只扫开头部分）。
    """
    faces_root = Path(faces_root)
    if not faces_root.is_dir():
        return []
    ignored = [Path(item).resolve() for item in ignore_dirs]
    needles = [item.encode("utf-8") for item in portrait_paths(uid)]
    hits = []
    candidates = list(faces_root.rglob(CONFIG_NAME)) + list(
        faces_root.rglob("*" + PACK_FILE_SUFFIX)
    )
    for pack in sorted(candidates):
        try:
            resolved = pack.resolve()
        except OSError:
            continue
        if any(item == resolved.parent or item in resolved.parents for item in ignored):
            continue
        try:
            size = pack.stat().st_size
        except OSError:
            continue
        head = PACK_SCAN_BYTES if (pack.suffix.lower() == PACK_FILE_SUFFIX or size > 64 * 1024 * 1024) else size + 1
        if _file_contains(pack, needles, head):
            hits.append(pack)
    return hits


# ---------------------------------------------------------------- 安装

@dataclass
class InstallResult:
    uid: str
    png: Path
    config: Path
    total: int
    source: Path
    source_size: Tuple[int, int] = (0, 0)
    conflicts: List[Path] = field(default_factory=list)


def install_face(
    image_path: Path,
    uid: str,
    pack_dir: Path,
    size: int = DEFAULT_SIZE,
    preload: bool = False,
) -> InstallResult:
    """把一张图片装成某个球员的头像，并重建 config.xml。"""
    uid = validate_uid(uid)
    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError("找不到图片：%s" % image_path)

    pack_dir = Path(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    png = pack_dir / ("%s.png" % uid)
    original = normalize_image(image_path, png, size)
    total, config = rebuild_config(pack_dir, preload)
    return InstallResult(
        uid=uid,
        png=png,
        config=config,
        total=total,
        source=image_path,
        source_size=original,
    )


# ---------------------------------------------------------------- 设置

def settings_path(explicit: Optional[Path] = None) -> Path:
    if explicit:
        return Path(explicit)
    override = os.environ.get(SETTINGS_ENV)
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "FM26FaceAssistant" / "settings.json"


def load_settings(path: Optional[Path] = None) -> dict:
    target = settings_path(path)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data: dict, path: Optional[Path] = None) -> bool:
    target = settings_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
