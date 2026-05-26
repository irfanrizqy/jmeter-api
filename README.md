# JMeter API

Repository ini berisi API untuk menjalankan dan mengelola pengujian load test menggunakan Apache JMeter. Project ini digunakan sebagai bagian dari pengujian sistem Smart Load Balancer pada Capstone Design.

API ini membantu proses pengujian agar load test tidak hanya dijalankan manual lewat command line, tetapi juga bisa dikontrol melalui endpoint HTTP. Dengan begitu, proses menjalankan test, membaca status, memproses hasil, dan membuat output CSV bisa dilakukan dari satu service.

## Struktur Project

```text
jmeter-api/
├── jmeter/               # Modul untuk membuat command, menjalankan test, dan memproses hasil JMeter
├── routes/               # Endpoint API
├── storage/              # Penyimpanan session dan metadata runtime
├── templates/            # Template JMeter (.jmx)
├── config-example.py     # Contoh konfigurasi
├── jmeter_api_server.py  # Entry point server API
├── state.py              # State aplikasi
└── README.md
```

## Ringkasan Perubahan

Project ini merupakan hasil refactor dari versi awal JMeter API yang sebelumnya masih berbentuk monolitik. Refactor dilakukan dengan memecah endpoint API ke beberapa modul di folder `routes/`, memisahkan logika JMeter ke folder `jmeter/`, memindahkan pengelolaan session dan metadata ke folder `storage/`, menghapus dead code, serta memperbaiki format log agar lebih mudah dipantau melalui systemd atau `journalctl`. Perubahan ini membuat struktur project lebih modular, lebih mudah dirawat, dan lebih siap digunakan sebagai lampiran laporan Capstone Design.

Detail perubahan refactor, termasuk pemecahan modul, penghapusan fungsi tidak terpakai, perubahan format log, cleanup file, dan dependency graph dapat dilihat pada file `changelog-17052026.md`.

## File yang Tidak Disertakan

Beberapa file dan folder tidak disertakan ke repository karena bersifat lokal atau merupakan output runtime:

```text
config.py
test_metadata.json
test_results/
logs/
venv/
__pycache__/
```

File `config.py` tidak disertakan karena berisi konfigurasi lokal environment pengujian. Gunakan `config-example.py` sebagai template:

```bash
cp config-example.py config.py
```

Setelah itu, sesuaikan nilai konfigurasi seperti target host, port, lokasi JMeter, Redis host, dan backend mapping sesuai environment pengujian.

## Requirement

Project ini membutuhkan:

- Python 3
- Apache JMeter
- Flask
- Redis, jika integrasi Q-Learning digunakan

Apache JMeter tidak disertakan di repository. JMeter perlu di-install secara terpisah pada server atau VM pengujian.

## Menjalankan API

Masuk ke folder project:

```bash
cd jmeter-api
```

Buat virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Buat file konfigurasi lokal:

```bash
cp config-example.py config.py
```

Sesuaikan konfigurasi di `config.py`, lalu jalankan server:

```bash
python3 jmeter_api_server.py
```

## Template Load Test

Template JMeter berada di:

```text
templates/load_test_template.jmx
```

Template ini menerima parameter dari API saat JMeter dijalankan, seperti:

```text
target_host
target_port
http_path
num_threads
ramp_time
duration
results_file
```

Dengan cara ini, template `.jmx` tetap fleksibel dan tidak perlu diubah setiap kali target atau skenario pengujian berubah.

## Catatan

Repository ini hanya menyimpan source code, template JMeter, file contoh konfigurasi, dan changelog refactor. File konfigurasi lokal, hasil pengujian, metadata runtime, virtual environment, cache Python, dan log tidak disertakan agar repository tetap bersih dan aman untuk arsip laporan.