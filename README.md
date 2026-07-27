# Cari HP (Phone Finder) — Fase 1

Aplikasi kecil untuk membunyikan HP yang sedang mode hening (silent), dengan cara tepuk tangan 2x.

## Cara Kerja

1. Buka app, tap **Mulai Dengarkan**.
2. App mendengarkan lewat mikrofon selama app terbuka/diminimize.
3. Kalau terdeteksi 2 tepukan cepat (dalam ~1.5 detik), app memutar suara alarm bawaan sistem lewat **stream ALARM**. Ini kuncinya: mode hening biasanya cuma membisukan stream Ring & Notifikasi, bukan stream Alarm — makanya suaranya tetap terdengar.
4. Alarm berbunyi ~30 detik lalu berhenti otomatis (atau tap Berhenti).

## Build

Pakai pipeline yang biasa dipakai: push ke GitHub, biarkan GitHub Actions + Buildozer yang compile APK.

Sebelum push, cek `buildozer.spec`:
- `package.domain` — sesuaikan dengan domain yang dipakai di app Sudoku/Tasbih Digital biar konsisten
- `android.api` / `android.minapi` — samakan dengan app lain kalau perlu

## Keterbatasan Fase 1 (penting)

Ini **belum** background service resmi — app harus tetap terbuka atau diminimize (bukan di-force-close) supaya proses dengarnya jalan terus. Ada wake lock (`PARTIAL_WAKE_LOCK`) yang bantu jaga CPU tetap nyala walau layar mati, tapi tetap ada batasnya.

Kalau HP-nya dari brand dengan manajemen baterai galak (Xiaomi/MIUI, Oppo/ColorOS, Vivo/FuntouchOS — banyak dipakai di Indonesia), mungkin perlu whitelist manual di:
Setelan > Baterai > Cari HP > jangan optimasi / izinkan aktif di background.

## Sensitivitas

Ada slider di UI (default 9000, rentang 3000–20000). Kalau alarm suka ke-trigger sendiri karena suara berisik lain, naikkan nilainya. Kalau tepukan gak kedeteksi, turunkan.

## Fase 2 (rencana lanjutan, belum dibangun)

Supaya bisa jalan walau app ditutup total / auto-start pas HP nyala: perlu dijadikan Android Service resmi (`services =` di buildozer.spec) + izin foreground service. Bagian ini lebih rawan gagal di percobaan pertama karena perilakunya beda-beda tiap versi Android/brand HP — makanya sengaja dipisah, supaya logika inti (deteksi tepuk + alarm) bisa dites dulu sebelum nambah kerumitan service.
