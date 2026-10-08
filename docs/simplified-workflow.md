# FocusOS: satu input untuk kerja dan kalender

## Alur pengguna setelah perubahan 8 Oktober 2026

Home adalah tempat bekerja. Tidak perlu berpindah ke Activity atau Planning untuk memasukkan pekerjaan. Satu textbox menerima bahasa Indonesia atau Inggris; pengguna tidak memilih jenis input melalui tombol atau dropdown.

- **Task atau catatan:** "Siapkan checklist demo sebelum Jumat pukul 17.00 WIB. Estimasi 30 menit. Audiens demo adalah backend engineers." Sistem menyimpan sumber, mengekstrak task dan fakta, menyimpan memori berbukti termasuk memori task, lalu mengindeksnya untuk pencarian. Deadline saja tidak membuat event.
- **Jadwal tanpa task:** "Cari waktu besok antara jam 13 sampai 16 untuk belajar Python selama 45 menit." Sistem mencari waktu kosong dalam jam kerja, memeriksa Calendar kembali, lalu membuat event. Tidak membuat source, task, atau memori task yang tidak diminta. Hasil menampilkan tanggal, jam, zona waktu, dan link Calendar.
- **Task sekaligus jadwal:** "Buat task siapkan checklist demo, estimasi 30 menit, sekaligus jadwalkan besok antara jam 10 sampai 12." Task/memori disimpan dahulu, kemudian hanya task dari sumber ini yang dijadwalkan. Kegagalan tahap Calendar tidak menyembunyikan task yang sudah tersimpan.
- **Task yang sudah ada:** "Jadwalkan task checklist demo yang sudah ada selama 30 menit besok antara jam 10 sampai 12." Inferensi memilih referensi dari task aktif pengguna; tidak menambah task duplikat. Referensi yang ambigu atau tidak ditemukan menghasilkan alert.
- **Gmail:** tombol Sync Gmail pada header tetap terlihat saat scroll. Sekali klik menyinkronkan email berlabel FocusOS sampai task dan memori tersimpan. Tidak ada halaman job atau tombol process/extract/confirm bertahap. Jika tidak ada email baru, label tidak ada, atau email tidak berisi task/fakta, UI memberi notifikasi yang sesuai.

Task Today dan deadline mendatang tetap tersedia, termasuk edit judul, complete, urutan urgency/deadline, dan pagination. Search memory, Scheduled work, sumber/evidence, dan Preferences ada di Home. URL Activity dan Agent lama mengarah ke bagian Home; permalink run lama dipertahankan untuk kompatibilitas. Google connection tetap tersedia untuk consent dan pengelolaan koneksi.

## Pendekatan teknis dan alasan

POST /api/commands menerima hanya teks dan request_key, memverifikasi sesi di Next.js, lalu meneruskan JWT hanya dari server ke POST /commands FastAPI. Antrean planning yang sudah ada dipakai untuk proses terpadu; tidak menambah sistem worker atau secret baru.

Gemini mengembalikan WorkIntent dengan action capture/schedule/both/clarify dan PlanningSelection yang sempit. Model boleh memilih handle task yang diberikan, tetapi tidak memilih ID database, membuat timestamp event, atau menulis Calendar langsung. Judul aktivitas baru harus berupa kutipan dari input; referensi tidak dikenal atau evidence buatan ditolak. Instruksi membuat task bersama jadwal harus eksplisit; deadline tidak disamakan dengan event.

Backend menghitung slot secara deterministik dari snapshot Calendar dan working hours. Durasi, hari sederhana, ISO date, dan rentang jam 24-hour yang jelas ditambatkan ke teks asli secara independen dari model. Pilihan model tidak dapat menghapus rentang "antara jam 13 sampai 16". Plan baru tetap memakai buffer lima menit, slot utuh minimal 15 menit, serta horizon tujuh hari. Jika durasi tidak disebut, memakai estimasi task atau 30 menit; default dijelaskan pada composer. Deadline hanya tanggal berarti akhir hari dalam zona waktu preferensi pengguna.

Untuk aktivitas tanpa task, compiler memakai deskripsi sementara, lalu menyimpan Calendar action dengan task_id/task_version/source_id null. Tidak membuat task palsu di database. Migration 20261008090000_unified_calendar.sql melonggarkan task_id menjadi nullable dan memperluas proposal/trigger; run, connection, owner, judul yang bersumber dari input, saved slot, payload hash, dan stable event ID tetap diperiksa. Task biasa tetap tunduk pada foreign key owner dan version check.

Sebelum menulis event, backend memeriksa kembali grant Google, timezone/jam kerja, perubahan task atau aktivitas, deadline, dan Calendar terbaru. Retry membaca stable event ID dan merekonsiliasi timeout agar tidak menyisipkan event ganda. Jika tidak ada slot, grant hilang, atau request tidak jelas, UI memberi alert; hasil parsial tetap terlihat.

Proses capture menyimpan checkpoint source dan key konfirmasi deterministik. Proses indexing selesai sebelum capture dilabeli succeeded. Refresh Home memulihkan observasi job aktif; browser hanya membaca status dan meminta server melanjutkan saat siap, tanpa menggerakkan tiap langkah secara manual. Worker dan backoff tetap internal.

## Setup dan batas praktis

Tidak ada env atau akun baru. Tetap memakai Gemini, Supabase, dan koneksi Google yang sudah dikonfigurasi. Penjadwalan memerlukan Calendar event write consent dan Preferences jam kerja. Migration baru harus diterapkan sebelum backend baru digunakan. Backup/restore tetap di luar scope sesuai keputusan pengguna.

Textbox saat ini menerima maksimal 1.000 karakter. Planning memilih dari maksimal 20 task aktif terbaru, menggunakan primary Calendar, satu hari/rentang dalam tujuh hari, dan blok utuh 15-480 menit. Request recurring, guests, timezone berbeda, atau exact-time-only yang tidak didukung menghasilkan alert; tidak diam-diam diubah. Kuota provider tetap berlaku. Tidak ada klaim akurasi intent Gemini live dari tes dengan respons sintetis.

## Pengujian otomatis

334 tes backend dan 111 tes frontend lulus sebelum rilis. Workflow sintetis memverifikasi task-only, standalone schedule tanpa source/task, both, task yang sudah ada, slot tidak cukup, perubahan busy event saat eksekusi, indexing, hasil parsial, dan timeout/replay tanpa duplikasi. Proxy memverifikasi autentikasi, validasi input, token server-only, dan pekerjaan setelah response. Tes SQL memakai user sintetis dalam transaksi rollback: proposal tanpa task, judul yang tidak bersumber, slot palsu, isolasi owner, automatic authorization, replay, dan batas deadline tanggal.

Build Next.js/TypeScript lulus. Layout sintetis ditinjau dengan Chrome headless pada viewport desktop dan ponsel; viewport 390px tidak overflow horizontal. Tes tersebut tidak membaca Gmail pengguna atau membuat event Google Calendar nyata. Hasil migration dan deploy dicatat di implementation-log.md setelah rilis.
