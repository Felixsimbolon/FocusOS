# Menyelesaikan setup produk pribadi

Implementasi hari 4-14 memakai project Supabase, Google Cloud, Gemini dan Vercel yang sama. Tidak membutuhkan Redis atau akun baru untuk fitur yang sudah berjalan. Catatan ini membedakan pekerjaan server segera dari scheduler pemulihan.

## Background job

Antrean ada di `work_jobs`. Payload berisi ID, checkpoint, hasil ringkas dan status. JWT sesi pengguna disimpan terpisah di schema private, dienkripsi AES-GCM dengan domain job dan ID yang terikat. Key memakai `FOCUSOS_TOKEN_ENCRYPTION_KEYS` dan versi aktif yang sudah ada. Credential dihapus setelah job selesai/gagal/dibatalkan; sweep worker menghapus credential job kedaluwarsa. Tidak ada refresh token Supabase yang disimpan.

Job maksimal 15 menit atau umur sesi, mana yang lebih pendek; satu lease 180 detik, maksimum 64 langkah dan lima kegagalan retry. User tetap diverifikasi tiap claim. Server web menjalankan job setelah response lewat Next.js `after`, maksimal 200 detik dalam invocation 240 detik. Ini membuat pekerjaan tidak tergantung tab browser yang masih terbuka, tetapi crash host atau backoff lama membutuhkan pemicu berikutnya.

Jika System menunjukkan queue/lifecycle belum siap, jalankan `npx supabase db push --linked` dari root repo. Untuk env backend, gunakan key Supabase secret/server, Gemini key, keyring enkripsi dan Google client yang sama dengan lokal. Jangan menaruh server secret pada variabel `NEXT_PUBLIC_*`.

## Scheduler pemulihan

Scheduler GitHub yang disertakan bersifat best effort, bukan jaminan tepat setiap lima menit. Tanpa dua setting berikut, workflow hanya memberi status bahwa scheduler belum dikonfigurasi. Pemrosesan segera dari web tetap dapat berjalan.

1. Buat secret acak minimal 32 karakter di komputer pribadi. Contoh PowerShell: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Simpan di password manager; jangan kirim ke chat.
2. Vercel project **focusos-api** > Settings > Environment Variables: tambahkan `FOCUSOS_WORKER_SECRET`, pilih Production, lalu redeploy API.
3. Repo GitHub > Settings > Secrets and variables > Actions > Secrets: tambahkan secret `FOCUSOS_WORKER_SECRET` dengan nilai **yang sama**.
4. Di tab Variables: tambahkan `FOCUSOS_API_URL=https://focusos-api.vercel.app`.
5. Actions > Resume FocusOS jobs > Run workflow. Workflow mengirim Bearer secret ke `/internal/jobs/tick`, maksimal 20 langkah dan tanpa log token.
6. System menampilkan `Scheduler trigger: configured` bila API mempunyai secret; itu belum membuktikan GitHub berhasil memanggilnya. Bukti scheduler ada pada run Actions dan job yang benar-benar maju.

Untuk pengujian lokal: set kedua env di terminal privat, lalu `python scripts/work_jobs.py`. Gunakan URL API lokal. Jika sesi job kedaluwarsa, login dan submit lagi; lihat Schedule sebelum replanning karena sebagian event mungkin sudah berhasil dibuat.

Ini bukan Gmail push/watch atau sync harian permanen tanpa sesi pengguna. Job Gmail hanya memproses email berlabel FocusOS dalam jendela sesi pendek. Scheduler dapat melanjutkan job yang sudah ada, tetapi tidak membuat sesi login baru.

## Calendar

Schedule menampilkan maksimal 100 action tersimpan. Cancel block hanya berlaku untuk event sukses yang disimpan FocusOS. Backend membaca ID stabil, memeriksa marker, konten dan waktu, lalu DELETE memakai ETag/If-Match dan `sendUpdates=none`. Event yang diedit di Google tidak dihapus otomatis. Timeout ditampilkan unknown; retry merekonsiliasi ID yang sama. Pembatalan tidak menyelesaikan task. Untuk pindah waktu, batalkan block, tunggu cancelled, lalu submit plan baru.

## Backup dan recovery

System > Export my data mengunduh JSON maksimal 1000 baris per tabel dan 8 MB. File berisi teks sumber, task, project, fakta/evidence, preferensi dan catatan action; tidak mencakup credential, vektor embedding atau queue token. Ini salinan data aplikasi, bukan dump penuh PostgreSQL. Simpan privat. Jika ada tabel truncated, gunakan backup database untuk pemulihan lengkap.

Validasi offline: `python scripts/validate_export.py <path-ke-export.json>`. Validasi tidak membuat data atau event. Untuk recovery penuh, buat dan uji backup Supabase/database pada project terpisah; jangan restore langsung ke project aktif tanpa memeriksa pemetaan user ID dan foreign key. OAuth perlu reconnect dan embedding perlu dibangun kembali. Catatan Calendar pada backup tidak boleh dieksekusi kembali sebagai event baru.

Restore database penuh dan pemulihan provider akun live belum dianggap terbukti oleh export validator. Sesi serta identitas tetap dikelola Supabase Auth.
