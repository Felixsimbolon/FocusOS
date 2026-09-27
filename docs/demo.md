# Demo FocusOS — Phase 9

## Status yang dapat diklaim

Kode Phase 1–9, migration database, tes sintetis/provider-mock, dan deploy web/API tersedia. [Laporan evaluasi](evaluation.md) saat ini **belum memuat skor model live** karena `GEMINI_API_KEY` tidak ada di environment produksi/lokal saat evaluasi. Login Supabase production pernah diverifikasi di Phase 1; login ulang dan alur Google integration pada rilis ini belum teruji. Satu event Calendar nyata belum dibuat/diamati melalui alur approval. Jangan menyebut MVP end-to-end diterima sampai gerbang live itu lulus.

## Akun dan konfigurasi

Tidak perlu akun baru jika project Supabase, Google Cloud, Google AI Studio, dan dua project Vercel yang sudah ada digunakan. Untuk demo live, API memerlukan secret service-role Supabase, keyring enkripsi token, Google OAuth client/redirect allowlist, dan Gemini API key. Web memerlukan Google client ID/state secret selain Supabase/app/API env dasar. Simpan hanya di environment server Vercel yang tepat; [deployment.md](deployment.md) dan [backend/.env.example](../backend/.env.example) menjelaskan nama/formatnya. Aktifkan Gmail API dan Google Calendar API; Google OAuth consent perlu scope Gmail read, Calendar owned read/write dan akun uji bila app masih Testing. Tambahkan callback integrasi web Vercel pada OAuth client, serta `/auth/callback` pada Supabase Redirect URLs. Setelah mengubah env, redeploy kedua project. Jangan kirim token/secret lewat chat, screenshot, atau repo.

## Jalur demo sintetis setelah secret tersedia

1. Login ke `https://focusos-web-five.vercel.app`; cek `/api/me` berisi user/profile tanpa token. Simpan zona waktu dan jam kerja di `/settings`.
2. Hubungkan Google di `/settings/connections` dan aktifkan Calendar write scope. Buat label Gmail `FocusOS`, kirim satu email uji berisi tugas/tenggat, lalu gunakan Sync & organize email di `/activity`.
3. Periksa hasil Activity: satu task harus otomatis tersimpan dengan kutipan email yang benar. Email yang hanya berisi instruksi tugas boleh menghasilkan nol memory. Bila extraction gagal atau kutipan salah, catat hasil sebenarnya.
4. Untuk memori, gunakan fakta sintetis yang tersimpan dan sudah di-embed. Tanyakan fakta itu di `/memories`; jawaban utama harus satu fakta yang didukung kutipan dan tautan source. Ajukan juga pertanyaan yang tidak dijawab oleh memori; hasilnya harus menyatakan tidak ada jawaban, bukan memilih fakta yang hanya bertopik mirip. Catat mode semantic atau keyword fallback.
5. Siapkan satu busy event sintetis di primary Calendar. Jalankan `/agent` dengan permintaan menjadwalkan task sebelum tenggat. Satu submit harus menjalankan pembacaan task, Calendar, slot bebas, memory, dan pembuatan blok kerja otomatis. Slot terpilih harus berada dalam jam kerja dan tidak menabrak busy event.
6. Pada halaman run, periksa tanggal, jam, zona waktu, status tiap blok, dan tautan Google Calendar. Buka tautan provider dan cocokkan judul, waktu/zona, serta tamu kosong. Reload run: event tidak boleh terduplikasi. Jika status `unknown`, cek Calendar sebelum percobaan lain.
7. Uji disconnect di Settings; sinkronisasi dan tindakan baru harus tertahan. Reconnect, lalu hapus satu source Gmail sintetis di Activity; pastikan task/memori/embedding dan snapshot run terkait hilang, sementara source/run lain tetap ada. Penghapusan di FocusOS tidak menghapus Gmail atau Google Calendar event.
8. Jalankan `python evals/run.py --live`, review `evals/output/observations.jsonl` (lokal dan di-ignore), catat judgment semantik bila ada, kemudian `python evals/score.py`. Hanya setelah itu publikasikan laporan yang memuat angka live dan versi.

## Verifikasi tanpa secret

Dari repo root: `npm ci`, `npm ci --prefix web`, `python -m venv .venv`, instal `backend` dalam venv, lalu `npm run test:api`, `npm run test:web`, `python -m unittest discover -s evals -p 'test_*.py' -v`, `python evals/safety_gate.py`, `python evals/validate.py`, `python evals/run.py --dry-run`, `python evals/score.py`, dan `npm run build:web`. `python evals/hosted_smoke.py` memeriksa HTTP 200 publik dan HTTP 401 untuk route tanpa sesi, tanpa mengirim credential.

## Batas dan risiko yang perlu ditampilkan

- Evaluasi dry-run tidak mengukur akurasi. Dataset 24 kasus sintetis mencakup 16 kasus extraction dan 8 kasus scheduling/policy; skor extraction tidak mewakili kualitas Gmail nyata.
- Google OAuth/Gmail read scope untuk penggunaan publik memerlukan proses provider tersendiri. FocusOS saat ini cocok untuk akun uji yang diizinkan.
- Tidak ada background worker; Gmail sync dan run agent dilanjutkan secara manual. Cold start/timeout Vercel dapat membuat hasil Google sementara `unknown`, lalu perlu rekonsiliasi stable event ID.
- Body source disimpan maksimal 30 hari dan dibersihkan secara lazy pada request berikutnya, maksimal 100 per panggilan. Task/memori yang sudah dikonfirmasi tetap ada sampai source Gmail terkait dihapus secara eksplisit.
- Disconnect menghapus token FocusOS, bukan mencabut akses di Google Cloud atau menghapus event/provider data. Request yang sudah in-flight mungkin mencapai Google sebelum token hilang; audit akan menjaga hasil yang tidak pasti sebagai `unknown`.


## Bukti rilis otomatis terakhir

GitHub Actions [FocusOS checks — success](https://github.com/Felixsimbolon/FocusOS/actions/runs/36298773031) menjalankan suite tanpa secret. API deployment `dpl_5s6k6nHCXXruEK2puumZz4K81v6f` dan web `dpl_HALEESKPyjPWrgZ635mvG9g3xsHN` READY. Smoke tanpa sesi lulus 7/7; ini belum menggantikan langkah demo login/provider di atas.


Rincian setiap gerbang yang belum lulus, konfigurasi yang masih hilang, dan bukti penerimaannya tersedia di [catatan pekerjaan tersisa](remaining-work.md).
