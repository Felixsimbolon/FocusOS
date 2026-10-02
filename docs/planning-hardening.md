# Penguatan planning: hari 1-3

Tanggal: 2 Oktober 2026. Scope: perbaikan planning dan pengujian otomatis untuk penggunaan pribadi. Tidak menambah worker, scheduled sync, atau fitur lifecycle Calendar pada tahap ini.

## Hari 1: diagnosis dan aturan input

Pemeriksaan kode dan reproduksi otomatis menunjukkan beberapa kelas kegagalan; ini bukan penetapan akar masalah untuk satu run produksi yang lognya belum tersedia:

- Form memakai default 60 menit meskipun instruksi meminta 30 menit.
- Free-time stage memilih slot awal sebelum hari yang diminta diterapkan dan tanpa deadline task.
- Output Gemini harus menyalin judul persis dan mengembalikan total menit yang konsisten. Judul task diperbolehkan sampai 200 karakter, tetapi kontrak model lama membatasi 120.
- Slot bisa dimulai pada waktu request awal, sehingga sudah lewat ketika alur berikutnya mencoba membuat event.
- Fragmen split bisa lebih pendek dari batas 15 menit CalendarAction.
- Run kedaluwarsa masih bisa masuk ke tahap model; SQL memang melarang checkpoint setelah expiry.

Aturan baru: field durasi opsional. Durasi eksplisit pada instruksi atau field digunakan; jika keduanya ada dan berbeda, kembalikan clarification. Jika tidak ada keduanya, gunakan estimasi task; estimasi yang tidak tersedia menghasilkan clarification. Permintaan hari dan waktu berlaku dalam timezone profil. Deadline date-only membutuhkan jam yang jelas. Deadline lewat, waktu tidak cukup, atau konteks berubah harus menghasilkan pesan yang dapat ditindaklanjuti.

## Hari 2: implementasi

`agent_planner.py` sekarang meminta selection terstruktur: referensi task, durasi eksplisit, hari/tanggal, batas jam, referensi memori, atau pertanyaan klarifikasi. Model tidak lagi menulis judul, slot, timestamp event, atau total menit. Prompt dan selection schema memiliki versi yang dicatat evaluator.

`planning_request.py` mendasarkan constraint sederhana pada instruksi asli, seperti 30 minutes, setengah jam, tomorrow/besok, dan tanggal ISO yang diminta. Judul dalam tanda kutip tidak dianggap sebagai constraint. Constraint yang ambigu menghasilkan clarification; penafsiran bahasa yang lebih luas tetap melibatkan model.

`planning_compiler.py` mengambil task milik pengguna dan snapshot Calendar yang lengkap, menerapkan hari/jam/deadline, lalu menghitung slot secara deterministik. Awal blok dibulatkan ke menit dan diberi buffer lima menit dari waktu kompilasi. Split block minimal 15 menit. Banyak task memakai estimasi masing-masing, total yang konsisten, serta alokasi tanpa overlap; hasil yang tidak lengkap tidak diteruskan untuk penulisan event.

Hasil memakai kontrak plan tersimpan yang sama, termasuk `free_time.slots`, sehingga tidak membutuhkan migration baru. Judul dan ID berasal dari task server. Pemeriksaan referensi, bukti memori, deadline, durasi, kepemilikan, revalidation Calendar, stable event ID, dan idempotency tetap berlaku. Expiry diturunkan dari timestamp tersimpan, tanpa mencoba SQL update yang dilarang setelah expiry.

Frontend mengosongkan durasi default dan memberi label override opsional, menampilkan asumsi durasi, serta menerjemahkan kode kegagalan yang dikenal. Pengulangan request key dengan options berbeda menjadi 409. Alur automatic Calendar tetap mengikuti pilihan pengguna; tidak ada langkah persetujuan baru.

## Hari 3: pengujian otomatis

- Unit/regression tests memeriksa 30/60 menit, fallback estimasi, konflik input, timezone dan besok, batas jam, deadline lengkap/date-only/lewat, Calendar penuh, split minimum, banyak task, referensi palsu, schema salah, dan expiry.
- Workflow tests menjalankan extraction dari source email sintetis, automatic capture, embedding, memory search, staged planning lewat FastAPI, dan jalur penulisan Calendar. Database dan respons provider disimulasikan pada batas integrasi; data pribadi tidak diakses.
- Replay request/event, perubahan Calendar/task sebelum eksekusi, dan timeout setelah provider menerima insert memastikan event tetap tunggal atau tindakan ditolak dengan alasan yang benar.
- `evals/planning_eval.py --mock` adalah regression backend dengan fixture selection, bukan ukuran akurasi Gemini. `--live` memanggil Gemini dengan data sintetis dan Calendar sintetis; kedua mode tidak menulis Calendar sungguhan.
- CI menjalankan evaluator mock dan safety gate yang mencakup compiler serta workflow baru.

Perintah lokal:

```powershell
npm.cmd run test:api
npm.cmd run test:web
.\.venv\Scripts\python.exe -m unittest discover -s evals -p 'test_*.py' -v
.\.venv\Scripts\python.exe evals/planning_eval.py --mock
.\.venv\Scripts\python.exe evals/safety_gate.py
.\web\node_modules\.bin\tsc.cmd --noEmit -p web/tsconfig.json
npm.cmd run build:web
```

Untuk evaluasi model live, sediakan `GEMINI_API_KEY` di proses backend secara privat, lalu jalankan `python evals/planning_eval.py --live`. Laporan masuk `evals/output/planning.json`, yang sudah di-ignore. Sukses pengujian mock tidak membuktikan kualitas provider live atau konfigurasi akun produksi.

## Batasan

Horizon planning tetap tujuh hari dan task retrieval dibatasi 20 task aktif. Model masih bisa meminta clarification atau gagal saat memahami permintaan; backend tidak meneruskan hasil tersebut menjadi event. Ini belum menambahkan background worker: browser masih menggerakkan kelanjutan proses, sesuai scope hari 6-8. Proses deployment dan hasil verifikasi final dicatat dalam implementation log.


## Hasil rilis

Implementasi `9598a43` sudah di-push dan kedua project Vercel mencapai READY pada 2 Oktober 2026. Smoke produksi anonim lulus 7/7; kontrak durasi opsional juga terverifikasi dari OpenAPI produksi. Tidak dibutuhkan env baru atau migration. Rincian deployment ada di implementation log.

Evaluasi Gemini live masih belum diuji karena key tidak tersedia di runner lokal dan review persetujuan otomatis menolak ekspor seluruh env produksi. Semua pengujian workflow memakai data sintetis dan respons provider yang disimulasikan; tidak ada email pribadi yang dibaca atau event Calendar nyata yang dibuat.
