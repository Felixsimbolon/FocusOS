# FocusOS pribadi: hari 4-14

Tanggal mulai: 7 Oktober 2026. Pengguna mengizinkan seluruh tahap dan meminta pengujian otomatis. Rencana hari 4-14 tidak tersimpan secara rinci sebelumnya; scope berikut melanjutkan arah pada plan.md. Hari adalah kelompok pekerjaan, bukan klaim jumlah hari yang sudah berlalu.

| Hari | Hasil yang dikerjakan | Bukti yang diperlukan |
| --- | --- | --- |
| 4-5 | Workspace task: cari/filter, edit deadline/estimasi/prioritas, complete/reopen/archive; pengelolaan memori dengan evidence | Tes kontrak edit, status, UI helper dan build |
| 6-8 | Durable job queue untuk planning, Gmail, source dan embedding; lease, retry, cancel, status; pekerjaan server setelah respons | Tes ownership, retry, expiry, fencing, workflow dan proxy |
| 9-10 | Daftar focus block tersimpan, pembatalan event milik FocusOS dan rekonsiliasi; memori task manual mengikuti perubahan | Tes provider mock, ETag, ownership, timeout dan SQL rollback |
| 11-12 | Diagnostik nonsecret, riwayat run/job, export data pribadi dan panduan restore | Tes redaksi, auth, pagination/batas export |
| 13-14 | Regresi otomatis, evaluator sintetis, build, migration/deploy bila akses tersedia; daftar setup yang belum selesai | Catatan hasil nyata, tanpa menyamakan mock dengan provider live |

Pendekatan: gunakan Supabase/Postgres sebagai antrean durable, tidak menambah Redis. Pekerjaan memakai sesi pengguna berumur pendek yang dienkripsi terpisah dari payload; tidak menyimpan refresh token Supabase. Pemicu server segera dapat menjalankan pekerjaan setelah halaman ditutup, tetapi retry saat host mati membutuhkan scheduler eksternal. Job kedaluwarsa meminta pengguna login dan submit ulang. Ini tidak mengklaim sync Gmail terus-menerus tanpa sesi atau worker yang aktif.

Tidak menambah integrasi baru atau akun wajib hanya untuk implementasi lokal. Setup pemicu scheduler dan verifikasi provider nyata yang belum tersedia dicatat dalam remaining-work.md setelah hasil pengujian.
