"""
Kyo Dynamic Island (Clean & Sleek Edition)
- Clean, flush design without awkward side-notch artifacts.
- Super Clear Notification Banner (Shows App, Sender, and Full Message Body like WhatsApp / Telegram).
- Dynamic Notch Pet that morphs smoothly into Now Playing, Notifications, or Battery.
- Click to expand to Now Playing or Focus directly (no unwanted separate control deck).
- Auto-Hide when clicking outside or mouse leave.
- Run on Windows Startup helper.
"""

import os
import sys
import math
import time
import asyncio
import threading
import winreg
import psutil
from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QPointF, pyqtSignal, QObject, QPropertyAnimation,
    QEasingCurve, pyqtProperty
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QPainterPath, QFont, QLinearGradient,
    QRadialGradient, QIcon, QPixmap
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSystemTrayIcon, QMenu
)

try:
    import winsdk.windows.media.control as wmc
    import winsdk.windows.ui.notifications.management as unm
    import winsdk.windows.ui.notifications as un
    WINSDK_AVAILABLE = True
except Exception:
    WINSDK_AVAILABLE = False


# ==============================================================================
# WINDOWS STARTUP HELPER (AUTO START ON BOOT)
# ==============================================================================
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "KyoDynamicIsland"

def is_run_on_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def set_run_on_startup(enable=True):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            bat_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "start_island.bat"))
            cmd = f'"{bat_path}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except Exception:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print("Error set startup:", e)
        return False


# ==============================================================================
# REALTIME OBSERVER (NOTIFICATIONS & MEDIA)
# ==============================================================================
class SystemObserverWorker(QObject):
    media_changed = pyqtSignal(dict)
    notification_arrived = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.last_media_state = {"title": "", "artist": "", "is_playing": False, "has_media": False}
        self.last_notif_ids = set()
        self.active_session_ref = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._monitor())

    async def _monitor(self):
        mgr = None
        listener = None
        has_notif_access = False

        if WINSDK_AVAILABLE:
            try:
                listener = unm.UserNotificationListener.current
                access = await listener.request_access_async()
                has_notif_access = (access == unm.UserNotificationListenerAccessStatus.ALLOWED)
                if has_notif_access:
                    existing = await listener.get_notifications_async(un.NotificationKinds.TOAST)
                    self.last_notif_ids = {n.id for n in existing}
            except Exception:
                pass

        while True:
            # 1. Deteksi Notifikasi Baru (WhatsApp, Browser, Telegram, dll)
            if WINSDK_AVAILABLE and has_notif_access and listener:
                try:
                    notifs = await listener.get_notifications_async(un.NotificationKinds.TOAST)
                    for n in notifs:
                        if n.id not in self.last_notif_ids:
                            self.last_notif_ids.add(n.id)
                            app_name = n.app_info.display_info.display_name if n.app_info else "Windows"
                            
                            sender = app_name
                            message = ""
                            try:
                                binding = n.notification.visual.get_binding(un.KnownNotificationBindings.toast_generic)
                                if binding:
                                    texts = [el.text.strip() for el in binding.get_text_elements() if el.text]
                                    if len(texts) == 1:
                                        message = texts[0]
                                    elif len(texts) >= 2:
                                        sender = texts[0]
                                        message = " ".join(texts[1:])
                            except Exception:
                                pass

                            if not message:
                                message = "Pesan atau notifikasi baru masuk"

                            self.notification_arrived.emit({
                                "app": app_name,
                                "sender": sender,
                                "message": message
                            })
                            break
                except Exception:
                    pass

            # 2. Deteksi Media Player (Spotify, YouTube, dll)
            if WINSDK_AVAILABLE:
                try:
                    if mgr is None:
                        mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()

                    cur_session = mgr.get_current_session()
                    if not cur_session:
                        sessions = mgr.get_sessions()
                        if sessions and len(sessions) > 0:
                            cur_session = sessions[0]

                    if cur_session:
                        self.active_session_ref = cur_session
                        prop = await cur_session.try_get_media_properties_async()
                        pb = cur_session.get_playback_info()
                        is_playing = (pb.playback_status == wmc.GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING)
                        title = (prop.title or "").strip()
                        artist = (prop.artist or "").strip()

                        if not title and not artist:
                            state = {"title": "", "artist": "", "is_playing": False, "has_media": False}
                        else:
                            state = {
                                "title": title if title else "Now Playing",
                                "artist": artist if artist else "Media",
                                "is_playing": is_playing,
                                "has_media": True
                            }
                    else:
                        self.active_session_ref = None
                        state = {"title": "", "artist": "", "is_playing": False, "has_media": False}
                except Exception:
                    mgr = None
                    state = {"title": "", "artist": "", "is_playing": False, "has_media": False}
            else:
                state = {"title": "", "artist": "", "is_playing": False, "has_media": False}

            if state != self.last_media_state:
                self.last_media_state = state
                self.media_changed.emit(state)

            await asyncio.sleep(0.9)

    def toggle_play_pause(self):
        async def _act():
            try:
                if self.active_session_ref:
                    await self.active_session_ref.try_toggle_play_pause_async()
            except Exception:
                pass
        threading.Thread(target=lambda: asyncio.run(_act()), daemon=True).start()


# ==============================================================================
# MAIN NOTCH WIDGET
# ==============================================================================
class KyoIslandWidget(QWidget):
    def __init__(self, observer: SystemObserverWorker, parent=None):
        super().__init__(parent)
        self.observer = observer
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # Mode: 'pet', 'notif', 'music', 'pomo', 'water', 'shelf', 'battery'
        self.mode = "pet"
        self.is_expanded = False

        # Dimensi Clean Notch (Ultra Slim Pill agar tidak menutupi tab/minimize button aplikasi lain)
        self._w = 140.0
        self._h = 24.0
        self.radius = 12.0

        self.anim_w = QPropertyAnimation(self, b"anim_width")
        self.anim_w.setDuration(380)
        self.anim_w.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.anim_h = QPropertyAnimation(self, b"anim_height")
        self.anim_h.setDuration(380)
        self.anim_h.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Pet Eyes
        self.eye_scale_y = 1.0
        self.eye_dx = 0.0
        self.eye_dy = 0.0
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._do_blink)
        self.blink_timer.start(3400)

        # Equalizer
        self.eq_bars = [0.3, 0.6, 0.8, 0.4, 0.7, 0.5]

        # Pomodoro
        self.pomo_total = 25 * 60
        self.pomo_left = self.pomo_total
        self.pomo_running = False

        # Water
        self.water_goal = 8
        self.water_count = 3
        self.water_countdown = 45 * 60

        # Shelf
        self.shelf_files = []

        # Battery Animation & State
        self.battery_pct = 100
        self.is_plugged = True
        self.last_plugged_state = True
        self.charge_wave_phase = 0.0

        # Notification data & timer
        self.current_notif = None
        self.notif_timer = QTimer(self)
        self.notif_timer.setSingleShot(True)
        self.notif_timer.timeout.connect(self._dismiss_notif)

        # Auto-hide timer jika mouse leave
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.timeout.connect(self._collapse_to_pet)

        # Media cache
        self.media_info = {"title": "", "artist": "", "is_playing": False, "has_media": False}

        # 60 FPS tick
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._tick)
        self.render_timer.start(16)

        # 1-sec tick
        self.sec_timer = QTimer(self)
        self.sec_timer.timeout.connect(self._second_tick)
        self.sec_timer.start(1000)

        self._check_battery(initial=True)

    def get_anim_width(self):
        return self._w

    def set_anim_width(self, val):
        self._w = val
        self.update()

    anim_width = pyqtProperty(float, get_anim_width, set_anim_width)

    def get_anim_height(self):
        return self._h

    def set_anim_height(self, val):
        self._h = val
        self.update()

    anim_height = pyqtProperty(float, get_anim_height, set_anim_height)

    def transition_to(self, target_w, target_h, target_r):
        self.radius = target_r
        self.anim_w.stop()
        self.anim_w.setStartValue(self._w)
        self.anim_w.setEndValue(target_w)
        self.anim_w.start()

        self.anim_h.stop()
        self.anim_h.setStartValue(self._h)
        self.anim_h.setEndValue(target_h)
        self.anim_h.start()

    def set_mode(self, new_mode):
        self.mode = new_mode
        if new_mode == "pet":
            self.is_expanded = False
            self.transition_to(140.0, 24.0, 12.0)
        elif new_mode == "notif":
            # Melebar proporsional untuk menampilkan isi pesan notifikasi
            self.transition_to(440.0, 78.0, 24.0)
        elif new_mode == "battery":
            self.transition_to(380.0, 68.0, 22.0)
        elif new_mode == "music":
            self.is_expanded = True
            self.transition_to(430.0, 138.0, 26.0)
        elif new_mode == "pomo":
            self.is_expanded = True
            self.transition_to(420.0, 138.0, 26.0)
        elif new_mode == "water":
            self.is_expanded = True
            self.transition_to(420.0, 138.0, 26.0)
        elif new_mode == "shelf":
            self.is_expanded = True
            self.transition_to(430.0, 140.0, 26.0)

    def _do_blink(self):
        self.eye_scale_y = 0.08
        QTimer.singleShot(140, self._finish_blink)

    def _finish_blink(self):
        self.eye_scale_y = 1.0

    def _tick(self):
        if self.mode == "battery" or self.is_plugged:
            self.charge_wave_phase = (self.charge_wave_phase + 0.05) % (2 * math.pi)

        if self.media_info.get("is_playing"):
            t = time.time() * 8.0
            for i in range(len(self.eq_bars)):
                self.eq_bars[i] = (math.sin(t + i * 1.2) + 1.0) / 2.0
        self.update()

    def _second_tick(self):
        if self.pomo_running and self.pomo_left > 0:
            self.pomo_left -= 1
        if self.water_countdown > 0:
            self.water_countdown -= 1
        self._check_battery()

    def _check_battery(self, initial=False):
        try:
            bat = psutil.sensors_battery()
            if bat:
                self.battery_pct = int(bat.percent)
                now_plugged = bat.power_plugged
                if not initial and now_plugged != self.last_plugged_state:
                    self.last_plugged_state = now_plugged
                    if not self.is_expanded:
                        self.set_mode("battery")
                        QTimer.singleShot(4200, self._collapse_to_pet)
                self.last_plugged_state = now_plugged
                self.is_plugged = now_plugged
        except Exception:
            pass

    def on_notification_received(self, notif_data):
        self.current_notif = notif_data
        # Otomatis pop-up notifikasi kapan saja ada pesan masuk
        self.set_mode("notif")
        if self.parent():
            self.parent().raise_()
        self.notif_timer.start(6000)

    def _dismiss_notif(self):
        if self.mode == "notif":
            self._collapse_to_pet()

    def on_media_changed(self, state):
        was_playing = self.media_info.get("is_playing", False)
        old_title = self.media_info.get("title", "")
        self.media_info = state

        if state.get("is_playing") and (not was_playing or old_title != state.get("title")):
            if not self.is_expanded:
                self.set_mode("music")
                self.auto_hide_timer.start(6500)

    # Mouse & Event Handlers
    def enterEvent(self, event):
        self.auto_hide_timer.stop()
        if self.mode == "pet":
            self.transition_to(160.0, 28.0, 14.0)

    def leaveEvent(self, event):
        if self.mode == "pet":
            self.transition_to(140.0, 24.0, 12.0)
        elif self.is_expanded:
            # Auto hidden setelah 2 detik kursor keluar
            self.auto_hide_timer.start(2000)

    def _collapse_to_pet(self):
        self.set_mode("pet")

    def mousePressEvent(self, event):
        self.auto_hide_timer.stop()
        pos = event.position()
        cx = self.width() / 2.0
        w = self._w
        h = self._h
        x1 = cx - w / 2.0
        x2 = cx + w / 2.0
        y1 = 0.0
        y2 = h

        # 1. AUTO-HIDDEN: Klik di luar area notch langsung menutup ke awal
        if not (x1 <= pos.x() <= x2 and y1 <= pos.y() <= y2):
            self._collapse_to_pet()
            return

        # 2. Klik pada Kyo Pet saat idle -> Buka langsung modul aktif (Now Playing jika ada lagu, atau Fokus Timer)
        if self.mode in ("pet", "notif", "battery"):
            if self.media_info.get("has_media"):
                self.set_mode("music")
            else:
                self.set_mode("pomo")
            return

        # 3. Kontrol di dalam mode Musik
        if self.mode == "music":
            btn_cx = cx + 150
            btn_cy = 66
            if (pos.x() - btn_cx)**2 + (pos.y() - btn_cy)**2 <= 22**2:
                self.observer.toggle_play_pause()
                return

        # 4. Kontrol Pomodoro
        if self.mode == "pomo":
            btn_cx = cx + 130
            btn_cy = 66
            if (pos.x() - btn_cx)**2 + (pos.y() - btn_cy)**2 <= 26**2:
                self.pomo_running = not self.pomo_running
                self.update()
                return

        # 5. Kontrol Water
        if self.mode == "water":
            btn_cx = cx + 130
            btn_cy = 66
            if (pos.x() - btn_cx)**2 + (pos.y() - btn_cy)**2 <= 26**2:
                self.water_count = min(self.water_goal, self.water_count + 1)
                self.water_countdown = 60 * 60
                self.update()
                return

        # 6. Kontrol Shelf
        if self.mode == "shelf":
            if abs(pos.x() - (cx + 140)) < 24 and abs(pos.y() - 24) < 14:
                self.shelf_files.clear()
                self.update()
                return

        # 7. Navigasi Dots Bawah jika expanded
        if self.is_expanded:
            if y2 - 25 <= pos.y() <= y2:
                modes = ["music", "pomo", "water", "shelf", "pet"]
                dot_w = 26.0
                dot_start = cx - (len(modes) * dot_w) / 2.0
                for idx, m in enumerate(modes):
                    dcx = dot_start + idx * dot_w + dot_w / 2.0
                    if abs(pos.x() - dcx) < 13:
                        self.set_mode(m)
                        return

    def mouseMoveEvent(self, event):
        pos = event.position()
        cx = self.width() / 2.0
        dx = (pos.x() - cx) / 75.0
        dy = (pos.y() - 18.0) / 35.0
        self.eye_dx = max(-4.0, min(4.0, dx))
        self.eye_dy = max(-2.5, min(2.5, dy))

    # Drag & Drop File Shelf
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self.mode != "shelf":
                self.set_mode("shelf")

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if p and p not in self.shelf_files:
                    self.shelf_files.insert(0, p)
            self.set_mode("shelf")
            event.acceptProposedAction()
            self.update()

    # ==========================================================================
    # CLEAN PILL / NOTCH RENDERER (NO UGLY SIDE CORNERS)
    # ==========================================================================
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2.0
        w = self._w
        h = self._h
        x = cx - w / 2.0
        y = 0.0
        r = self.radius

        # Bentuk Pill Bersih Menempel ke Atas Layar (Tanpa sayap samping yang patah)
        pill_rect = QRectF(x, y, w, h)
        path = QPainterPath()
        # Rounded hanya di sudut kiri bawah dan kanan bawah
        path.moveTo(x, y)
        path.lineTo(x, y + h - r)
        path.arcTo(QRectF(x, y + h - 2 * r, 2 * r, 2 * r), 180, 90)
        path.lineTo(x + w - r, y + h)
        path.arcTo(QRectF(x + w - 2 * r, y + h - 2 * r, 2 * r, 2 * r), 270, 90)
        path.lineTo(x + w, y)
        path.closeSubpath()

        # Bayangan Halus
        shadow = QPainterPath()
        shadow.addRoundedRect(QRectF(x - 3, y, w + 6, h + 6), r + 3, r + 3)
        painter.fillPath(shadow, QColor(0, 0, 0, 95))

        # Badan Hitam Pekat Charcoal
        painter.fillPath(path, QColor(9, 12, 15, 252))

        # Garis Bawah Aksen Cyber-Emerald & Neon Cyan
        glow_grad = QLinearGradient(x, y + h, x + w, y + h)
        glow_grad.setColorAt(0.0, QColor(0, 245, 160, 150))
        glow_grad.setColorAt(0.5, QColor(0, 217, 245, 180))
        glow_grad.setColorAt(1.0, QColor(46, 120, 255, 150))
        painter.strokePath(path, QPen(QBrush(glow_grad), 1.5))

        # Konten di dalam Notch
        painter.save()
        painter.setClipPath(path)

        if self.mode == "pet":
            self._render_pet(painter, cx, y, w, h)
        elif self.mode == "notif":
            self._render_notification(painter, cx, y, w, h)
        elif self.mode == "music":
            self._render_music(painter, cx, y, w, h)
        elif self.mode == "pomo":
            self._render_pomo(painter, cx, y, w, h)
        elif self.mode == "water":
            self._render_water(painter, cx, y, w, h)
        elif self.mode == "shelf":
            self._render_shelf(painter, cx, y, w, h)
        elif self.mode == "battery":
            self._render_battery(painter, cx, y, w, h)

        if self.is_expanded:
            self._render_bottom_nav(painter, cx, y + h - 12)

        painter.restore()

    def _render_pet(self, painter, cx, y, w, h):
        """Kyo Living Mascot (Ultra Slim & Elegant)."""
        eye_w = 7.0
        eye_h = 11.0 * max(0.1, self.eye_scale_y)
        gap = 20.0
        eye_y = y + h / 2.0 - eye_h / 2.0 + (self.eye_dy * 0.6)

        for sign in (-1, 1):
            ex = cx + (sign * gap / 2.0) - eye_w / 2.0 + (self.eye_dx * 0.6)
            glow = QRadialGradient(ex + eye_w / 2.0, eye_y + eye_h / 2.0, 8)
            glow.setColorAt(0.0, QColor(0, 245, 160, 220))
            glow.setColorAt(0.65, QColor(0, 180, 140, 75))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(glow))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(ex - 4, eye_y - 4, eye_w + 8, eye_h + 8))

            painter.setBrush(QColor(255, 255, 255, 250))
            painter.drawRoundedRect(QRectF(ex, eye_y, eye_w, eye_h), 3.5, 3.5)

    def _render_notification(self, painter, cx, y, w, h):
        """Notifikasi Super Jelas: Icon Aplikasi, Pengirim, dan Isi Pesan Lengkap."""
        x1 = cx - w / 2.0

        # Avatar / Icon Bulat
        avatar_rect = QRectF(x1 + 16, y + 18, 42, 42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 245, 160, 35))
        painter.drawRoundedRect(avatar_rect, 13, 13)

        painter.setFont(QFont("Segoe UI Variable Display", 16))
        painter.setPen(QColor(0, 245, 160))
        painter.drawText(avatar_rect, Qt.AlignmentFlag.AlignCenter, "💬")

        if self.current_notif:
            app_name = self.current_notif.get("app", "Pemberitahuan")
            sender = self.current_notif.get("sender", app_name)
            message = self.current_notif.get("message", "")
        else:
            app_name = "WhatsApp"
            sender = "Pengirim Pesan"
            message = "Halo! Ini contoh tampilan pesan notifikasi."

        # Header Pengirim & Aplikasi
        header_text = f"{sender}  •  {app_name}"
        if len(header_text) > 36:
            header_text = header_text[:34] + "..."

        painter.setFont(QFont("Segoe UI Variable Display", 10, QFont.Weight.Bold))
        painter.setPen(QColor(0, 245, 160))
        painter.drawText(int(x1 + 68), int(y + 34), header_text)

        # Isi Pesan (Message Body)
        if len(message) > 48:
            message = message[:46] + "..."

        painter.setFont(QFont("Segoe UI Variable Text", 10))
        painter.setPen(QColor(245, 250, 248))
        painter.drawText(int(x1 + 68), int(y + 54), message)

    def _render_music(self, painter, cx, y, w, h):
        x1 = cx - w / 2.0
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(0, 245, 160))
        painter.drawText(int(x1 + 24), int(y + 24), "NOW PLAYING")

        art_rect = QRectF(x1 + 24, y + 36, 68, 68)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 24, 28))
        painter.drawRoundedRect(art_rect, 15, 15)

        vg = QLinearGradient(art_rect.topLeft(), art_rect.bottomRight())
        vg.setColorAt(0.0, QColor(0, 245, 160, 220))
        vg.setColorAt(1.0, QColor(0, 180, 245, 220))
        painter.setBrush(QBrush(vg))
        painter.drawEllipse(QRectF(art_rect.center().x() - 19, art_rect.center().y() - 19, 38, 38))
        painter.setBrush(QColor(10, 14, 16))
        painter.drawEllipse(QRectF(art_rect.center().x() - 6, art_rect.center().y() - 6, 12, 12))

        title = self.media_info.get("title", "") or "Tidak ada lagu diputar"
        if len(title) > 23:
            title = title[:21] + "..."
        painter.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        painter.setPen(QColor(245, 250, 248))
        painter.drawText(int(x1 + 104), int(y + 60), title)

        artist = self.media_info.get("artist", "") or "Buka Spotify/Browser"
        if len(artist) > 26:
            artist = artist[:24] + "..."
        painter.setFont(QFont("Segoe UI Variable Text", 10))
        painter.setPen(QColor(135, 165, 155))
        painter.drawText(int(x1 + 104), int(y + 80), artist)

        eq_x = x1 + 104
        eq_y = y + 92
        painter.setBrush(QColor(0, 245, 160, 240))
        for i, val in enumerate(self.eq_bars):
            bh = 4.0 + val * 11.0
            painter.drawRoundedRect(QRectF(eq_x + i * 6.0, eq_y - bh, 3.5, bh), 1.7, 1.7)

        btn_pos = QPointF(cx + 150, y + 66)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 245, 160, 235))
        painter.drawEllipse(btn_pos, 22, 22)

        painter.setBrush(QColor(10, 14, 16))
        if self.media_info.get("is_playing"):
            painter.drawRect(int(btn_pos.x() - 5), int(btn_pos.y() - 7), 3, 14)
            painter.drawRect(int(btn_pos.x() + 2), int(btn_pos.y() - 7), 3, 14)
        else:
            tri = QPainterPath()
            tri.moveTo(btn_pos.x() - 4, btn_pos.y() - 8)
            tri.lineTo(btn_pos.x() + 8, btn_pos.y())
            tri.lineTo(btn_pos.x() - 4, btn_pos.y() + 8)
            tri.closeSubpath()
            painter.fillPath(tri, QColor(10, 14, 16))

    def _render_pomo(self, painter, cx, y, w, h):
        x1 = cx - w / 2.0
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(0, 245, 160))
        painter.drawText(int(x1 + 24), int(y + 24), "FOCUS TIMER")

        mins = self.pomo_left // 60
        secs = self.pomo_left % 60
        painter.setFont(QFont("Segoe UI Variable Display", 26, QFont.Weight.Bold))
        painter.setPen(QColor(245, 250, 248))
        painter.drawText(int(x1 + 24), int(y + 68), f"{mins:02d}:{secs:02d}")

        status = "Fokus sedang berjalan..." if self.pomo_running else "Klik untuk mulai fokus"
        painter.setFont(QFont("Segoe UI Variable Text", 10))
        painter.setPen(QColor(135, 165, 155))
        painter.drawText(int(x1 + 24), int(y + 92), status)

        arc_rect = QRectF(cx + 105, y + 42, 52, 52)
        painter.setPen(QPen(QColor(255, 255, 255, 25), 4.5))
        painter.drawEllipse(arc_rect)

        progress = (self.pomo_total - self.pomo_left) / float(self.pomo_total)
        arc_pen = QPen(QColor(245, 105, 80), 4.5)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        painter.drawArc(arc_rect, 90 * 16, int(-progress * 360 * 16))

        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
        painter.setPen(QColor(245, 250, 248))
        painter.drawText(arc_rect, Qt.AlignmentFlag.AlignCenter, "PAUSE" if self.pomo_running else "START")

    def _render_water(self, painter, cx, y, w, h):
        x1 = cx - w / 2.0
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(0, 217, 245))
        painter.drawText(int(x1 + 24), int(y + 24), "WATER REMINDER")

        painter.setFont(QFont("Segoe UI Variable Display", 24, QFont.Weight.Bold))
        painter.setPen(QColor(0, 245, 160))
        painter.drawText(int(x1 + 24), int(y + 66), f"{self.water_count} / {self.water_goal} Gelas")

        rem_m = self.water_countdown // 60
        painter.setFont(QFont("Segoe UI Variable Text", 10))
        painter.setPen(QColor(135, 165, 155))
        painter.drawText(int(x1 + 24), int(y + 90), f"Pengingat minum: {rem_m} menit lagi")

        btn_pos = QPointF(cx + 130, y + 68)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 217, 245, 235))
        painter.drawEllipse(btn_pos, 22, 22)

        painter.setFont(QFont("Segoe UI Variable Display", 18, QFont.Weight.Bold))
        painter.setPen(QColor(10, 14, 16))
        painter.drawText(QRectF(btn_pos.x() - 15, btn_pos.y() - 15, 30, 30), Qt.AlignmentFlag.AlignCenter, "+")

    def _render_shelf(self, painter, cx, y, w, h):
        x1 = cx - w / 2.0
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(0, 245, 160))
        painter.drawText(int(x1 + 24), int(y + 24), "QUICK SHELF (DROP FILES)")

        if self.shelf_files:
            painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.Bold))
            painter.setPen(QColor(245, 90, 90))
            painter.drawText(int(cx + 120), int(y + 24), "Clear All")

        if not self.shelf_files:
            painter.setFont(QFont("Segoe UI Variable Text", 10))
            painter.setPen(QColor(120, 145, 135))
            painter.drawText(int(x1 + 24), int(y + 65), "Tarik file dari Windows Explorer ke notch ini.")
        else:
            for idx, p in enumerate(self.shelf_files[:3]):
                name = os.path.basename(p)
                painter.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
                painter.setPen(QColor(240, 248, 245))
                painter.drawText(int(x1 + 24), int(y + 54 + idx * 20), f"📎 {name[:36]}")

    def _render_battery(self, painter, cx, y, w, h):
        """Ultra-Sleek Dynamic Battery & Charging HUD with breathing animations."""
        x1 = cx - w / 2.0

        # 1. Circular Charging Emblem / Lightning Icon
        icon_rect = QRectF(x1 + 18, y + 14, 40, 40)
        
        # Ambient Breathing Aura
        pulse = (math.sin(self.charge_wave_phase * 2.0) + 1.0) / 2.0
        aura_color = QColor(0, 245, 160, int(35 + pulse * 45)) if self.is_plugged else (
            QColor(0, 217, 245, 30) if self.battery_pct > 20 else QColor(255, 75, 75, 50)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(aura_color)
        painter.drawRoundedRect(icon_rect, 13, 13)

        # Lightning / Battery Bolt Icon
        painter.setFont(QFont("Segoe UI Variable Display", 16))
        painter.setPen(QColor(0, 245, 160) if self.is_plugged else QColor(245, 250, 248))
        icon_symbol = "⚡" if self.is_plugged else ("🪫" if self.battery_pct <= 20 else "🔋")
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, icon_symbol)

        # 2. Text Status & Percentage
        painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
        painter.setPen(QColor(245, 250, 248))
        status_label = "MENGISI DAYA CEPAT" if self.is_plugged else "DAYA BATERAI"
        painter.drawText(int(x1 + 68), int(y + 30), status_label)

        # Subtitle Status
        painter.setFont(QFont("Segoe UI Variable Text", 9))
        painter.setPen(QColor(135, 165, 155))
        sub_text = "Terhubung adaptor listrik" if self.is_plugged else (
            "Baterai hampir habis!" if self.battery_pct <= 20 else "Mode hemat daya aktif"
        )
        painter.drawText(int(x1 + 68), int(y + 44), sub_text)

        # 3. Big Percentage Display on Right
        pct_str = f"{self.battery_pct}%"
        painter.setFont(QFont("Segoe UI Variable Display", 15, QFont.Weight.ExtraBold))
        pct_color = QColor(0, 245, 160) if self.battery_pct > 20 else QColor(255, 85, 85)
        painter.setPen(pct_color)
        painter.drawText(int(cx + w / 2.0 - 64), int(y + 33), pct_str)

        # 4. Sleek Progress Bar Rail
        rail_rect = QRectF(x1 + 68, y + 51, w - 86, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(rail_rect, 3.5, 3.5)

        # Animated Gradient Fill
        fill_width = max(6.0, rail_rect.width() * (self.battery_pct / 100.0))
        fill_rect = QRectF(rail_rect.x(), rail_rect.y(), fill_width, rail_rect.height())

        bar_gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.bottomRight())
        if self.battery_pct <= 20:
            bar_gradient.setColorAt(0.0, QColor(255, 105, 70))
            bar_gradient.setColorAt(1.0, QColor(255, 55, 55))
        elif self.is_plugged:
            # Dynamic Shimmer Effect when charging
            shimmer_offset = (math.sin(self.charge_wave_phase) + 1.0) / 2.0
            bar_gradient.setColorAt(0.0, QColor(0, 217, 245))
            bar_gradient.setColorAt(max(0.05, min(0.95, shimmer_offset)), QColor(0, 245, 160))
            bar_gradient.setColorAt(1.0, QColor(46, 220, 140))
        else:
            bar_gradient.setColorAt(0.0, QColor(0, 217, 245))
            bar_gradient.setColorAt(1.0, QColor(0, 245, 160))

        painter.setBrush(QBrush(bar_gradient))
        painter.drawRoundedRect(fill_rect, 3.5, 3.5)

    def _render_bottom_nav(self, painter, cx, dot_y):
        modes = ["music", "pomo", "water", "shelf", "pet"]
        dot_w = 26.0
        start_x = cx - (len(modes) * dot_w) / 2.0
        for idx, m in enumerate(modes):
            dot_cx = start_x + idx * dot_w + dot_w / 2.0
            is_active = (self.mode == m)
            painter.setPen(Qt.PenStyle.NoPen)
            if is_active:
                painter.setBrush(QColor(0, 245, 160, 245))
                painter.drawRoundedRect(QRectF(dot_cx - 7, dot_y - 2, 14, 4), 2, 2)
            else:
                painter.setBrush(QColor(255, 255, 255, 60))
                painter.drawRoundedRect(QRectF(dot_cx - 2, dot_y - 2, 4, 4), 2, 2)


# ==============================================================================
# WINDOW SHELL & SYSTEM TRAY
# ==============================================================================
class KyoMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.observer = SystemObserverWorker()
        self.island = KyoIslandWidget(self.observer, self)
        self.observer.media_changed.connect(self.island.on_media_changed)
        self.observer.notification_arrived.connect(self.island.on_notification_received)

        self.setCentralWidget(self.island)
        self._setup_tray()
        self.reposition_screen()

    def reposition_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            win_w = 560
            win_h = 165
            x = int(geo.x() + (geo.width() - win_w) / 2)
            y = int(geo.y())
            self.setGeometry(x, y, win_w, win_h)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 245, 160))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 6, 28, 20, 8, 8)
        p.setBrush(QColor(10, 14, 16))
        p.drawEllipse(8, 12, 4, 7)
        p.drawEllipse(20, 12, 4, 7)
        p.end()

        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip("Kyo Dynamic Island")

        menu = QMenu()
        menu.addAction("🐾 Kyo Pet", lambda: self.island.set_mode("pet"))
        menu.addAction("🎵 Music Player", lambda: self.island.set_mode("music"))
        menu.addAction("⏱ Focus Timer", lambda: self.island.set_mode("pomo"))
        menu.addAction("💧 Water Reminder", lambda: self.island.set_mode("water"))
        menu.addAction("📁 Quick Shelf", lambda: self.island.set_mode("shelf"))
        menu.addAction("⚡ Battery HUD", lambda: self.island.set_mode("battery"))
        menu.addSeparator()

        # Menu toggle start on Windows startup
        self.startup_action = menu.addAction("🚀 Jalankan Saat Windows Nyala (Auto-Start)")
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(is_run_on_startup())
        self.startup_action.triggered.connect(self._toggle_startup)

        menu.addSeparator()
        menu.addAction("Keluar (Exit)", QApplication.instance().quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _toggle_startup(self, checked):
        set_run_on_startup(checked)
        self.startup_action.setChecked(is_run_on_startup())


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = KyoMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
