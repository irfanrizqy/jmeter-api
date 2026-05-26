"""
Endpoint untuk merge CSV dari beberapa fase test menjadi satu file.
Ada dua flow: langsung download (merge), atau prepare dulu lalu download (merge-prepare).
merge-prepare berguna kalau file besar — frontend bisa tampilkan ukuran file dulu sebelum download dimulai.
"""

import os

from flask import Blueprint, current_app, jsonify, request, send_file

import config
from jmeter.csv_merge import build_merged_summary_csv, build_merged_requests_csv

csv_merge_bp = Blueprint('csv_merge', __name__)


def _parse_ids(ids_param):
    # Split dan bersihkan daftar test_id dari query string
    return [t.strip() for t in ids_param.split(',') if t.strip()]


@csv_merge_bp.route('/api/load-test/results/summary-csv/merge', methods=['GET'])
def merge_summary_csv():
    # Gabungkan summary CSV semua fase dan langsung kirim sebagai download
    test_ids = _parse_ids(request.args.get('ids', ''))
    if not test_ids:
        return jsonify({'status': 'error', 'message': 'ids required'}), 400

    try:
        out_path, out_filename, missing = build_merged_summary_csv(test_ids)
        size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 1)
        if missing:
            current_app.logger.warning(f"⚠️ [CSV] Merge summary: {len(missing)} fase dilewati: {missing}")
        current_app.logger.info(f"✅ [CSV] Merge summary selesai: {out_filename} | {len(test_ids)} fase | {size_mb} MB")
        return send_file(out_path, mimetype='text/csv', as_attachment=True, download_name=out_filename)
    except RuntimeError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 404
    except Exception as e:
        current_app.logger.error(f"❌ [CSV] Error merge summary CSVs: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@csv_merge_bp.route('/api/load-test/results/summary-csv/merge-prepare', methods=['GET'])
def merge_summary_csv_prepare():
    # Simpan file merge tapi hanya kembalikan metadata (nama, path, ukuran).
    # Frontend pakai ini untuk tampilkan konfirmasi sebelum download file besar.
    test_ids = _parse_ids(request.args.get('ids', ''))
    if not test_ids:
        return jsonify({'status': 'error', 'message': 'ids required'}), 400

    try:
        out_path, out_filename, missing = build_merged_summary_csv(test_ids)
        size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 1)
        if missing:
            current_app.logger.warning(f"⚠️ [CSV] Merge summary prepare: {len(missing)} fase dilewati: {missing}")
        current_app.logger.info(f"✅ [CSV] Merge summary prepare selesai: {out_filename} | {len(test_ids)} fase | {size_mb} MB")
        return jsonify({'status': 'ok', 'filename': out_filename, 'path': out_path,
                        'size_mb': size_mb, 'missing': missing})
    except RuntimeError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 404
    except Exception as e:
        current_app.logger.error(f"❌ [CSV] Error prepare merge summary CSVs: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@csv_merge_bp.route('/api/load-test/results/requests-csv/merge', methods=['GET'])
def merge_requests_csv():
    # Gabungkan requests.csv semua fase dan langsung kirim sebagai download
    test_ids = _parse_ids(request.args.get('ids', ''))
    if not test_ids:
        return jsonify({'status': 'error', 'message': 'ids required'}), 400

    try:
        out_path, out_filename, missing = build_merged_requests_csv(test_ids)
        size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 1)
        if missing:
            current_app.logger.warning(f"⚠️ [CSV] Merge requests: {len(missing)} fase tidak ada requests.csv: {missing}")
        current_app.logger.info(f"✅ [CSV] Merge requests selesai: {out_filename} | {len(test_ids)} fase | {size_mb} MB")
        return send_file(out_path, mimetype='text/csv', as_attachment=True, download_name=out_filename)
    except RuntimeError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 404
    except Exception as e:
        current_app.logger.error(f"❌ [CSV] Error merge requests CSVs: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@csv_merge_bp.route('/api/load-test/results/requests-csv/merge-prepare', methods=['GET'])
def merge_requests_csv_prepare():
    # Sama seperti merge tapi hanya kembalikan metadata, tidak langsung download
    test_ids = _parse_ids(request.args.get('ids', ''))
    if not test_ids:
        return jsonify({'status': 'error', 'message': 'ids required'}), 400

    try:
        out_path, out_filename, missing = build_merged_requests_csv(test_ids)
        size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 1)
        if missing:
            current_app.logger.warning(f"⚠️ [CSV] Merge prepare requests: {len(missing)} fase tidak ada requests.csv: {missing}")
        current_app.logger.info(f"✅ [CSV] Merge requests prepare selesai: {out_filename} | {len(test_ids)} fase | {size_mb} MB")
        return jsonify({'status': 'ok', 'filename': out_filename, 'path': out_path,
                        'size_mb': size_mb, 'missing': missing})
    except RuntimeError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 404
    except Exception as e:
        current_app.logger.error(f"❌ [CSV] Error prepare merge requests CSVs: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@csv_merge_bp.route('/api/load-test/results/merged/<filename>', methods=['GET'])
def serve_merged_file(filename):
    # Serve file dari merged_results/ berdasarkan nama file.
    # Validasi path supaya tidak bisa keluar dari direktori merged_results/.
    out_dir   = os.path.join(config.RESULTS_DIR, 'merged_results')
    file_path = os.path.join(out_dir, filename)
    if not os.path.abspath(file_path).startswith(os.path.abspath(out_dir)):
        return jsonify({'status': 'error', 'message': 'Invalid filename'}), 400
    if not os.path.exists(file_path):
        return jsonify({'status': 'error', 'message': 'File not found'}), 404
    return send_file(file_path, mimetype='text/csv', as_attachment=True, download_name=filename)
