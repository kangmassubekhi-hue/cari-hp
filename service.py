"""
Cari HP - Fase 2, background service.
Berjalan sebagai Android Service (foreground service), terpisah dari
main activity, supaya tetap mendengarkan walau app ditutup/layar mati.
"""

import json
import math
import os
import struct
import time
import wave

from jnius import autoclass, cast

AudioRecord = autoclass("android.media.AudioRecord")
AudioFormat = autoclass("android.media.AudioFormat")
MediaRecorder = autoclass("android.media.MediaRecorder")
AudioSource = autoclass("android.media.MediaRecorder$AudioSource")
MediaPlayer = autoclass("android.media.MediaPlayer")
AudioManager = autoclass("android.media.AudioManager")
Context = autoclass("android.content.Context")
PythonService = autoclass("org.kivy.android.PythonService")
NotificationBuilder = autoclass("android.app.Notification$Builder")
NotificationChannel = autoclass("android.app.NotificationChannel")
NotificationManager = autoclass("android.app.NotificationManager")
BuildVersion = autoclass("android.os.Build$VERSION")
PowerManager = autoclass("android.os.PowerManager")

SAMPLE_RATE = 44100
DEFAULT_THRESHOLD = 25000
CLAP_WINDOW = 1.5
CLAP_DEBOUNCE = 0.15
ALARM_DURATION = 30
CHANNEL_ID = "cari_hp_channel"
NOTIF_ID = 1001

service = PythonService.mService
data_dir = service.getFilesDir().getAbsolutePath()
status_path = os.path.join(data_dir, "status.json")
control_path = os.path.join(data_dir, "control.json")
alarm_path = os.path.join(data_dir, "alarm_sound.wav")


def write_status(status, overall_max, clap_count):
    try:
        with open(status_path, "w") as f:
            json.dump({"status": status, "overall_max": overall_max, "clap_count": clap_count}, f)
    except Exception:
        pass


def read_control():
    try:
        with open(control_path, "r") as f:
            return json.load(f)
    except Exception:
        return {"threshold": DEFAULT_THRESHOLD, "should_stop": False}


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
    if not os.path.exists(alarm_path):
        generate_siren_wav(alarm_path)
    return alarm_path


def play_alarm():
    path = ensure_alarm_file()
    audio_manager = cast(AudioManager, service.getSystemService(Context.AUDIO_SERVICE))
    max_vol = audio_manager.getStreamMaxVolume(AudioManager.STREAM_ALARM)
    audio_manager.setStreamVolume(AudioManager.STREAM_ALARM, max_vol, 0)

    player = MediaPlayer()
    player.setAudioStreamType(AudioManager.STREAM_ALARM)
    player.setDataSource(path)
    player.setLooping(True)
    player.prepare()
    player.start()
    return player


def stop_alarm_player(player):
    if player is None:
        return
    try:
        if player.isPlaying():
            player.stop()
        player.release()
    except Exception:
        pass


def start_foreground():
    if BuildVersion.SDK_INT >= 26:
        channel = NotificationChannel(CHANNEL_ID, "Cari HP", NotificationManager.IMPORTANCE_LOW)
        manager = cast(NotificationManager, service.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.createNotificationChannel(channel)
        builder = NotificationBuilder(service, CHANNEL_ID)
    else:
        builder = NotificationBuilder(service)

    builder.setContentTitle("Cari HP aktif")
    builder.setContentText("Mendengarkan tepukan di background")
    builder.setSmallIcon(service.getApplicationInfo().icon)
    service.startForeground(NOTIF_ID, builder.build())


def main():
    write_status("menyiapkan...", 0, 0)

    try:
        start_foreground()
    except Exception as exc:
        write_status(f"ERROR notifikasi - {exc}", 0, 0)
        return

    wake_lock = None
    try:
        power_manager = cast(PowerManager, service.getSystemService(Context.POWER_SERVICE))
        wake_lock = power_manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CariHP::Service")
        wake_lock.acquire()
    except Exception:
        pass

    try:
        channel_config = AudioFormat.CHANNEL_IN_MONO
        audio_format = AudioFormat.ENCODING_PCM_16BIT
        min_buffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, channel_config, audio_format)
        buffer_size = max(min_buffer, 2048)

        audio_record = AudioRecord(AudioSource.MIC, SAMPLE_RATE, channel_config, audio_format, buffer_size)

        if audio_record.getState() != AudioRecord.STATE_INITIALIZED:
            write_status("GAGAL siapkan mic", 0, 0)
            return

        audio_record.startRecording()
    except Exception as exc:
        write_status(f"ERROR - {exc}", 0, 0)
        return

    buf = bytearray(buffer_size)
    last_clap_time = 0.0
    first_clap_time = None
    overall_max = 0
    clap_count = 0
    current_player = None
    alarm_started_at = None
    suppress_until = 0
    last_write = 0

    while True:
        control = read_control()
        if control.get("should_stop"):
            break
        threshold = control.get("threshold", DEFAULT_THRESHOLD)

        try:
            read = audio_record.read(buf, 0, buffer_size)
        except Exception as exc:
            write_status(f"ERROR baca mic - {exc}", overall_max, clap_count)
            time.sleep(1)
            continue

        now = time.time()

        if current_player is not None and alarm_started_at and (now - alarm_started_at) > ALARM_DURATION:
            stop_alarm_player(current_player)
            current_player = None

        if read <= 0:
            continue

        peak = 0
        for i in range(0, read - 1, 2):
            sample = struct.unpack_from("<h", buf, i)[0]
            amp = abs(sample)
            if amp > peak:
                peak = amp

        if peak > overall_max:
            overall_max = peak

        if now - last_write > 2 and now >= suppress_until:
            write_status(f"mendengarkan... level: {peak}", overall_max, clap_count)
            last_write = now

        if peak >= threshold and (now - last_clap_time) > CLAP_DEBOUNCE:
            last_clap_time = now
            if first_clap_time is None or (now - first_clap_time) > CLAP_WINDOW:
                first_clap_time = now
            else:
                first_clap_time = None
                clap_count += 1
                suppress_until = now + 5
                write_status("TERDETEKSI! Alarm bunyi...", overall_max, clap_count)
                stop_alarm_player(current_player)
                try:
                    current_player = play_alarm()
                    alarm_started_at = now
                except Exception as exc:
                    write_status(f"GAGAL alarm - {exc}", overall_max, clap_count)
                    current_player = None

    try:
        audio_record.stop()
        audio_record.release()
    except Exception:
        pass
    stop_alarm_player(current_player)
    if wake_lock:
        try:
            wake_lock.release()
        except Exception:
            pass
    write_status("berhenti", overall_max, clap_count)


main()
