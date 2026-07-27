"""
Cari HP (Phone Finder) - Fase 1
Dengarkan tepukan tangan lewat mic, lalu bunyikan alarm keras
lewat stream ALARM (nembus mode hening/silent).
"""

import struct
import threading
import time

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
    MediaPlayer = autoclass("android.media.MediaPlayer")
    AudioManager = autoclass("android.media.AudioManager")
    RingtoneManager = autoclass("android.media.RingtoneManager")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    PowerManager = autoclass("android.os.PowerManager")
    Context = autoclass("android.content.Context")


SAMPLE_RATE = 44100
DEFAULT_THRESHOLD = 9000   # ambang volume deteksi tepukan (0-32767)
CLAP_WINDOW = 1.5          # jeda maksimal antar tepukan 1 & 2 (detik)
CLAP_DEBOUNCE = 0.15       # jeda minimal biar 1 tepukan gak kehitung dobel
ALARM_DURATION = 30        # lama alarm berbunyi (detik)


class ListenerThread(threading.Thread):
    """Terus mendengarkan lewat mic, deteksi pola tepuk 2x berturut-turut."""

    def __init__(self, on_clap_detected, threshold=DEFAULT_THRESHOLD):
        super().__init__(daemon=True)
        self.on_clap_detected = on_clap_detected
        self.threshold = threshold
        self._running = threading.Event()
        self._running.set()
        self.audio_record = None

    def stop(self):
        self._running.clear()

    def run(self):
        if not IS_ANDROID:
            return

        channel_config = AudioFormat.CHANNEL_IN_MONO
        audio_format = AudioFormat.ENCODING_PCM_16BIT
        min_buffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, channel_config, audio_format)
        buffer_size = max(min_buffer, 2048)

        self.audio_record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            channel_config,
            audio_format,
            buffer_size,
        )

        try:
            self.audio_record.startRecording()
        except Exception as exc:
            print(f"[CariHP] Gagal mulai rekam: {exc}")
            return

        buf = bytearray(buffer_size)
        last_clap_time = 0.0
        first_clap_time = None

        while self._running.is_set():
            read = self.audio_record.read(buf, 0, buffer_size)
            if read <= 0:
                continue

            # Cari amplitudo tertinggi di buffer ini (PCM 16-bit signed, little-endian)
            peak = 0
            for i in range(0, read - 1, 2):
                sample = struct.unpack_from("<h", buf, i)[0]
                amp = abs(sample)
                if amp > peak:
                    peak = amp

            now = time.time()

            if peak >= self.threshold and (now - last_clap_time) > CLAP_DEBOUNCE:
                last_clap_time = now
                if first_clap_time is None or (now - first_clap_time) > CLAP_WINDOW:
                    first_clap_time = now  # ini tepukan pertama
                else:
                    first_clap_time = None  # ini tepukan kedua -> trigger
                    self.on_clap_detected()

        try:
            self.audio_record.stop()
            self.audio_record.release()
        except Exception:
            pass


def play_alarm():
    """Putar suara alarm bawaan sistem lewat stream ALARM (nembus mode hening)."""
    if not IS_ANDROID:
        print("[CariHP] (simulasi) ALARM BERBUNYI!")
        return

    activity = PythonActivity.mActivity

    audio_manager = cast(AudioManager, activity.getSystemService(Context.AUDIO_SERVICE))
    max_vol = audio_manager.getStreamMaxVolume(AudioManager.STREAM_ALARM)
    audio_manager.setStreamVolume(AudioManager.STREAM_ALARM, max_vol, 0)

    alarm_uri = RingtoneManager.getActualDefaultRingtoneUri(activity, RingtoneManager.TYPE_ALARM)
    if alarm_uri is None:
        alarm_uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)

    player = MediaPlayer()
    player.setAudioStreamType(AudioManager.STREAM_ALARM)
    player.setDataSource(activity, alarm_uri)
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

        self.status_label = Label(text="Status: berhenti", font_size="20sp")
        self.add_widget(self.status_label)

        self.sensitivity_label = Label(text=f"Sensitivitas: {self.threshold}")
        self.add_widget(self.sensitivity_label)

        slider = Slider(min=3000, max=20000, value=self.threshold, step=500)
        slider.bind(value=self.on_slider_change)
        self.add_widget(slider)

        self.toggle_btn = Button(text="Mulai Dengarkan", font_size="22sp", size_hint=(1, 0.3))
        self.toggle_btn.bind(on_release=self.on_toggle)
        self.add_widget(self.toggle_btn)

        info = Label(
            text=(
                "Tepuk tangan 2x cepat untuk membunyikan alarm.\n"
                "HP tetap bunyi walau mode hening aktif.\n"
                "(Fase 1: jaga app tetap terbuka/diminimize)"
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

        self.listener = ListenerThread(self.on_clap, threshold=self.threshold)
        self.listener.start()
        self.status_label.text = "Status: mendengarkan..."
        self.toggle_btn.text = "Berhenti"

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
        self.status_label.text = "Status: TERDETEKSI! Alarm bunyi..."
        play_alarm()
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
