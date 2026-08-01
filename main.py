"""
Cari HP (Phone Finder) - Fase 2 (background service)
"""

import json
import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.utils import platform

IS_ANDROID = platform == "android"
DEFAULT_THRESHOLD = 25000
SERVICE_CLASS = "org.subehiahmad.phonefinder.ServiceListener"
STALE_AFTER = 10  # detik - anggap service mati kalau gak update status selama ini

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


class FinderUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=24, spacing=16, **kwargs)
        self.running = False
        self.stop_requested_at = 0
        self.threshold = DEFAULT_THRESHOLD

        self.status_label = Label(text="Status: berhenti", font_size="20sp", halign="center")
        self.status_label.bind(
            width=lambda inst, w: setattr(inst, "text_size", (w * 0.9, None))
        )
        self.add_widget(self.status_label)

        self.peak_label = Label(
            text="Puncak tertinggi sesi ini: -", font_size="18sp", color=(1, 1, 0, 1)
        )
        self.add_widget(self.peak_label)

        self.count_label = Label(text="Terdeteksi: 0x", font_size="18sp", color=(1, 1, 0, 1))
        self.add_widget(self.count_label)

        self.sensitivity_label = Label(text=f"Sensitivitas: {self.threshold}")
        self.add_widget(self.sensitivity_label)

        slider = Slider(min=10000, max=30000, value=self.threshold, step=500)
        slider.bind(value=self.on_slider_change)
        self.add_widget(slider)

        self.toggle_btn = Button(text="Mulai (Background)", font_size="22sp", size_hint=(1, 0.3))
        self.toggle_btn.bind(on_release=self.on_toggle)
        self.add_widget(self.toggle_btn)

        info = Label(
            text=(
                "Fase 2: jalan walau app ditutup/layar mati.\n"
                "Kalau tetap gak kedeteksi pas ditutup, cek\n"
                "izin Autostart & Baterai tanpa batasan di\n"
                "pengaturan HP untuk app ini."
            ),
            font_size="14sp",
        )
        self.add_widget(info)

        Clock.schedule_interval(self.refresh_status, 1.0)

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
                    self.status_label.text = "Status: izin mic ditolak"

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
                self.status_label.text = f"Status: GAGAL start service - {exc}"
                return
        self.running = True
        self.stop_requested_at = 0
        self.toggle_btn.text = "Berhenti"
        self.status_label.text = "Status: menyiapkan..."
        self.peak_label.text = "Puncak tertinggi sesi ini: -"
        self.count_label.text = "Terdeteksi: 0x"

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
        self.toggle_btn.text = "Mulai (Background)"
        self.status_label.text = "Status: berhenti"

    def refresh_status(self, dt):
        status = read_status()
        if status is None:
            return

        if self.stop_requested_at and (time.time() - self.stop_requested_at) < STALE_AFTER:
            return

        ts = status.get("timestamp", 0)
        age = time.time() - ts

        if self.running and age > STALE_AFTER:
            self.status_label.text = f"Status: service tidak merespon ({int(age)} detik lalu)"
            return

        self.status_label.text = f"Status: {status.get('status', '-')}"
        self.peak_label.text = f"Puncak tertinggi sesi ini: {status.get('overall_max', 0)}"
        self.count_label.text = f"Terdeteksi: {status.get('clap_count', 0)}x"

        if status.get("status") not in (None, "berhenti") and not self.running and age <= STALE_AFTER:
            self.running = True
            self.toggle_btn.text = "Berhenti"


class CariHPApp(App):
    def build(self):
        self.title = "Cari HP"
        return FinderUI()


if __name__ == "__main__":
    CariHPApp().run()
