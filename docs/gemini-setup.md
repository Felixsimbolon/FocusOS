# Mengaktifkan Gemini untuk FocusOS

Backend sekarang memakai Gemini untuk ekstraksi, perencanaan, fungsi baca tugas, dan embedding memori. Frontend tidak membutuhkan Gemini key. Jangan kirim key lewat chat, jangan commit ke Git, dan jangan taruh di variabel browser.

## 1. Key dan akses model

Buat API key di Google AI Studio pada project yang ingin dipakai. Simpan di password manager. Pastikan model generasi gemini-3.5-flash-lite dan model embedding gemini-embedding-2 tersedia. Model generasi menghasilkan JSON terstruktur dan pemanggilan fungsi; model embedding menghasilkan vektor 256 dimensi sesuai kolom pgvector yang sudah ada.

**Privasi:** ketentuan Gemini API untuk layanan tanpa biaya melarang pengiriman informasi sensitif, rahasia, atau pribadi dan menyatakan konten dapat digunakan untuk meningkatkan produk. Untuk mencoba key gratis, gunakan pesan, tugas, dan event sintetis saja. Sebelum menghubungkan Gmail/Calendar pribadi ke alur AI, pastikan tier dan pengaturan data sesuai. Baca [Gemini API Terms](https://ai.google.dev/gemini-api/terms) dan [Pricing](https://ai.google.dev/gemini-api/docs/pricing) terbaru.

## 2. Local di PowerShell

Buka terminal di root FocusOS. Isi environment untuk terminal ini tanpa menulis key di riwayat perintah:

    $secret = Read-Host "Gemini API key" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    npm.cmd run dev:api

Di terminal lain, jalankan frontend dengan npm.cmd run dev:web. backend/.env.example hanya contoh nama variabel; backend tidak otomatis membaca file .env. Untuk evaluasi live di terminal lain, set variabel yang sama di terminal itu lalu jalankan .\.venv\Scripts\python.exe evals/run.py --live dan .\.venv\Scripts\python.exe evals/score.py. Hasil evaluasi memakai data sintetis dan ditulis di evals/output/ yang diabaikan Git.

## 3. Database Supabase

Jalankan migration baru 20260927160000_gemini_provider.sql pada project Supabase yang dipakai aplikasi. Jika CLI sudah terhubung ke project yang benar, jalankan npm.cmd run db:push dari root repo. Migration mengganti kontrak model dan fungsi pencarian/telemetri. Vektor embedding OpenAI terdahulu kembali ke status pending; fakta memori tetap ada dan dapat di-embed ulang dari UI. Kedua model menghasilkan ruang semantik berbeda walaupun panjang vektornya sama.

Pastikan migration berhasil sebelum memakai tombol Embed atau semantic search pada backend Gemini. Hindari menjalankan backend lama selama migration provider berlangsung.

## 4. Vercel

Di project API focusos-api buka Settings → Environment Variables dan tambahkan GEMINI_API_KEY sebagai variabel Production. Tempel key hanya di dashboard Vercel, lalu redeploy API. Jangan menambahkannya ke project web. Key ini terpisah dari OAuth Google Client ID/Secret: OAuth mengizinkan akses Gmail/Calendar, sedangkan Gemini key mengizinkan panggilan model AI. Jika secret OAuth/token backend pada [remaining-work.md](remaining-work.md) belum diisi, fitur Google live tetap belum aktif walaupun Gemini key sudah ada.

Verifikasi awal dengan source sintetis di /activity: simpan, extract, periksa bukti dan tanggal sebelum konfirmasi. Coba satu fakta sintetis terkonfirmasi untuk embedding, lalu buka `/memories` untuk pencarian langsung. Planning agent di `/agent` menyusun jadwal dan membutuhkan pembacaan Calendar sebelum mencapai pencarian memori; gunakan `/memories` untuk menguji pencarian tanpa Calendar. Jalankan evaluator live sintetis sebelum membuat klaim kualitas. Model lookup, generate sederhana, structured output, dan extraction source sintetis sudah dilaporkan berhasil secara lokal. Embedding live, evaluasi 16 kasus, dan deployment Gemini belum diverifikasi.
