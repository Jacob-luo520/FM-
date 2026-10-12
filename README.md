# FM26 头像助手

给 FM26 里的球员加头像。界面版一次处理一张：放一张图片、填上球员 ID、点一下按钮，头像就进游戏了。

这个仓库提供两个程序：

- `FM26-Face-Assistant.exe` — 图形界面版，日常用这个（窗口标题是「FM26 头像助手」）
- `FM26-Face-Tool.exe` — 命令行 / 拖拽批量版，适合一次处理一堆图片

exe 本身没有放进仓库（体积偏大），到本仓库的 Releases 页面下载即可；也可以自己双击 `build_exe.bat` 重新生成。

## 界面版怎么用

1. 双击 `FM26-Face-Assistant.exe`
2. 看一眼顶部的"游戏目录"（会自动检测，不对就点"浏览…"，或从下拉框里换一个）
3. 选图片，三种方式随便挑：

   - 直接把图片拖进窗口
   - 点"选择图片…"
   - 截图后点"从剪贴板粘贴"

4. 填球员 ID（只填数字）。如果图片文件名本身就是 ID，会自动填好
5. 点"安装到游戏"
6. 回到游戏按 Shift+R 重载皮肤

头像装在 `<游戏目录>\graphics\faces\MyFaces\` 里，一张一张累积。工具只动这个自己管的文件夹，不会碰你其它头像包的配置文件。

如果日志里出现"别的头像包已经有这个 ID"的提醒，说明那个包会抢走显示：要么删掉那个包里对应 ID 的记录，要么换一个 ID。

## 游戏里怎么查球员 ID

`Preferences → Interface`，勾上 `Show Unique IDs`，然后打开球员档案页，名字下方那串数字就是。

## 游戏目录的小提醒

FM26 第一次启动之前，`文档\Sports Interactive\Football Manager 26` 这个目录还不存在，这时工具会检测到你机器上旧版本的目录（例如 `Football Manager 2024`）。如果还没启动过 FM26，先在游戏里进一次主菜单让它把目录生成出来。

## 命令行版怎么用

把装满头像图片的文件夹拖到 `FM26-Face-Tool.exe` 上松手，它会给整个文件夹生成 `config.xml` 和一份 `facepack-report.txt` 检查报告。

也可以在命令行里跑：

```
FM26-Face-Tool.exe "D:\faces"
FM26-Face-Tool.exe "D:\raw" --prepare "D:\ready"     统一裁剪成 250x250 再生成
```

| 参数 | 作用 |
| --- | --- |
| `folder` | 头像所在文件夹，省略时用 exe 所在文件夹 |
| `--prepare OUT_DIR` | 把图片统一裁剪成方形透明 PNG 后输出到新文件夹并生成 config.xml |
| `--size N` | 头像边长，默认 250 |
| `--dry-run` | 只检查，不写任何文件 |
| `--preload` | 在 config 里开启预加载 |
| `--no-backup` | 不备份已有的 config.xml |
| `--no-pause` | 跑完不暂停，适合脚本调用 |

## 命令行版会检查什么

- 文件名是不是纯数字 ID，不是的会被忽略并写进报告
- 有没有重复 ID（比如同名 png 和 jpg 同时存在），重复时优先保留 PNG
- 图片是不是 PNG、是不是正方形、尺寸对不对、有没有透明通道

这些问题不会阻止生成，游戏会自己缩放，只是显示效果可能不理想。

## 常见问题

**exe 被杀毒软件拦截**

PyInstaller 打包的单文件程序常被误报，加个信任即可。

**exe 第一次打开要等一两秒**

单文件版每次启动会先解压到临时目录，属于正常现象。

**装了头像但游戏里看不到**

按顺序检查：游戏里取消勾选 `Use caching to decrease page loading times`，按 Shift+R 重载皮肤；还不行就退出游戏删掉 `Football Manager 26\cache` 再进；再不行看日志里有没有"别的头像包已经占用该 ID"的提醒。

**球员的 ID 填错了**

头像会装到那个 ID 名下。重新装一次正确的 ID 即可，装错的可以在 `MyFaces` 文件夹里删掉对应的 `数字.png`，再打开界面版点一次"安装到游戏"刷新配置。

**新生成的随机球员（newgen）**

界面上照样能装，只是 newgen 的 ID 是游戏随机分配的，重开存档可能变。

## 源码结构

| 文件 | 作用 |
| --- | --- |
| `fm26_core.py` | 公共逻辑：ID 校验、图片规整、config 读写、游戏目录探测、冲突检查、设置读写 |
| `fm26_face_gui.py` | 图形界面 |
| `fm26_facepack.py` | 命令行版 |
| `tests/test_fm26_core.py` | 公共逻辑自测（15 项） |
| `tests/test_fm26_gui_flow.py` | 界面按钮背后那条通路自测（3 项） |
| `build_exe.bat` | 一键重新打包 |

## 排查与自动化入口

界面版带两个隐藏参数，出问题时用得上：

```
FM26-Face-Assistant.exe --selftest --selftest-out 结果.json
FM26-Face-Assistant.exe --headless-install --image 图片.png --uid 2000043406 --game-dir "D:\文档\Sports Interactive\Football Manager 26" --out 结果.json
```

界面启动失败时，程序旁边会生成 `fm26-error.log`，里面是报错详情。

## 重新打包

双击 `build_exe.bat`，它会装依赖、打包两个 exe，并跑一遍自测。需要本机装有 Python 3。
