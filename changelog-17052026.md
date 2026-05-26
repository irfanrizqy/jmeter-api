# Changelog: J-METER FINAL 2

**Tanggal refactor:** 17 Mei 2026  
**Basis:** J-METER FINAL (versi monolitik)  
**Tujuan:** Modularisasi, hapus dead code, dan beberapa perbaikan minor yang ditemukan saat proses refactor.

---

## Ringkasan Perubahan Struktur

| Versi Lama | Versi Baru | Keterangan |
|---|---|---|
| `routes/api.py` (1166 baris) | 6 file di `routes/` | Dipecah per domain |
| `jmeter/results.py` (514 baris) | 5 file di `jmeter/` | Dipecah per tanggung jawab |
| `jmeter/runner.py` (347 baris) | `runner.py` + `cmd_builder.py` + `processor.py` | Eksekusi, command build, post-process dipisah |
| `config.py` | `config.py` | Tambah 1 konstanta baru |
| `storage/recovery.py` | `storage/recovery.py` | Pakai konstanta dari config |
| *(tidak ada)* | `storage/sessions.py` | Logika session dipindah dari api.py |

---

## 1. Modularisasi

### `routes/api.py` → dipecah jadi 6 file

File monolitik 1166 baris yang menampung 26 endpoint sekaligus logika bisnis dipecah menjadi:

| File Baru | Isi |
|---|---|
| `routes/tests.py` | Health check, start, stop, status, results, list |
| `routes/csv_routes.py` | Generate, status, dan download CSV per-request |
| `routes/csv_merge_routes.py` | Merge summary/requests CSV antar fase, serve merged file |
| `routes/sessions.py` | CRUD sesi multi-phase |
| `routes/disk.py` | Status disk dan cleanup |
| `routes/recovery_routes.py` | Restore semua test dan reload test spesifik |

Masing-masing file punya Blueprint sendiri, didaftarkan di `jmeter_api_server.py`.

Logika yang sebelumnya inline di `api.py` dipindahkan ke modul yang lebih tepat:
- `_sessions_file`, `_load_sessions`, `_save_sessions` → `storage/sessions.py`
- `_ids_hash`, `_build_merged_summary_csv`, `_build_merged_requests_csv` → `jmeter/csv_merge.py`

---

### `jmeter/results.py` → dipecah jadi 5 file

| File Baru | Isi |
|---|---|
| `jmeter/formatting.py` | `_safe_int`, `_to_iso`, `_fmt` |
| `jmeter/qlearning_history.py` | Load history dari Redis, cari decision per timestamp |
| `jmeter/parser.py` | Parse JTL → summary statistics |
| `jmeter/csv_writer.py` | Build dan stream CSV (summary + per-request) |
| `jmeter/csv_merge.py` | Merge CSV multi-fase |

---

### `jmeter/runner.py` → dipecah jadi 3 file

| File Baru | Isi |
|---|---|
| `jmeter/cmd_builder.py` | `parse_target_url`, `build_jmeter_cmd` |
| `jmeter/processor.py` | `process_results`, `process_no_jtl` (post-processing background thread) |
| `jmeter/runner.py` | `run_jmeter_test`, `validate_test_parameters`, `generate_test_id`, `_parse_stdout_stats` |

---

## 2. Dead Code yang Dihapus

### `_safe_float()` — `jmeter/results.py` baris 28–31

```python
# DIHAPUS — tidak pernah dipanggil di mana pun
def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
```

Fungsi ini didefinisikan tapi tidak ada satu pun kode di proyek ini yang pernah memanggilnya. Bisa dipastikan mati sejak pertama kali ditulis.

---

### `parse_jmeter_request_rows()` — `jmeter/results.py` baris 192–260

```python
# DIHAPUS — tidak pernah diimpor di mana pun
def parse_jmeter_request_rows(app, results_file, test_id, params):
    ...
```

Fungsi ini tidak pernah diimpor oleh `routes/api.py` maupun `jmeter/runner.py`. Fungsionalitas yang sama sudah digantikan oleh `stream_request_csv_to_file()` yang versi streaming (lebih efisien, tidak load semua baris ke memory sekaligus).

---

## 3. Perubahan Non-Modularisasi

Berikut adalah perubahan yang ditemukan selain pemecahan file dan penghapusan dead code. Semua perubahan ini bersifat perbaikan — tidak ada yang mengubah perilaku sistem secara fundamental.

---

### 3.1 Konstanta `MAX_TESTS_IN_MEMORY` dipindah ke `config.py`

**File:** `config.py` dan `storage/recovery.py`

**Sebelum:**
```python
# storage/recovery.py baris 29 — hardcoded
MAX_TESTS = 50
```

**Sesudah:**
```python
# config.py
MAX_TESTS_IN_MEMORY = 50

# storage/recovery.py — pakai dari config
if test_count <= config.MAX_TESTS_IN_MEMORY:
```

Nilai 50 sekarang bisa diubah dari satu tempat tanpa perlu cari ke dalam logika recovery.

---

### 3.2 Penggunaan `.pop()` menggantikan `del` saat hapus key `process`

**File:** `jmeter/runner.py`

**Sebelum:**
```python
del state.running_tests[test_id]['process']
```

**Sesudah:**
```python
state.running_tests[test_id].pop('process', None)
```

`del` akan raise `KeyError` kalau key tidak ada (misalnya race condition antara stop handler dan timeout handler). `.pop(..., None)` tidak akan raise error. Perilaku fungsionalnya sama, tapi versi baru lebih defensif.

Perubahan ini berlaku di 3 tempat dalam `runner.py`: timeout handler, post-status update, dan exception handler.

---

### 3.3 Duplikasi logika load hasil dari disk dieliminasi

**File:** `routes/api.py` → `routes/tests.py`

Di versi lama, blok kode yang sama untuk membaca `summary.json` dari disk muncul dua kali:
- Di `get_test_results()` (baris 217–239)
- Di `get_test_results_csv()` (baris 289–311)

Di versi baru, logika ini dikumpulkan ke satu helper `_load_results_from_disk()` yang dipanggil dari kedua endpoint. Tidak ada perubahan perilaku, hanya menghilangkan duplikasi.

---

### 3.4 Nama fungsi Q-Learning history dipersingkat

**File:** `jmeter/results.py` → `jmeter/qlearning_history.py`

| Nama Lama | Nama Baru |
|---|---|
| `_load_qlearning_history(app)` | `load_qlearning_history(app)` |
| `_find_qlearning_decision_for_timestamp(request_dt, history)` | `find_qlearning_decision(request_dt, history)` |

Nama lama terlalu panjang dan prefiks `_` (private) tidak relevan lagi karena fungsi ini sekarang berada di modul sendiri dan diimpor dari luar. Tidak ada perubahan logika di dalamnya.

---

### 3.5 Beberapa emoji dihilangkan dari log message di `runner.py`

**File:** `jmeter/runner.py`

Beberapa log message di versi baru tidak lagi menggunakan emoji. Ini hanya perubahan kosmetik dari proses penulisan ulang, tidak mempengaruhi fungsionalitas.

Contoh:
- `"🚀 Starting JMeter test"` → `"Mulai JMeter test"`
- `"❌ Test {test_id} timeout"` → `"Test {test_id} timeout"`

Log message lain yang emoji-nya masih penting (seperti di `persistence.py` dan `recovery.py`) dibiarkan tidak berubah karena file-file tersebut tidak dimodifikasi.

---

## 4. Peningkatan Log untuk Systemd/Journalctl

Semua log message di seluruh codebase distandarisasi supaya lebih mudah dibaca di `journalctl` dan tidak membosankan di terminal hitam-putih.

### 4.1 Skema Prefix Kategori

Setiap log message sekarang diawali prefix `[KATEGORI]` sehingga mudah di-grep dan langsung jelas konteksnya:

| Prefix | File | Keterangan |
|--------|------|------------|
| `[TEST]` | `jmeter/runner.py`, `routes/tests.py` | Lifecycle test JMeter (mulai, selesai, stop manual) |
| `[JTL]` | `jmeter/processor.py`, `jmeter/parser.py` | Parse JTL dan post-processing |
| `[CSV]` | `jmeter/csv_writer.py`, `routes/csv_routes.py`, `routes/csv_merge_routes.py`, `routes/tests.py` | Generate, merge, dan serve CSV |
| `[PERSIST]` | `storage/persistence.py`, `routes/tests.py` | Save metadata ke disk |
| `[RECOVER]` | `storage/recovery.py` | Load dan recovery test dari disk |
| `[REDIS]` | `jmeter/qlearning_history.py` | Koneksi ke Redis Q-Learning |
| `[DISK]` | `routes/disk.py` | Status disk dan cleanup |
| `[API]` | `routes/tests.py` | Error pada endpoint REST |
| `[SESSION]` | `routes/sessions.py`, `storage/sessions.py` | CRUD sesi multi-phase |
| `[SHUTDOWN]` | `jmeter_api_server.py` | Proses berhenti karena sinyal |

### 4.2 Skema Emoji

Emoji ditambahkan di depan setiap pesan supaya level log langsung terbaca secara visual:

| Emoji | Makna | Contoh pesan |
|-------|-------|--------------|
| 🚀 | Proses dimulai | Test baru dijalankan |
| ✅ | Berhasil | Test selesai, CSV ready, metadata tersimpan |
| ❌ | Gagal | Test gagal, parse error, CSV error |
| ⏱️ | Timeout | JMeter di-kill karena melewati batas waktu |
| ⚠️ | Peringatan non-fatal | JMeter exit non-zero tapi JTL ada, Redis tidak konek |
| 🚨 | Error kritis | Disk I/O error, permission denied |
| 💥 | Exception tidak terduga | Error di luar prediksi di exception handler |
| 📊 | Data/hasil | Parse JTL selesai dengan statistik |
| 🔍 | Parsing | Mulai baca JTL |
| 📝 | Generate | Mulai generate CSV per-request |
| 💾 | Simpan | Critical info tersimpan (INFO), metadata tersimpan (DEBUG) |
| 📦 | Backup | Periodic backup selesai |
| 🧹 | Cleanup | Hapus test lama dari memory |
| 🔄 | Recover | Test berhasil di-recover dari disk |
| 🗑️ | Hapus | Hapus test/merged/sesi dari disk |
| 🛑 | Shutdown | Server menerima sinyal berhenti |
| ℹ️ | Informasi | Kondisi normal yang perlu dicatat |

### 4.3 Perubahan Level Log

Satu log diturunkan levelnya karena terlalu sering muncul dan tidak informatif di kondisi normal:

| Pesan | Sebelum | Sesudah | Alasan |
|-------|---------|---------|--------|
| `save_metadata` berhasil | INFO | DEBUG | Dipanggil setiap kali ada perubahan state — bisa puluhan kali per menit saat test aktif |

JMeter command tetap di INFO karena dipanggil sekali per test dan penting untuk verifikasi parameter yang sebenarnya dijalankan.

### 4.4 Perbaikan Format Log

- **Multiline dihilangkan:** `stderr` yang sebelumnya ditulis dengan `\n` sekarang ditulis satu baris menggunakan ` | ` sebagai pemisah. Log multiline mempersulit `journalctl` dan alat log aggregator.
- **Konteks ditambahkan:** Log yang sebelumnya hanya menyebut `test_id` kini menyertakan informasi tambahan yang relevan:
  - Log mulai test: `url`, `threads`, `duration`, `no_jtl`
  - Log hasil JTL: `total_requests`, `error_rate`, `throughput`
  - Log CSV selesai: jumlah baris dan ukuran file (MB)
  - Log hapus disk: ukuran folder yang dibebaskan (MB)
  - Log hapus sesi: daftar `test_ids` dari sesi yang dihapus
  - Log Redis gagal: `host:port` dan dampaknya ke CSV
- **Log completion ditambahkan:** `runner.py` sekarang mencatat saat test selesai dengan `elapsed time` dan `status` — sebelumnya tidak ada log penutup sama sekali.

### 4.5 Event Penting yang Sebelumnya Tidak Dilog

Beberapa operasi signifikan ditemukan tidak menghasilkan log sama sekali, atau log errornya tidak punya konteks cukup:

| Operasi | File | Masalah | Fix |
|---------|------|---------|-----|
| Test dihentikan manual | `routes/tests.py` | `stop_load_test` tidak ada log sama sekali | Tambah `🛑 [TEST] Test dihentikan manual` |
| Merge CSV selesai | `routes/csv_merge_routes.py` | 4 endpoint merge/prepare tidak ada log sukses, warning dan error juga tanpa emoji/prefix | Tambah `✅ [CSV] Merge selesai` + ukuran file; standarisasi warning dan error |
| Simpan dan hapus sesi | `routes/sessions.py` | Tidak ada log, tidak ada `current_app` diimport | Import `current_app`, tambah `✅ [SESSION]` untuk save dan `🗑️ [SESSION]` untuk delete |
| File sesi rusak | `storage/sessions.py` | `except Exception: return []` — diam-diam kembalikan list kosong tanpa log | Tambah `⚠️ [SESSION]` warning agar operator tahu file sesi perlu diperiksa |
| Error parse JTL | `jmeter/parser.py` | Log error tanpa prefix, emoji, atau nama file | Ganti jadi `❌ [JTL] Error parsing JTL {results_file}: {e}` |

---

## 5. Cleanup File Tidak Terpakai di templates/

Dua file ditemukan di `templates/` yang tidak direferensikan dari mana pun di codebase:

| File | Status | Alasan dihapus |
|------|--------|----------------|
| `load_test_template.jmx.backup` | **Dihapus** | File backup manual, tidak dipakai oleh code apapun |
| `traffic_monitor.html` | **Dihapus** | Tidak diimport, tidak di-serve, tidak ada route yang merujuknya |

File yang tetap ada:

| File | Direferensikan oleh |
|------|---------------------|
| `load_test_template.jmx` | `config.py` (konstanta `JMETER_TEMPLATE`) dan `availability_test_24h.sh` |

---

## 6. Yang Tidak Berubah

File-file berikut tidak dimodifikasi sama sekali:

- `state.py` — shared state, tidak ada yang perlu diubah
- `storage/persistence.py` — logika save sudah baik
- `storage/recovery.py` — hanya diubah satu baris (`MAX_TESTS` → `config.MAX_TESTS_IN_MEMORY`)
- `templates/` — semua file template JMeter dan HTML
- `availability_test_24h.sh` — script bash standalone

---

## 7. Dependency Graph Modul Baru

```
jmeter_api_server.py
├── routes/tests.py          → jmeter/runner.py, jmeter/csv_writer.py
├── routes/csv_routes.py     → jmeter/csv_writer.py
├── routes/csv_merge_routes.py → jmeter/csv_merge.py
├── routes/sessions.py       → storage/sessions.py
├── routes/disk.py           → storage/sessions.py
└── routes/recovery_routes.py → storage/recovery.py

jmeter/runner.py
├── jmeter/cmd_builder.py
└── jmeter/processor.py
      └── jmeter/parser.py

jmeter/csv_writer.py
├── jmeter/formatting.py
└── jmeter/qlearning_history.py

jmeter/csv_merge.py
└── jmeter/csv_writer.py
```

Tidak ada circular import.
