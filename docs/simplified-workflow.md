# FocusOS: alur pribadi yang lebih sederhana

## Perubahan yang diminta

Pengguna meminta input sekali sampai organized, tanpa halaman untuk memantau jobs. Form task satu per satu dan New project dihapus. Input manual berupa plain text seperti isi email. Preferensi dan search memories masuk Home; halaman Tasks dan Schedule dihilangkan.

## Alur pengguna

- Home: task hari ini, deadline mendatang (pagination/urgency tetap), pencarian memory dengan evidence, ketersediaan Calendar, Scheduled work dan Preferences. Edit judul/complete tetap bisa dilakukan dari Home.
- Activity: Sync & organize mengimpor email berlabel FocusOS, memproses tugas/fakta, menyimpan hasil, mengindeks memory, lalu memperbarui Activity otomatis. Tombol tetap Organizing selama belum selesai. Refresh halaman melanjutkan observasi pekerjaan aktif.
- Manual: satu textarea Work description. Judul sumber berasal dari baris pertama; tidak meminta title, priority, project atau deadline terpisah. Sumber disimpan idempotently lalu diorganisasi dengan jalur yang sama.
- Task hasil parsing juga disimpan sebagai memory berbukti, termasuk jika teks tidak memiliki fakta terpisah. Retry memakai key memory deterministik; tidak membuat task/memory baru berulang untuk extraction sama.
- Planning dan Google connections tetap tersedia. URL lama Tasks/Schedule/Memories/Settings mengarah ke bagian Home; System kembali ke Home. Tidak ada tautan Jobs atau instruksi membuka System.

## Implementasi dan batas

Antrean durable, enkripsi sesi dan scheduler tetap internal agar tab yang ditutup tidak membatalkan pekerjaan server. UI hanya membaca status serta meminta server melanjutkan pekerjaan saat siap, tanpa tombol tiap langkah. Resume otomatis dibatasi interval dan menghormati available_at/backoff. Observasi berhenti saat komponen ditutup; pekerjaan server tidak dibatalkan.

Gmail menyimpan checkpoint source sebelum extraction/capture. Jika worker crash atau task/memory belum tersimpan, retry memakai source sama; ready extraction tidak membuat source tersebut dilewati. Counter hasil dipertahankan antar halaman sync. Succeeded baru diberikan setelah source diproses dan memory indexing selesai; failure/expiry tidak dilabeli organized.

Memory pada Activity dibaca dengan source_id tervalidasi dan owner/RLS, bukan dipotong dari daftar global 50 memory terbaru. Provider/schema tidak diganti dan tidak memerlukan environment variable atau migration baru. Error quota Gemini tetap memerlukan kuota tersedia; UI tidak bisa menghapus batas provider.

Backup dan restore tetap di luar scope. Tidak ada akses Gmail nyata atau pembuatan/penghapusan Calendar nyata saat pengujian otomatis perubahan ini.


## Verifikasi rilis

316 tes backend dan 99 tes web lulus. Build lokal dan build Vercel lulus. Kedua project produksi sudah READY; 22 pemeriksaan HTTP anonim dan lima pemeriksaan redirect langsung lulus. UI Home dan form plain text diverifikasi dengan rendering sintetis. Pemrosesan akun Google pengguna dan kualitas Gemini live tidak disimpulkan dari tes tersebut.
