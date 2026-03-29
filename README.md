# Apple Music Lyric

Apple Music Dynamic Lyrics  — 苹果音乐动态歌词

> 本软件是为了解决apple music 这么多年都没有动态歌词，以及没有歌词翻译的问题而开发的。

目前仅支持Windows系统。

---

## 特色功能

- 🎵 **自动检测播放内容及同步进度条** — 通过Windows 系统媒体传输控制（SMTC），自动识别 Apple Music 的歌曲以及当前播放曲目的进度。
- 🌐 **双歌词源** — 同时从网易云音乐和 QQ 音乐获取歌词，自动选择匹配度更高的结果
- 📝 **双语歌词** — 当歌词有翻译时，中文原词和译文同步显示

- 🔒 **锁定模式** — 一键锁定，窗口变为完全穿透，鼠标点击不影响下方操作
- ⚙️ **逐曲偏移校准** — 不同来源的歌词时间轴可能有偏差，支持鼠标滚轮快速微调每首歌的偏移量（±500ms / ±100ms with Ctrl）
- 📐 **多显示器支持** — 拖动窗口到其他显示器后，自动适配该显示器的分辨率和 DPI
- 🔍 **手动搜索绑定** — 如果自动匹配不到歌词，支持手动搜索并指定歌词
- 💾 **本地缓存** — 已获取的歌词自动缓存到本地，再次播放同一首歌时秒加载

---

## 快速开始

### 方式一：下载 EXE（推荐）

前往 GitHub release 页面，下载最新版本的 EXE 文件并运行。

> 无需安装 Python 环境，开箱即用。

首次运行后，会在 `文档/Apple Music Dynamic Lyrics/` 目录下自动生成配置文件和歌词缓存。

### 方式二：从源码运行

确保已安装 [uv](https://github.com/astral-sh/uv)（推荐）或 Python 3.13+。

```bash
# 使用 uv 运行（无需手动创建虚拟环境）
uv run python -m apple_music_lyric

# 或手动创建并激活虚拟环境后运行
uv venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv sync
python -m apple_music_lyric
```

### 方式三：打包为 EXE

```bash
uv pip install pyinstaller
uv run --no-project -m PyInstaller AppleMusicLyric.spec
```

打包产物输出到 `dist/AppleMusicLyric*.exe`。

---

## 使用指南

### 基本操作

| 操作 | 说明 |
|---|---|
| **拖动窗口** | 鼠标按住窗口任意位置拖动，调整歌词位置 |
| **滚轮调整时间偏移** | 滚动鼠标滚轮，以 500ms 为步长微调当前歌曲的歌词时间偏移 |
| **Ctrl + 滚轮** | 以 100ms 为步长精细调整偏移 |
| **双击窗口** | 打开手动搜索对话框 |
| **右键点击托盘图标** | 呼出设置菜单 |
| **Shift + 滚轮** | 调整歌词字体大小 |
| **右键锁定按钮 / 托盘锁定** | 切换锁定模式（鼠标穿透） |

### 锁定模式

**右键点击托盘图标 → 锁定歌词**。锁定后，歌词窗口变为完全透明、鼠标穿透，点击不会获得焦点，适合不需要操作歌词窗口时使用。右键托盘图标或再次点击锁定按钮即可解除锁定。

### 手动搜索

如果当前歌曲没有自动匹配到歌词，双击歌词窗口即可打开搜索面板，支持在网易云和 QQ 音乐之间切换标签页，预览歌词并手动选择。

### 设置面板

右键点击托盘图标 → **设置...**，打开设置面板，分为两个标签页：

#### 延迟设置

- **启用 Apple Music 默认延迟**：开关控制是否对 Apple Music 歌曲自动应用默认延迟
- **默认延迟 (ms)**：Apple Music 歌曲新检测时自动应用的延迟量（单位：毫秒），可在 0~10000 范围内调整

> 新检测到的 Apple Music 歌曲会自动使用此延迟值，之后你可以通过鼠标滚轮微调每首歌的偏移量，程序会自动保存。

#### 目录设置

可自定义以下文件的存放路径：

| 文件 | 说明 |
|---|---|
| **offsets.json** | 每首歌的歌词时间偏移记录 |
| **歌词缓存文件夹** | 歌词 LRC 文件本地缓存目录 |

默认路径为 `文档/Apple Music Dynamic Lyrics/`，点击「浏览...」可选择自定义位置。

### 手动写入歌词文件

如果自动匹配不到歌词，也可以手动将 LRC 文件放入歌词缓存文件夹，程序启动时会自动加载。

文件命名格式：

```
{title} - {artist}.lrc       # 原歌词（必须）
{title} - {artist}.tlyric   # 翻译歌词（可选）
```

其中 `{title}` 为歌曲名，`{artist}` 为艺人名。**注意：Apple Music 的 SMTC 返回的 artist 字段本身已包含专辑信息**（格式为「艺人名 — 专辑名」），拼接后文件名的典型结构为：

```
歌曲名 - 艺人名 — 专辑名.lrc
```

> 程序运行时会打印 SMTC 返回的完整字段，可在终端中直接查看作为文件名参考。路径中的特殊字符 `\` `/` `:` `*` `"` `<` `>` `|` 会被自动替换为 `_`。

![1774785218174](image/README/1774785218174.png)

在apple music的显示中，第一行为歌曲名，第二行为艺术家及专辑名


**示例：**

根据日志输出：

```
[MediaListener] Got properties: 'Elf' - 'Ado — Elf - Single' [...]
```

文件名应为：

```
Elf - Ado — Elf - Single.lrc
```

或：

```
心拍数♯0822 - Akie秋绘 — 冬氤。2016-17.lrc
```

LRC 文件格式示例（时间标签 `[mm:ss.xx]`）：

```lrc
[00:12.00] 看着你认真的眼神
[00:18.50] 所有的温柔都有了姓名
[00:24.80] 藏在眉间的那个字
[00:31.20] 是我此生写过最好的情诗
```

`tlyric` 翻译文件格式与 `lrc` 完全相同，只需将译文替换进文本部分，时间标签保持一致。

---

## 数据目录

程序首次运行时会自动在 Windows 文档文件夹中创建：

```
文档/
└── Apple Music Dynamic Lyrics/
    ├── settings.json      # 程序设置（宽度、延迟开关、默认延迟、路径配置）
    ├── offsets.json       # 每首歌的歌词偏移量
    └── lyrics_cache/      # 歌词 LRC 文件缓存
```

---


## 项目结构

```
apple_music_lyric/
├── src/
│   └── apple_music_lyric/
│       ├── __init__.py
│       ├── __main__.py      # 程序入口
│       ├── media_listener.py # Windows SMTC 监听（WinRT API）
│       ├── lyric_provider.py # 网易云 / QQ 音乐 API 客户端
│       └── lyric_parser.py   # LRC 时间标签解析器
├── pyproject.toml            # 项目依赖配置
├── AppleMusicLyric.spec     # PyInstaller 打包配置
├── icon.png / icon.ico      # 程序图标
└── .github/workflows/build.yml # GitHub Actions 自动编译
```

> `settings.json`、`offsets.json`、`lyrics_cache/` 不在程序目录中，首次运行后自动创建于 `文档/Apple Music Dynamic Lyrics/` 下。

---

## 技术栈

| 技术 | 用途 |
|---|---|
| **uv** | Python 环境管理（依赖解析、虚拟环境、打包） |
| **PySide6** | Qt6 GUI 框架，负责悬浮窗渲染、拖拽、系统托盘 |
| **winrt-windows-media-control** | Windows Runtime API，读取系统媒体会话信息 |
| **httpx** | 异步 HTTP 客户端，用于歌词 API 请求 |
| **pycryptodome** | AES 加密，用于网易云音乐 API 签名 |
| **PyInstaller** | 将程序打包为单文件 EXE（通过 `uv sync --extra build` 安装） |

---

## 许可证

本项目采用 **GNU General Public License v3.0**（GNU GPL v3）开源，并附加以下条款：

- **必须署名**：传播或再分发时，必须标注原作者 **IcarusAegis** 及项目地址
- **禁止商业使用**：严禁出售、出租或作为商业产品的一部分收费
- **相同方式共享**：修改后再发布必须采用相同许可证

详细条款请参阅 [LICENSE](LICENSE) 文件。

> **第三方组件许可证**
>
> | 组件 | 许可证 |
> |------|--------|
> | PySide6 (Qt6) | LGPL v3 |
> | httpx | BSD 3-Clause |
> | pycryptodome | BSD 2-Clause / Public Domain |
> | winrt-windows-media-control | MIT |

---

# 其他
欢迎提 Issue 。
感谢 Linux.do 社区推动。