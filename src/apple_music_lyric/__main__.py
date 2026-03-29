import sys
import os
import json
import asyncio
from typing import List

from PySide6.QtCore import Qt, QThread, Signal, QPoint, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QFont, QColor, QPen, QBrush, QAction, QIcon, QPixmap, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QLabel, QTextEdit, QTabWidget, QInputDialog, QGroupBox, QSpinBox,
    QCheckBox, QFileDialog, QMessageBox, QFormLayout
)

from apple_music_lyric.media_listener import MediaListener
from apple_music_lyric.lyric_provider import LyricProvider
from apple_music_lyric.lyric_parser import LyricParser, LyricLine


# ---------------------------------------------------------------------------
# 配置管理器：统一管理所有持久化路径和延迟设置
# ---------------------------------------------------------------------------

class SettingsManager:
    """统一管理程序配置（路径、延迟开关、默认延迟值）。"""

    _instance = None

    @classmethod
    def instance(cls) -> "SettingsManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._settings: dict = {}
        self._settings_file: str = ""
        self._loaded: bool = False
        self._data_dir_path: str = ""  # 冻结的数据目录，不随 settings_file 位置变化

    # ---------- 公开属性 ----------

    @property
    def width_percentage(self) -> int:
        return self._settings.get("width_percentage", 60)

    @width_percentage.setter
    def width_percentage(self, v: int):
        self._settings["width_percentage"] = v
        self._save()

    @property
    def apple_delay_enabled(self) -> bool:
        return self._settings.get("apple_delay_enabled", True)

    @apple_delay_enabled.setter
    def apple_delay_enabled(self, v: bool):
        self._settings["apple_delay_enabled"] = v
        self._save()

    @property
    def apple_delay_ms(self) -> int:
        return self._settings.get("apple_delay_ms", 1000)

    @apple_delay_ms.setter
    def apple_delay_ms(self, v: int):
        self._settings["apple_delay_ms"] = v
        self._save()

    @property
    def offsets_file(self) -> str:
        return self._settings.get("offsets_file", "")

    @offsets_file.setter
    def offsets_file(self, v: str):
        self._settings["offsets_file"] = v
        self._save()

    @property
    def cache_dir(self) -> str:
        return self._settings.get("cache_dir", "")

    @cache_dir.setter
    def cache_dir(self, v: str):
        self._settings["cache_dir"] = v
        self._save()

    # ---------- 解析后的绝对路径 ----------

    def get_offsets_path(self) -> str:
        path = self.offsets_file
        if path:
            return os.path.abspath(path)
        # 用冻结的 _data_dir_path，不再用 _data_dir()
        return os.path.join(self._data_dir_path, "offsets.json")

    def get_cache_dir(self) -> str:
        path = self.cache_dir
        if path:
            return os.path.abspath(path)
        # 用冻结的 _data_dir_path，不再用 _data_dir()
        d = os.path.join(self._data_dir_path, "lyrics_cache")
        os.makedirs(d, exist_ok=True)
        return d

    # ---------- 初始化与加载 ----------

    def init(self, settings_file: str):
        """
        设置配置文件路径并加载。
        若文件不存在，则在 Documents/Apple Music Dynamic Lyrics/ 下创建默认配置。
        """
        self._settings_file = settings_file
        # 冻结数据目录，始终指向 Documents 下的固定位置，不受 settings_file 路径影响
        self._data_dir_path = os.path.join(
            os.path.expanduser("~"), "Documents", "Apple Music Dynamic Lyrics"
        )
        os.makedirs(self._data_dir_path, exist_ok=True)
        self._load()

    def _data_dir(self) -> str:
        """返回数据目录（配置文件所在目录）。"""
        return os.path.dirname(os.path.abspath(self._settings_file))

    def _load(self):
        if os.path.exists(self._settings_file):
            try:
                with open(self._settings_file, "r", encoding="utf-8") as f:
                    self._settings = json.load(f)
            except Exception:
                self._settings = {}
        else:
            self._settings = self._default_settings()
            self._save()

    def _default_settings(self) -> dict:
        """生成默认配置（offsets_file 和 cache_dir 由 getters 动态计算）。"""
        return {
            "width_percentage": 60,
            "apple_delay_enabled": True,
            "apple_delay_ms": 1000,
            "offsets_file": "",   # 由 get_offsets_path() 动态计算
            "cache_dir": "",      # 由 get_cache_dir() 动态计算
        }

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._settings_file), exist_ok=True)
            with open(self._settings_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[SettingsManager] 保存配置失败: {e}")


# ---------------------------------------------------------------------------
# 后台工作线程
# ---------------------------------------------------------------------------

class MediaWorker(QThread):
    songChanged = Signal(str, str, str)
    lyricsReady = Signal(list)   # List[LyricLine]
    positionChanged = Signal(int)
    playbackStateChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self.listener = MediaListener()
        self.provider = LyricProvider()
        self.parser = LyricParser()
        self.running = True
        self.current_fetch_task = None

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self.async_run())
        except Exception as e:
            print(f"Worker Error: {e}")

    async def async_run(self):
        self.listener.on_song_changed = self._on_song_changed
        self.listener.on_position_changed = lambda pos: self.positionChanged.emit(pos)
        self.listener.on_playback_state_changed = lambda state: self.playbackStateChanged.emit(state)

        await self.listener.start()

        while self.running:
            await asyncio.sleep(1)

        await self.provider.close()

    def _on_song_changed(self, title: str, artist: str, platform: str = "Unknown"):
        self.songChanged.emit(title, artist, platform)

        if self.current_fetch_task and not self.current_fetch_task.done():
            self.current_fetch_task.cancel()

        if title and artist:
            self.current_fetch_task = asyncio.create_task(self.fetch_lyrics(title, artist))
        else:
            self.lyricsReady.emit([])

    async def fetch_lyrics(self, title: str, artist: str):
        try:
            print(f"[Main] Starting fetch for {title} - {artist}")
            import re
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
            safe_artist = re.sub(r'[\\/:*?"<>|]', '_', artist)

            cache_dir = SettingsManager.instance().get_cache_dir()
            os.makedirs(cache_dir, exist_ok=True)
            cache_lrc_path = os.path.join(cache_dir, f"{safe_title} - {safe_artist}.lrc")
            cache_tlyric_path = os.path.join(cache_dir, f"{safe_title} - {safe_artist}.tlyric")

            lrc_text = ""
            tlyric_text = ""

            if os.path.exists(cache_lrc_path):
                try:
                    with open(cache_lrc_path, 'r', encoding='utf-8') as f:
                        lrc_text = f.read()
                    if os.path.exists(cache_tlyric_path):
                        with open(cache_tlyric_path, 'r', encoding='utf-8') as f:
                            tlyric_text = f.read()
                    print(f"[Main] Loaded lyrics from cache: {cache_lrc_path}")
                except Exception as e:
                    print(f"[Main] Cache read error: {e}")

            if not lrc_text:
                raw_lyrics = await self.provider.fetch_lyrics_for_song(title, artist)
                lrc_text = raw_lyrics.get("lrc", "")
                tlyric_text = raw_lyrics.get("tlyric", "")

                if lrc_text:
                    try:
                        with open(cache_lrc_path, 'w', encoding='utf-8') as f:
                            f.write(lrc_text)
                        if tlyric_text:
                            with open(cache_tlyric_path, 'w', encoding='utf-8') as f:
                                f.write(tlyric_text)
                    except Exception:
                        pass

            parsed_lines = self.parser.parse(lrc_text, tlyric_text)

            print(f"[Main] Fetched {len(parsed_lines)} lines.")
            if parsed_lines:
                for idx, line in enumerate(parsed_lines[:5]):
                    print(f"  Line {idx}: {line}")

            self.lyricsReady.emit(parsed_lines)
        except Exception as e:
            print(f"[Main] Fetch lyrics error: {e}")
            import traceback
            traceback.print_exc()
            self.lyricsReady.emit([])

    async def fetch_and_bind_lyrics(self, title: str, artist: str, song_id: str):
        print(f"[Main] Manually binding song ID: {song_id}")
        raw_lyrics = await self.provider.get_lyric(song_id)

        import re
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
        safe_artist = re.sub(r'[\\/:*?"<>|]', '_', artist)

        cache_dir = SettingsManager.instance().get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        cache_lrc_path = os.path.join(cache_dir, f"{safe_title} - {safe_artist}.lrc")
        cache_tlyric_path = os.path.join(cache_dir, f"{safe_title} - {safe_artist}.tlyric")

        lrc_text = raw_lyrics.get("lrc", "")
        tlyric_text = raw_lyrics.get("tlyric", "")

        if lrc_text:
            try:
                with open(cache_lrc_path, 'w', encoding='utf-8') as f:
                    f.write(lrc_text)
                if tlyric_text:
                    with open(cache_tlyric_path, 'w', encoding='utf-8') as f:
                        f.write(tlyric_text)
            except Exception as e:
                print("Write manual cache error:", e)

        parsed_lines = self.parser.parse(lrc_text, tlyric_text)
        self.lyricsReady.emit(parsed_lines)

    def stop(self):
        self.running = False


# ---------------------------------------------------------------------------
# 桌面歌词悬浮窗
# ---------------------------------------------------------------------------

class DesktopLyricWindow(QWidget):
    searchRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_OpaquePaintEvent)  # 防止系统绘制默认背景
        self.setStyleSheet("background: transparent; border: none;")  # 确保无边框

        self._sm = SettingsManager.instance()
        self.width_percentage = self._sm.width_percentage

        self.current_screen = QApplication.primaryScreen()
        self.update_window_width(center=True)

        self.lyrics: List[LyricLine] = []
        self.current_pos_ms = 0

        # 歌曲状态
        self.current_title = ""
        self.current_artist = ""
        self.current_platform = "Unknown"
        self.playback_state = "Stopped"

        # 歌词偏移管理
        self.lyric_offset_ms = 0
        self.offsets_cache: dict = {}
        self._load_offsets()

        # 字体配置
        self.font_size_main = 32
        self.font_size_trans = 20
        self._update_fonts()

    def _update_fonts(self):
        self.font_main = QFont("Microsoft YaHei", self.font_size_main, QFont.Bold)
        self.font_trans = QFont("Microsoft YaHei", self.font_size_trans, QFont.Normal)
        # 拖拽状态
        self.drag_pos = QPoint()
        self.is_hovered = False
        self.locked = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(50)

    def set_width_percentage(self, pct: int):
        if 10 <= pct <= 100:
            self.width_percentage = pct
            self._sm.width_percentage = pct
            self.update_window_width(center=True)

    def update_window_width(self, center=False):
        try:
            if not getattr(self, "current_screen", None):
                self.current_screen = QApplication.primaryScreen()

            screen_geom = self.current_screen.geometry()
            target_width = int(screen_geom.width() * (self.width_percentage / 100.0))

            self.resize(target_width, 260)

            if center:
                x = screen_geom.x() + (screen_geom.width() - self.width()) // 2
                y = screen_geom.y() + screen_geom.height() - self.height() - 150
                self.move(x, y)
        except Exception:
            self.resize(int(1600 * (self.width_percentage / 100.0)), 260)

    def moveEvent(self, event):
        super().moveEvent(event)
        try:
            if hasattr(self, 'current_screen'):
                new_screen = QApplication.screenAt(self.geometry().center())
                if new_screen and new_screen != self.current_screen:
                    self.current_screen = new_screen
                    self.update_window_width(center=False)
        except Exception:
            pass

    def toggle_locked(self, locked: bool):
        self.locked = locked
        if locked:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                | Qt.Tool | Qt.WindowTransparentForInput
            )
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            )

        self.show()
        self.raise_()

        # 强制置顶，防止重建窗口后失去 Z-order
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
        except Exception:
            pass

        self.update()

    def _load_offsets(self):
        # 防御性初始化：确保 SettingsManager 已 init
        if not self._sm._settings_file:
            default_path = os.path.join(
                os.path.expanduser("~"), "Documents",
                "Apple Music Dynamic Lyrics", "settings.json"
            )
            self._sm.init(default_path)
        offsets_path = self._sm.get_offsets_path()
        if os.path.exists(offsets_path):
            try:
                with open(offsets_path, 'r', encoding='utf-8') as f:
                    self.offsets_cache = json.load(f)
            except Exception:
                self.offsets_cache = {}

    def _save_offset(self):
        if not self.current_title:
            return
        key = f"[{self.current_platform}] {self.current_title} - {self.current_artist}"
        self.offsets_cache[key] = self.lyric_offset_ms
        try:
            offsets_path = self._sm.get_offsets_path()
            os.makedirs(os.path.dirname(offsets_path), exist_ok=True)
            with open(offsets_path, 'w', encoding='utf-8') as f:
                json.dump(self.offsets_cache, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def update_song(self, title: str, artist: str, platform: str = "Unknown"):
        self.current_title = title
        self.current_artist = artist
        self.current_platform = platform
        self.lyrics = []

        if title:
            key = f"[{platform}] {title} - {artist}"
            if key not in self.offsets_cache:
                # 从 SettingsManager 读取延迟配置
                if "apple" in platform.lower() or "applemusic" in platform.lower():
                    if self._sm.apple_delay_enabled:
                        self.lyric_offset_ms = self._sm.apple_delay_ms
                    else:
                        self.lyric_offset_ms = 0
                else:
                    self.lyric_offset_ms = 0
                self._save_offset()
            else:
                self.lyric_offset_ms = self.offsets_cache[key]
        else:
            self.lyric_offset_ms = 0

        self.update()

    def update_lyrics(self, lyrics: List[LyricLine]):
        self.lyrics = lyrics
        if not self.lyrics:
            self.lyrics = [LyricLine(0, f"未找到歌词: {self.current_title}")]
        self.update()

    def update_position(self, pos_ms: int):
        self.current_pos_ms = pos_ms

    def update_playback_state(self, state: str):
        self.playback_state = state
        self.update()

    def get_current_lyric_index(self) -> int:
        if not self.lyrics:
            return -1

        effective_time = self.current_pos_ms + self.lyric_offset_ms
        current_idx = -1
        for i in range(len(self.lyrics)):
            if effective_time >= self.lyrics[i].time_ms:
                current_idx = i
            else:
                break
        return current_idx

    def paintEvent(self, event):
        # 始终用完全透明色清除背景，防止失焦时出现残留边框
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        if self.playback_state == "Stopped" or (not self.current_title):
            painter.end()
            return

        painter.setRenderHint(QPainter.Antialiasing)

        current_idx = self.get_current_lyric_index()

        # 悬停时显示操作提示
        if not self.locked and self.is_hovered:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
            painter.setPen(QPen(Qt.white))
            painter.setFont(QFont("Microsoft YaHei", max(8, self.font_size_trans // 2)))
            painter.drawText(
                self.rect(), Qt.AlignTop | Qt.AlignLeft,
                f"拖拽移动 | Shift滚轮字号 | 滚轮+/-500ms(Ctrl 100ms) | 当前延迟:{self.lyric_offset_ms}ms | 托盘可锁定"
            )

        if not self.lyrics or current_idx == -1:
            main_text = "正在搜索歌词..." if not self.lyrics else "..."
            self._draw_text(painter, main_text, self.font_main, 0, 130,
                            QColor(255, 255, 255), QColor(20, 20, 20, 220), 4)
            painter.end()
            return

        prev_line = self.lyrics[current_idx - 1] if current_idx > 0 else None
        curr_line = self.lyrics[current_idx]
        next_line = self.lyrics[current_idx + 1] if current_idx < len(self.lyrics) - 1 else None

        if prev_line:
            self._draw_text(painter, prev_line.text, self.font_trans, 0, 50,
                            QColor(200, 200, 200, 180), QColor(20, 20, 20, 120), 2)

        self._draw_text(painter, curr_line.text, self.font_main, 0, 110,
                        QColor(255, 255, 255), QColor(20, 20, 20, 220), 4)
        if curr_line.translation:
            self._draw_text(painter, curr_line.translation, self.font_trans, 0, 160,
                            QColor(230, 230, 230), QColor(20, 20, 20, 220), 3)

        if next_line:
            y_offset = 210 if curr_line.translation else 170
            self._draw_text(painter, next_line.text, self.font_trans, 0, y_offset,
                            QColor(200, 200, 200, 180), QColor(20, 20, 20, 120), 2)

        painter.end()

    def _draw_text(self, painter: QPainter, text: str, font: QFont, x: int, y: int,
                   color_fill: QColor, color_outline: QColor, outline_width: int):
        if not text:
            return

        actual_font = QFont(font)
        fm = QFontMetrics(actual_font)
        max_width = self.width() - 40

        size = actual_font.pointSize()
        while size > 8 and fm.horizontalAdvance(text) > max_width:
            size -= 1
            actual_font.setPointSize(size)
            fm = QFontMetrics(actual_font)

        path = QPainterPath()
        path.addText(x, y, actual_font, text)

        rect = path.boundingRect()
        offset_x = (self.width() - rect.width()) / 2 - rect.x()
        path.translate(offset_x, 0)

        painter.setPen(QPen(color_outline, outline_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color_fill))
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if not self.locked and event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if not self.locked and event.button() == Qt.LeftButton:
            self.searchRequested.emit()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.locked and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        if self.locked:
            return

        delta = event.angleDelta().y()

        # Shift + 滚轮：字体缩放
        if event.modifiers() & Qt.ShiftModifier:
            if delta > 0:
                self.font_size_main += 2
                self.font_size_trans += 1
            elif delta < 0:
                self.font_size_main = max(10, self.font_size_main - 2)
                self.font_size_trans = max(6, self.font_size_trans - 1)
            self._update_fonts()
            self.update()
            event.accept()
            return

        # 普通 / Ctrl + 滚轮：调整时间偏移
        step_ms = 100 if event.modifiers() & Qt.ControlModifier else 500
        if delta > 0:
            self.lyric_offset_ms += step_ms
        elif delta < 0:
            self.lyric_offset_ms -= step_ms

        self._save_offset()
        self.update()
        event.accept()


# ---------------------------------------------------------------------------
# 手动搜索对话框
# ---------------------------------------------------------------------------

class ManualSearchDialog(QDialog):
    def __init__(self, worker: MediaWorker, title: str, artist: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动搜索并绑定歌词")
        self.resize(800, 500)
        self.worker = worker

        main_layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(f"{title} {artist}".strip())
        self.search_btn = QPushButton("搜索")
        search_layout.addWidget(QLabel("搜索关键字:"))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        main_layout.addLayout(search_layout)

        content_layout = QHBoxLayout()

        self.tab_widget = QTabWidget()
        self.tab_widget.setMinimumWidth(350)
        self.netease_list = QListWidget()
        self.qq_list = QListWidget()
        self.tab_widget.addTab(self.netease_list, "网易云音乐 Ex")
        self.tab_widget.addTab(self.qq_list, "QQ 音乐 Ex")

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText("选择左侧歌曲以预览歌词...")

        content_layout.addWidget(self.tab_widget, stretch=1)
        content_layout.addWidget(self.preview_text, stretch=1)
        main_layout.addLayout(content_layout)

        self.bind_btn = QPushButton("绑定并更新")
        self.bind_btn.setEnabled(False)
        main_layout.addWidget(self.bind_btn)

        self.search_btn.clicked.connect(self._do_search)
        self.netease_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.qq_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.bind_btn.clicked.connect(self.accept)

        self.selected_song_id = None
        self.results = {}

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._check_results)
        self._future = None

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._check_preview)
        self._preview_future = None

    def _do_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中...")
        self.netease_list.clear()
        self.qq_list.clear()

        self._future = asyncio.run_coroutine_threadsafe(
            self.worker.provider.search_songs_list(query, 20),
            self.worker._loop
        )
        self.poll_timer.start(100)

    def _check_results(self):
        if self._future and self._future.done():
            self.poll_timer.stop()
            self.search_btn.setEnabled(True)
            self.search_btn.setText("搜索")
            try:
                self.results = self._future.result()

                def _populate_list(list_widget, songs):
                    for song in songs:
                        name = song.get("name", "Unknown")
                        artists = ", ".join([a.get("name", "") for a in song.get("artists", [])])
                        album = song.get("album", {}).get("name", "")
                        duration = song.get("duration", 0)
                        mins, secs = divmod(duration // 1000, 60)
                        item_text = f"{name} - {artists} [{album}] ({mins}:{secs:02d})"
                        item = QListWidgetItem(item_text)
                        item.setData(Qt.UserRole, song.get("id"))
                        list_widget.addItem(item)

                _populate_list(self.netease_list, self.results.get("netease", []))
                _populate_list(self.qq_list, self.results.get("qq", []))

            except Exception as e:
                print(f"Error fetching search results: {e}")

    def _on_tab_changed(self):
        self._on_selection_changed()

    def _on_selection_changed(self):
        current_list = self.netease_list if self.tab_widget.currentIndex() == 0 else self.qq_list
        selected = current_list.selectedItems()
        if selected:
            self.selected_song_id = selected[0].data(Qt.UserRole)
            self.bind_btn.setEnabled(True)
            self.preview_text.setText("加载预览中...")

            self._preview_future = asyncio.run_coroutine_threadsafe(
                self.worker.provider.get_lyric(self.selected_song_id),
                self.worker._loop
            )
            self.preview_timer.start(100)
        else:
            self.selected_song_id = None
            self.bind_btn.setEnabled(False)
            self.preview_text.clear()

    def _check_preview(self):
        if self._preview_future and self._preview_future.done():
            self.preview_timer.stop()
            try:
                raw_lyrics = self._preview_future.result()
                lrc_text = raw_lyrics.get("lrc", "")
                tlyric_text = raw_lyrics.get("tlyric", "")
                preview_content = "暂无歌词"
                if lrc_text:
                    preview_content = "[原词]\n" + lrc_text
                if tlyric_text:
                    preview_content += "\n\n[翻译]\n" + tlyric_text
                self.preview_text.setPlainText(preview_content)
            except Exception as e:
                self.preview_text.setPlainText(f"获取预览失败: {e}")


class AboutDialog(QDialog):
    """关于对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        # 图标
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(255, 60, 100))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 60, 60)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 28, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "L")
        painter.end()
        icon_label = QLabel()
        icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        # 标题
        title_label = QLabel("Apple Music 桌面歌词")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 版本
        version_label = QLabel("版本 0.1.0")
        version_label.setStyleSheet("color: gray; font-size: 13px;")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        layout.addSpacing(10)

        # 作者
        author_label = QLabel("作者：IcarusAegis")
        author_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(author_label)

        # 联系方式
        contact_label = QLabel("问题反馈：GitHub Issue 或邮箱 icarusaegis-liu@qq.com")
        contact_label.setAlignment(Qt.AlignCenter)
        contact_label.setStyleSheet("color: gray; font-size: 12px;")
        contact_label.setWordWrap(True)
        layout.addWidget(contact_label)

        layout.addSpacing(20)

        # 关闭按钮
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


# ---------------------------------------------------------------------------
# 设置对话框
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """托盘右键「设置...」呼出的配置面板。"""

    def __init__(self, sm: SettingsManager, parent=None):
        super().__init__(parent)
        self._sm = sm
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Tab 1：延迟设置 ---
        tab_widget = QTabWidget()
        delay_tab = QWidget()
        delay_layout = QVBoxLayout(delay_tab)

        # Apple Music 延迟开关
        delay_grp = QGroupBox("Apple Music 歌词延迟补偿")
        delay_grp_layout = QVBoxLayout(delay_grp)

        self.cb_delay = QCheckBox("启用 Apple Music 默认延迟")
        self.cb_delay.setChecked(self._sm.apple_delay_enabled)
        delay_grp_layout.addWidget(self.cb_delay)

        delay_input_layout = QHBoxLayout()
        delay_input_layout.addWidget(QLabel("默认延迟 (ms):"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 10000)
        self.spin_delay.setSingleStep(100)
        self.spin_delay.setValue(self._sm.apple_delay_ms)
        self.spin_delay.setEnabled(self._sm.apple_delay_enabled)
        delay_input_layout.addWidget(self.spin_delay)
        delay_input_layout.addStretch()
        delay_grp_layout.addLayout(delay_input_layout)

        hint = QLabel(
            "提示：不同来源的歌词时间轴可能存在差异，可在悬浮窗上通过鼠标滚轮微调每首歌的偏移量。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 12px;")
        delay_grp_layout.addWidget(hint)

        delay_layout.addWidget(delay_grp)
        delay_layout.addStretch()

        # --- Tab 2：目录设置 ---
        dir_tab = QWidget()
        dir_layout = QVBoxLayout(dir_tab)

        dir_grp = QGroupBox("数据目录")
        dir_grp_layout = QFormLayout(dir_grp)

        # offsets.json 路径
        offsets_layout = QHBoxLayout()
        self.le_offsets = QLineEdit(self._sm.offsets_file)
        self.le_offsets.setReadOnly(True)
        btn_offsets = QPushButton("浏览...")
        btn_offsets.clicked.connect(self._browse_offsets)
        offsets_layout.addWidget(self.le_offsets)
        offsets_layout.addWidget(btn_offsets)
        dir_grp_layout.addRow("offsets.json 路径:", offsets_layout)

        # 歌词缓存目录
        cache_layout = QHBoxLayout()
        self.le_cache = QLineEdit(self._sm.cache_dir)
        self.le_cache.setReadOnly(True)
        btn_cache = QPushButton("浏览...")
        btn_cache.clicked.connect(self._browse_cache)
        cache_layout.addWidget(self.le_cache)
        cache_layout.addWidget(btn_cache)
        dir_grp_layout.addRow("歌词缓存文件夹:", cache_layout)

        dir_hint = QLabel(
            "提示：修改路径后，程序将把数据写入新位置。"
            "旧数据不会自动迁移，需手动复制。"
        )
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet("color: gray; font-size: 12px;")
        dir_grp_layout.addRow("", dir_hint)

        dir_layout.addWidget(dir_grp)
        dir_layout.addStretch()

        # --- Tab 3：关于 ---
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setAlignment(Qt.AlignCenter)

        # 图标
        pixmap_about = QPixmap(64, 64)
        pixmap_about.fill(Qt.transparent)
        painter_about = QPainter(pixmap_about)
        painter_about.setRenderHint(QPainter.Antialiasing)
        painter_about.setBrush(QColor(255, 60, 100))
        painter_about.setPen(Qt.NoPen)
        painter_about.drawEllipse(2, 2, 60, 60)
        painter_about.setPen(QColor(255, 255, 255))
        painter_about.setFont(QFont("Arial", 28, QFont.Bold))
        painter_about.drawText(pixmap_about.rect(), Qt.AlignCenter, "L")
        painter_about.end()
        icon_about_label = QLabel()
        icon_about_label.setPixmap(pixmap_about)
        icon_about_label.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(icon_about_label)

        title_about = QLabel("Apple Music 桌面歌词")
        title_about.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_about.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(title_about)

        version_about = QLabel("版本 1.0.2")
        version_about.setStyleSheet("color: gray; font-size: 13px;")
        version_about.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(version_about)

        about_layout.addSpacing(10)

        author_about = QLabel("作者：IcarusAegis")
        author_about.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(author_about)

        contact_about = QLabel("问题反馈：GitHub Issue 或邮箱：icarusaegis-liu@qq.com")
        contact_about.setAlignment(Qt.AlignCenter)
        contact_about.setStyleSheet("color: gray; font-size: 12px;")
        contact_about.setWordWrap(True)
        about_layout.addWidget(contact_about)

        about_layout.addStretch()

        # --- 组装 Tab ---
        tab_widget.addTab(delay_tab, "延迟设置")
        tab_widget.addTab(dir_tab, "目录设置")
        tab_widget.addTab(about_tab, "关于")
        layout.addWidget(tab_widget)

        # --- 按钮行 ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        # 联动：开关 → 延迟输入框
        self.cb_delay.toggled.connect(self.spin_delay.setEnabled)

    def _browse_offsets(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "选择 offsets.json 保存位置",
            self._sm.offsets_file or self._sm._data_dir(),
            "JSON Files (*.json)"
        )
        if path:
            self.le_offsets.setText(path)

    def _browse_cache(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择歌词缓存文件夹",
            self._sm.cache_dir or self._sm._data_dir()
        )
        if path:
            self.le_cache.setText(path)

    def _on_ok(self):
        # 保存延迟设置
        self._sm.apple_delay_enabled = self.cb_delay.isChecked()
        self._sm.apple_delay_ms = self.spin_delay.value()

        # 保存路径（允许留空表示使用默认值）
        offsets_text = self.le_offsets.text().strip()
        cache_text = self.le_cache.text().strip()

        # 如果用户选择的路径与默认值相同，清空（回到默认值路径）
        default_offsets = os.path.join(
            os.path.join(os.path.expanduser("~"), "Documents"),
            "Apple Music Dynamic Lyrics", "offsets.json"
        )
        default_cache = os.path.join(
            os.path.join(os.path.expanduser("~"), "Documents"),
            "Apple Music Dynamic Lyrics", "lyrics_cache"
        )

        self._sm.offsets_file = offsets_text if offsets_text != default_offsets else ""
        self._sm.cache_dir = cache_text if cache_text != default_cache else ""

        QMessageBox.information(self, "设置", "设置已保存，部分更改（如偏移量）将在下次播放时生效。")
        self.accept()


# ---------------------------------------------------------------------------
# 程序入口
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 初始化配置管理器
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    default_settings_path = os.path.join(docs, "Apple Music Dynamic Lyrics", "settings.json")
    SettingsManager.instance().init(default_settings_path)

    window = DesktopLyricWindow()
    window.show()

    worker = MediaWorker()
    worker.songChanged.connect(window.update_song)
    worker.lyricsReady.connect(window.update_lyrics)
    worker.positionChanged.connect(window.update_position)
    worker.playbackStateChanged.connect(window.update_playback_state)
    worker.start()

    # ---------- 托盘图标 ----------
    tray = QSystemTrayIcon()
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(255, 60, 100))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setPen(QColor(255, 255, 255))
    painter.setFont(QFont("Arial", 16, QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "L")
    painter.end()

    tray.setIcon(QIcon(pixmap))
    tray.setToolTip("Apple Music 桌面歌词")

    sm = SettingsManager.instance()
    menu = QMenu()

    # --- 歌词宽度子菜单 ---
    action_width_menu = QMenu("设置歌词宽度比例", menu)

    def get_width_handler(pct):
        return lambda checked=False: window.set_width_percentage(pct)

    for p in [100, 80, 60, 40]:
        act = QAction(f"{p}%", action_width_menu)
        act.triggered.connect(get_width_handler(p))
        action_width_menu.addAction(act)

    action_width_menu.addSeparator()

    act_custom = QAction("自定义输入...", action_width_menu)
    def open_custom_input():
        pct, ok = QInputDialog.getInt(
            None, "自定义宽度设定",
            "请输入窗体宽度占比 (10 - 100)%:",
            window.width_percentage, 10, 100, 1
        )
        if ok:
            window.set_width_percentage(pct)

    act_custom.triggered.connect(open_custom_input)
    action_width_menu.addAction(act_custom)

    menu.addMenu(action_width_menu)

    # --- 设置... ---
    action_settings = QAction("设置...", menu)
    action_settings.triggered.connect(
        lambda: SettingsDialog(sm).exec()
    )
    menu.addAction(action_settings)

    menu.addSeparator()

    # --- 手动搜索 ---
    action_search = QAction("手动搜索并绑定歌词...", menu)

    def open_search():
        if not window.current_title:
            return
        dialog = ManualSearchDialog(worker, window.current_title, window.current_artist)
        if dialog.exec():
            song_id = dialog.selected_song_id
            if song_id:
                asyncio.run_coroutine_threadsafe(
                    worker.fetch_and_bind_lyrics(window.current_title,
                                                 window.current_artist, song_id),
                    worker._loop
                )

    action_search.triggered.connect(open_search)
    window.searchRequested.connect(open_search)
    menu.addAction(action_search)

    # --- 锁定 ---
    action_lock = QAction("锁定歌词 (鼠标穿透)", menu)
    action_lock.setCheckable(True)
    action_lock.triggered.connect(window.toggle_locked)
    menu.addAction(action_lock)

    menu.addSeparator()

    # --- 关于 ---
    action_about = QAction("关于...", menu)
    action_about.triggered.connect(lambda: AboutDialog().exec())
    menu.addAction(action_about)

    menu.addSeparator()

    # --- 退出 ---
    action_quit = QAction("退出", menu)
    def quit_app():
        worker.stop()
        worker.quit()
        worker.wait(1000)
        app.quit()
    action_quit.triggered.connect(quit_app)
    menu.addAction(action_quit)

    tray.setContextMenu(menu)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
