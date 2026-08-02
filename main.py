"""
Cari HP (Phone Finder) - Fase 2 (background service)
"""

import json
import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.utils import platform, get_color_from_hex

IS_ANDROID = platform == "android"
DEFAULT_THRESHOLD = 25000
SERVICE_CLASS = "org.subehiahmad.phonefinder.ServiceListener"
STALE_AFTER = 10

BG_COLOR = get_color_from_hex("#141C3A")
CARD_COLOR = get_color_from_hex("#1B2550")
ACCENT_COLOR = get_color_from_hex("#FF9E45")
TEXT_COLOR = get_color_from_hex("#F4F6FB")
MUTED_COLOR = get_color_from_hex("#9AA3C7")
GREEN = get_color_from_hex("#3FA96A")
RED = get_color_from_hex("#E8593F")

GREEN_HEX = "3FA96A"
RED_HEX = "E8593F"
MUTED_HEX = "9AA3C7"

Window.clearcolor = BG_COLOR

if IS_ANDROID:
    from android.permissions import Permission, check_permission, request_permissions
    from jnius import autoclass


def get_paths():
    app = App.get_running_app()
    data_dir = app.user_data_dir
    return (
        os.path.join(data_dir, "status.json"),
        os.path.join(data_dir, "control.json"),
    )


def write_control(threshold, should_stop):
    _, control_path = get_paths()
    try:
        with open(control_path, "w") as f:
            json.dump({"threshold": threshold, "should_stop": should_stop}, f)
    except Exception:
        pass


def read_status():
    status_path, _ = get_paths()
    try:
        with open(status_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


class Card(BoxLayout):
    """BoxLayout dengan latar rounded-rect custom."""

    def __init__(self, bg_color=CARD_COLOR, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg_color)
            self._rect = RoundedRectangle(radius=[18], pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class RoundedButton(ButtonBehavior, BoxLayout):
    """Tombol dengan sudut membulat, isinya 1 Label."""

    def __init__(self, text="", bg_color=GREEN, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            self._color = Color(*bg_color)
            self._rect = RoundedRectangle(radius=[16], pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)
        self.label = Label(text=text, font_size="20sp", bold=True, color=TEXT_COLOR)
        self.add_widget(self.label)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_bg_color(self, color):
        self._color.rgba = color

    def set_text(self, text):
        self.label.text = text


class StatCard(Card):
    """Kartu statistik: label kecil di atas, angka besar di bawah."""

    def __init__(self, title="", **kwargs):
        super().__init__(orientation="vertical", padding=(10, 14), spacing=2, **kwargs)
        self.title_label = Label(
            text=title.upper(),
            font_size="11sp",
            bold=True,
            color=MUTED_COLOR,
            size_hint=(1, 0.4),
        )
        self.title_label.bind(size=lambda inst, s: setattr(inst, "text_size", s))
        self.value_label = Label(
            text="-",
            font_size="28sp",
            bold=True,
            color=ACCENT_COLOR,
            size_hint=(1, 0.6),
        )
        self.value_label.bind(size=lambda inst, s: setattr(inst, "text_size", s))
        self.add_widget(self.title_label)
        self.add_widget(self.value_label)

    def set_value(self, text):
        self.value_label.text = text


class FinderUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=28, spacing=18, **kwargs)
        self.running = False
        self.stop_requested_at = 0
        self.threshold = DEFAULT_THRESHOLD

        title = Label(
            text="Cari HP",
            font_size="30sp",
            bold=True,
            color=TEXT_COLOR,
            size_hint=(1, 0.7),
        )
        self.add_widget(title)

        status_card = Card(orientation="vertical", padding=18, size_hint=(1, 1.3))
        self.status_label = Label(
            text="",
            markup=True,
            font_size="18sp",
            color=TEXT_COLOR,
            halign="center",
            valign="middle",
        )
        self.status_label.bind(
            size=lambda inst, s: setattr(inst, "text_size", (s[0] * 0.95, s[1]))
        )
        status_card.add_widget(self.status_label)
        self.add_widget(status_card)
        self.set_status_text("berhenti", "idle")

        stats_row = BoxLayout(orientation="horizontal", spacing=14, size_hint=(1, 1.0))
        self.peak_card = StatCard(title="Puncak sesi ini", size_hint=(0.5, 1))
        stats_row.add_widget(self.peak_card)
        self.count_card = StatCard(title="Terdeteksi", size_hint=(0.5, 1))
        self.count_card.set_value("0x")
        stats_row.add_widget(self.count_card)
        self.add_widget(stats_row)

        self.sensitivity_label = Label(
            text=f"Sensitivitas: {self.threshold}",
            font_size="15sp",
            color=TEXT_COLOR,
            size_hint=(1, None),
            height=32,
        )
        self.add_widget(self.sensitivity_label)

        slider = Slider(
            min=10000, max=30000, value=self.threshold, step=500, size_hint=(1, None), height=48
        )
        slider.bind(value=self.on_slider_change)
        self.add_widget(slider)

        self.toggle_btn = RoundedButton(
            text="Mulai (Background)", bg_color=GREEN, size_hint=(1, None), height=68
        )
        self.toggle_btn.bind(on_release=self.on_toggle)
        self.add_widget(self.toggle_btn)

        info_card = Card(orientation="vertical", padding=20, size_hint=(1, 1.4))
        info = Label(
            text=(
                "Fase 2: jalan walau app ditutup/layar mati.\n\n"
                "Kalau tetap gak kedeteksi pas ditutup, cek "
                "izin Autostart & Baterai tanpa batasan di "
                "pengaturan HP untuk app ini."
            ),
            font_size="14sp",
            color=MUTED_COLOR,
            halign="center",
            valign="middle",
        )
        info.bind(size=lambda inst, s: setattr(inst, "text_size", (s[0] * 0.9, s[1])))
        info_card.add_widget(info)
        self.add_widget(info_card)

        Clock.schedule_interval(self.refresh_status, 1.0)

    def set_status_text(self, text, state="idle"):
        dot = {"idle": MUTED_HEX, "listening": GREEN_HEX, "alert": RED_HEX}.get(state, MUTED_HEX)
        self.status_label.text = f"[color={dot}]\u25cf[/color]  Status: {text}"

    def _status_state(self, text):
        lower = text.lower()
        if "berhenti" in lower:
            return "idle"
        if any(k in lower for k in ("gagal", "error", "tidak merespon", "ditolak")):
            return "alert"
        if "terdeteksi" in lower:
            return "alert"
        return "listening"

    def on_slider_change(self, instance, value):
        self.threshold = int(value)
        self.sensitivity_label.text = f"Sensitivitas: {self.threshold}"
        if self.running:
            write_control(self.threshold, False)

    def on_toggle(self, instance):
        if not self.running:
            self.start_service()
        else:
            self.stop_service()

    def start_service(self):
        if IS_ANDROID and not check_permission(Permission.RECORD_AUDIO):
            def callback(permissions, results):
                if all(results):
                    self._start()
                else:
                    self.set_status_text("izin mic ditolak", "alert")

            request_permissions([Permission.RECORD_AUDIO], callback)
            return

        self._start()

    def _start(self):
        write_control(self.threshold, False)
        if IS_ANDROID:
            try:
                service_cls = autoclass(SERVICE_CLASS)
                mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
                service_cls.start(mActivity, "")
            except Exception as exc:
                self.set_status_text(f"GAGAL start service - {exc}", "alert")
                return
        self.running = True
        self.stop_requested_at = 0
        self.toggle_btn.set_text("Berhenti")
        self.toggle_btn.set_bg_color(RED)
        self.set_status_text("menyiapkan...", "listening")
        self.peak_card.set_value("-")
        self.count_card.set_value("0x")

    def stop_service(self):
        write_control(self.threshold, True)
        if IS_ANDROID:
            try:
                service_cls = autoclass(SERVICE_CLASS)
                mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
                service_cls.stop(mActivity)
            except Exception:
                pass
        self.running = False
        self.stop_requested_at = time.time()
        self.toggle_btn.set_text("Mulai (Background)")
        self.toggle_btn.set_bg_color(GREEN)
        self.set_status_text("berhenti", "idle")

    def refresh_status(self, dt):
        status = read_status()
        if status is None:
            return

        if self.stop_requested_at and (time.time() - self.stop_requested_at) < STALE_AFTER:
            return

        ts = status.get("timestamp", 0)
        age = time.time() - ts

        if self.running and age > STALE_AFTER:
            self.set_status_text(f"service tidak merespon ({int(age)} detik lalu)", "alert")
            return

        text = status.get("status", "-")
        self.set_status_text(text, self._status_state(text))
        self.peak_card.set_value(str(status.get("overall_max", 0)))
        self.count_card.set_value(f"{status.get('clap_count', 0)}x")

        if status.get("status") not in (None, "berhenti") and not self.running and age <= STALE_AFTER:
            self.running = True
            self.toggle_btn.set_text("Berhenti")
            self.toggle_btn.set_bg_color(RED)


class CariHPApp(App):
    def build(self):
        self.title = "Cari HP"
        return FinderUI()


if __name__ == "__main__":
    CariHPApp().run()
