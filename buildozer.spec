[app]
title = Cari HP
package.name = phonefinder
package.domain = org.subehiahmad
icon.filename = %(source.dir)s/icon.png

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 0.1

requirements = python3,kivy,pyjnius

orientation = portrait
fullscreen = 0

android.permissions = RECORD_AUDIO, WAKE_LOCK, MODIFY_AUDIO_SETTINGS, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, POST_NOTIFICATIONS, VIBRATE

services = Listener:service.py

android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
