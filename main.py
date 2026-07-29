"""
Cari HP (Phone Finder) - Fase 1 (dengan status level suara)
"""

import math
import os
import struct
import threading
import time
import wave

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.utils import platform

IS_ANDROID = platform == "android"

if IS_ANDROID:
    from android.permissions import Permission, check_permission, request_permissions
    from jnius import autoclass, cast

    AudioRecord = autoclass("android.media.AudioRecord")
    AudioFormat = autoclass("android.media.AudioFormat")
    MediaRecorder = autoclass("android.media.MediaRecorder")
    AudioSource = autoclass("android.media.MediaRecorder$AudioSource")
    MediaPlayer = autoclass("android.media.MediaPlayer")
    AudioManager = autoclass("android.media.AudioManager")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    PowerManager = autoclass("android.os.PowerManager")
    Context = autoclass("android.content.Context")


SAMPLE_RATE = 44100
DEFAULT_THRESHOLD = 4500
CLAP_WINDOW = 1.5
CLAP_DEBOUNCE = 0.15
ALARM_DURATION = 30


class ListenerThread(threading.Thread):
    def __init__(self, on_clap_detected, on_status, threshold=DEFAULT_THRESHOLD):
        super().__init__(daemon=True)
        self.on_clap_detected = on_clap_detected
        self.on_status = on_status
        self.threshold = threshold
        self._running = threading.Event()
        self._running.set()
        self.audio_record = None
        self.suppress_until = 0
        self.overall_max = 0
        self.clap_count = 0

    def stop(self):
        self._running.clear()

    def run(self):
        if not IS_ANDROID:
            return

        try:
            channel_config = AudioFormat.CHANNEL_IN_MONO
            audio_format = AudioFormat.ENCODING_PCM_16BIT
            min_buffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, channel_config, audio_format)
            buffer_size = max(min_buffer, 2048)

            self.audio_record = AudioRecord(
                AudioSource.MIC,
                SAMPLE_RATE,
                channel_config,
                audio_format,
                buffer_size,
            )

            if self.audio_record.getState() != AudioRecord.STATE_INITIALIZED:
                self.on_status(f"Status: GAGAL siapkan mic (state={self.audio_record.getState()})")
                return

            self.audio_record.startRecording()

            if self.audio_record.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING:
                self.on_status("Status: GAGAL mulai rekam")
                return

        except Exception as exc:
            self.on_status(f"Status: ERROR - {exc}")
            return

        buf = bytearray(buffer_size)
        last_clap_time = 0.0
        first_clap_time = None
        loop_count = 0
        recent_max = 0

        while self._running.is_set():
            try:
                read = self.audio_record.read(buf, 0, buffer_size)
            except Exception as exc:
                self.on_status(f"Status: ERROR baca mic - {exc}")
                return

            if read <= 0:
                continue

            loop_count += 1

            peak = 0
            for i in range(0, read - 1, 2):
                sample = struct.unpack_from("<h", buf, i)[0]
                amp = abs(sample)
                if amp > peak:
                    peak = amp

            if peak > recent_max:
                recent_max = peak
            if peak > self.overall_max:
                self.overall_max = peak

            if loop_count % 8 == 0:
                if time.time() >= self.suppress_until:
                    self.on_status(f"Mendengarkan... puncak baru-baru ini: {recent_max}")
                recent_max = 0

            now = time.time()

            if peak >= self.threshold and (now - last_clap_time) > CLAP_DEBOUNCE:
                last_clap_time = now
                if first_clap_time is None or (now - first_clap_time) > CLAP_WINDOW:
                    first_clap_time = now
                else:
                    first_clap_time = None
                    self.clap_count += 1
                    self.on_clap_detected()

        try:
            self.audio_record.stop()
            self.audio_record.release()
        except Exception:
            pass


def generate_siren_wav(path):
    sample_rate = 44100
    duration = 3.0
    freq_low, freq_high = 600, 1000
    switch = 0.3
    n_samples = int(sample_rate * duration)
    frames = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        freq = freq_low if (t % (switch * 2)) < switch else freq_high
        val = int(math.sin(2 * math.pi * freq * t) * 32767 * 0.8)
        frames += struct.pack("<h", val)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))


def ensure_alarm_file():
    app = App.get_running_app()
    path = os.path.join(app.user_data_dir, "alarm_sound.wav")
    if not os.path.exists(path):
        generate_siren_wav(path)
    return path


def play_alarm():
    if not IS_ANDROID:
        print("[CariHP] (simulasi) ALARM BERBUNYI!")
        return

    path = ensure_alarm_file()

    activity = PythonActivity.mActivity

    audio_manager = cast(AudioManager, activity.getSystemService(Context.AUDIO_SERVICE))
    max_vol = audio_manager.getStreamMaxVolume(AudioManager.STREAM_ALARM)
    audio_manager.setStreamVolume(AudioManager.STREAM_ALARM, max_vol, 0)

    player = MediaPlayer()
    player.setAudioStreamType(AudioManager.STREAM_ALARM)
    player.setDataSource(path)
    player.setLooping(True)
    player.prepare()
    player.start()

    def stop_player(dt):
        try:
            if player.isPlaying():
                player.stop()
            player.release()
        except Exception:
            pass

    Clock.schedule_once(stop_player, ALARM_DURATION)


class FinderUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=24, spacing=16, **kwargs)
        self.listener = None
        self.wake_lock = None
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

        self.count_label = Label(
            text="Terdeteksi: 0x", font_size="18sp", color=(1, 1, 0, 1)
        )
        self.add_widget(self.count_label)

        self.sensitivity_label = Label(text=f"Sensitivitas: {self.threshold}")
        self.add_widget(self.sensitivity_label)

        slider = Slider(min=1000, max=15000, value=self.threshold, step=500)
        slider.bind(value=self.on_slider_change)
        self.add_widget(slider)

        self.toggle_btn = Button(text="Mulai Dengarkan", font_size="22sp", size_hint=(1, 0.3))
        self.toggle_btn.bind(on_release=self.on_toggle)
        self.add_widget(self.toggle_btn)

        info = Label(
            text=(
                "Perhatikan angka 'level' di status.\n"
                "Kalau angkanya diam terus walau ada suara,\n"
                "berarti mic-nya yang bermasalah."
            ),
            font_size="14sp",
        )
        self.add_widget(info)

    def on_slider_change(self, instance, value):
        self.threshold = int(value)
        self.sensitivity_label.text = f"Sensitivitas: {self.threshold}"
        if self.listener:
            self.listener.threshold = self.threshold

    def on_toggle(self, instance):
        if self.listener is None:
            self.start_listening()
        else:
            self.stop_listening()

    def start_listening(self):
        if IS_ANDROID and not check_permission(Permission.RECORD_AUDIO):
            def callback(permissions, results):
                if all(results):
                    self._start_thread()
                else:
                    self.status_label.text = "Status: izin mic ditolak"

            request_permissions([Permission.RECORD_AUDIO], callback)
            return

        self._start_thread()

    def _start_thread(self):
        if IS_ANDROID:
            activity = PythonActivity.mActivity
            power_manager = cast(PowerManager, activity.getSystemService(Context.POWER_SERVICE))
            self.wake_lock = power_manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CariHP::Listener")
            self.wake_lock.acquire()

        self.listener = ListenerThread(self.on_clap, self.set_status, threshold=self.threshold)
        self.listener.start()
        self.status_label.text = "Status: menyiapkan mic..."
        self.toggle_btn.text = "Berhenti"
        self.peak_label.text = "Puncak tertinggi sesi ini: -"
        self.count_label.text = "Terdeteksi: 0x"
        Clock.schedule_interval(self.refresh_stats, 0.5)

    def refresh_stats(self, dt):
        if not self.listener:
            return False
        self.peak_label.text = f"Puncak tertinggi sesi ini: {self.listener.overall_max}"
        self.count_label.text = f"Terdeteksi: {self.listener.clap_count}x"

    @mainthread
    def set_status(self, text):
        self.status_label.text = text

    def stop_listening(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        if self.wake_lock:
            try:
                self.wake_lock.release()
            except Exception:
                pass
            self.wake_lock = None
        self.status_label.text = "Status: berhenti"
        self.toggle_btn.text = "Mulai Dengarkan"

    @mainthread
    def on_clap(self):
        if self.listener:
            self.listener.suppress_until = time.time() + 5
        try:
            play_alarm()
            self.status_label.text = "Status: TERDETEKSI! Alarm bunyi..."
        except Exception as exc:
            self.status_label.text = f"Status: GAGAL alarm - {exc}"
        Clock.schedule_once(
            lambda dt: setattr(self.status_label, "text", "Status: mendengarkan..."),
            ALARM_DURATION,
        )


class CariHPApp(App):
    def build(self):
        self.title = "Cari HP"
        return FinderUI()


if __name__ == "__main__":
    CariHPApp().run()
