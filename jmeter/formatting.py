"""
Fungsi-fungsi kecil untuk konversi tipe dan format output CSV.
Dipakai di banyak tempat, dikumpulkan di sini biar tidak duplikat.
"""


def _safe_int(value, default=0):
    # Konversi ke int, kalau gagal (None, string kosong, dll.) kembalikan default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_iso(val):
    # Terima datetime object atau string ISO — kembalikan string ISO yang konsisten
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def _fmt(val):
    # Excel Indonesia pakai koma sebagai pemisah desimal, bukan titik
    if val is None:
        return ''
    if isinstance(val, float):
        return str(val).replace('.', ',')
    return val
