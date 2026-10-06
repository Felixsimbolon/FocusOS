# Yang masih perlu dilengkapi untuk FocusOS pribadi

Update: 7 Oktober 2026. Catatan September pada implementation log adalah riwayat, bukan kondisi env terbaru. Audit **nama** env API produksi hari ini memastikan Gemini, Google client, keyring enkripsi, Supabase secret, URL dan publishable key sudah ada. Tidak ada nilai secret yang diekspor. Migration queue dan lifecycle sudah diterapkan; API dan web terbaru sudah READY; 20 pemeriksaan produksi anonim lulus. Hasil lengkap ada pada implementation log.

## Setup yang masih perlu kamu lengkapi

### 1. Scheduler untuk pemulihan job saat host berhenti

Pemrosesan segera berjalan setelah response lewat server web. Untuk retry yang tidak bergantung halaman dibuka kembali, lengkapi `FOCUSOS_WORKER_SECRET` pada API Vercel dan GitHub Actions dengan nilai yang sama, serta variable repo `FOCUSOS_API_URL`. Panduan klik dan perintah ada di [personal-product-setup.md](personal-product-setup.md). Workflow disertakan tetapi tidak aktif memproses tanpa setting ini.

Secret pemicu ini **baru**; berbeda dari Gemini API key dan key enkripsi. API tetap bisa menjalankan job milik sesi terverifikasi tanpa secret scheduler. GitHub schedule bersifat best effort; sesi job tetap maksimal 15 menit. Sistem tidak mengklaim sinkronisasi Gmail terus-menerus tanpa login.

### 2. Evaluasi Gemini dengan runner lokal

Key Gemini produksi sudah terpasang di Vercel, tetapi tidak tersedia di proses atau file env backend lokal yang diperiksa. Agar evaluasi sintetis live dapat dijalankan otomatis, set `GEMINI_API_KEY` secara privat pada terminal runner atau env backend lokal. Jangan kirim key ke chat.

```powershell
.\.venv\Scripts\python.exe evals/planning_eval.py --live
.\.venv\Scripts\python.exe evals/run.py --live
.\.venv\Scripts\python.exe evals/score.py
```

Hasil mock adalah bukti regresi backend, bukan skor akurasi model live. Evaluator tidak membuat event Calendar nyata. Secret produksi tidak diekspor ke komputer untuk mengambil key tersebut.

### 3. Acceptance Google dengan sesi akun uji

Kode dan provider adapter diuji otomatis memakai data sintetis. OAuth reconnect, pemrosesan Gmail dan Calendar nyata pada rilis baru belum diuji dengan sesi akun terhubung. Sebelum menyatakan acceptance live, perlukan sesi akun uji berlabel FocusOS dan consent Calendar write yang aktif; Google test-mode dapat membutuhkan reconnect.

Yang perlu dibuktikan: email sintetis menjadi task dan fakta; pertanyaan positif/negatif memory sesuai; plan membuat satu event; replay tetap satu; cancel FocusOS block tercatat cancelled; event yang diedit di Google dibiarkan berubah; disconnect menghentikan pekerjaan baru. Tidak perlu membaca email pribadi atau mengubah event selain test FocusOS.

### 4. Recovery database penuh

Export aplikasi tersedia dan validator offline disertakan. Export dibatasi 1000 baris per tabel/8 MB dan menyatakan truncation. File ini bukan backup lengkap Supabase Auth atau credential Google. Untuk disaster recovery, simpan backup database privat dan uji restore pada project terpisah; OAuth reconnect dan indexing ulang tetap diperlukan. Restore penuh belum diuji pada sesi ini. Jangan restore audit Calendar menjadi event baru.

## Batas produk yang disengaja

- Planning horizon tujuh hari, 20 task pada konteks agent; workspace menampilkan maksimum 100 task per status, memori library 50 terbaru, focus block 100 terbaru, run/job history 50 terbaru. Memory search memakai retrieval database, bukan hanya library yang terlihat.
- Reschedule memakai cancel yang sudah dikonfirmasi lalu plan baru. Tidak ada overwrite event Google yang diedit manual.
- Tidak ada push notification, Gmail watch atau job baru berkala tanpa sesi. In-app deadline dan status tetap tersedia.
- Cancel job menghentikan langkah berikutnya; request provider yang sudah berjalan mungkin selesai. Hasil nyata tetap dilihat di Schedule sebelum replanning.

Rincian perubahan hari 4-14 ada pada [roadmap](personal-product-roadmap.md) dan [panduan setup](personal-product-setup.md). Seluruh pengujian pada sesi ini otomatis; tidak meminta pengguna melakukan tes manual untuk menyelesaikan implementasi.
