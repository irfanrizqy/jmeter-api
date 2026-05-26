"""
Endpoint untuk monitoring dan pembersihan disk.
Dipakai dari dashboard ketika disk mulai penuh atau mau hapus hasil test lama.
Cleanup juga otomatis hapus sesi multi-phase yang test-nya sudah tidak ada di disk.
"""

import glob
import os
import shutil

from flask import Blueprint, current_app, jsonify, request

import config
import state
from storage.persistence import save_metadata_async
from storage.sessions import _sessions_lock, load_sessions, save_sessions

disk_bp = Blueprint('disk', __name__)


@disk_bp.route('/api/disk/status', methods=['GET'])
def disk_status():
    # Cek penggunaan disk secara keseluruhan + ukuran folder test_results dan merged_results
    try:
        total, used, free = shutil.disk_usage('/')
        usage_pct = (used / total) * 100

        test_dirs          = sorted(glob.glob(os.path.join(config.RESULTS_DIR, 'test_*')),
                                    key=os.path.getmtime, reverse=True)
        total_results_size = 0
        for d in test_dirs:
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        if entry.is_file():
                            total_results_size += entry.stat().st_size
            except OSError:
                pass

        merged_dir   = os.path.join(config.RESULTS_DIR, 'merged_results')
        merged_size  = 0
        merged_count = 0
        if os.path.isdir(merged_dir):
            try:
                with os.scandir(merged_dir) as it:
                    for entry in it:
                        if entry.is_file():
                            merged_size  += entry.stat().st_size
                            merged_count += 1
            except OSError:
                pass

        return jsonify({
            'status':          'ok',
            'disk_total_gb':   round(total / 1e9, 2),
            'disk_used_gb':    round(used  / 1e9, 2),
            'disk_free_gb':    round(free  / 1e9, 2),
            'disk_usage_pct':  round(usage_pct, 1),
            'results_count':   len(test_dirs),
            'results_size_mb': round(total_results_size / 1e6, 1),
            'merged_count':    merged_count,
            'merged_size_mb':  round(merged_size / 1e6, 1),
            'warning':         usage_pct >= 80
        })
    except Exception as e:
        current_app.logger.error(f"🚨 [DISK] Error saat cek disk status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@disk_bp.route('/api/disk/cleanup', methods=['POST'])
def disk_cleanup():
    # Hapus test lama dari disk, sisakan N terbaru. Juga bersihkan merged_results/
    # dan hapus sesi yang sudah tidak punya semua fase di disk.
    try:
        data = request.get_json(silent=True) or {}
        keep = max(1, min(50, int(data.get('keep', 10))))

        test_dirs     = sorted(glob.glob(os.path.join(config.RESULTS_DIR, 'test_*')),
                               key=os.path.getmtime, reverse=True)
        to_delete     = test_dirs[keep:]
        deleted_count = 0
        freed_mb      = 0

        for d in to_delete:
            try:
                size = 0
                try:
                    with os.scandir(d) as it:
                        for entry in it:
                            if entry.is_file():
                                size += entry.stat().st_size
                except OSError:
                    pass
                shutil.rmtree(d)
                freed_mb      += size / 1e6
                deleted_count += 1
                test_id = os.path.basename(d)
                current_app.logger.info(f"🗑️ [DISK] Hapus test: {test_id} ({round(size/1e6, 1)} MB)")
                with state.tests_lock:
                    if test_id in state.running_tests:
                        del state.running_tests[test_id]
            except Exception as ex:
                current_app.logger.error(f"🚨 [DISK] Gagal hapus folder {d}: {ex}")

        # merged_results/ isinya artefak download yang mudah di-regenerasi, aman dihapus semua
        merged_dir = os.path.join(config.RESULTS_DIR, 'merged_results')
        if os.path.isdir(merged_dir):
            for fname in os.listdir(merged_dir):
                fpath = os.path.join(merged_dir, fname)
                try:
                    freed_mb += os.path.getsize(fpath) / 1e6
                    os.unlink(fpath)
                    current_app.logger.info(f"🗑️ [DISK] Hapus merged: {fname}")
                except Exception as ex:
                    current_app.logger.error(f"🚨 [DISK] Gagal hapus merged {fname}: {ex}")

        # Hapus sesi yang salah satu fasenya sudah tidak ada di disk
        with _sessions_lock:
            sessions         = load_sessions()
            kept_sessions    = []
            removed_sessions = 0
            for s in sessions:
                all_exist = all(
                    os.path.isdir(os.path.join(config.RESULTS_DIR, tid))
                    for tid in s.get('test_ids', [])
                )
                if all_exist:
                    kept_sessions.append(s)
                else:
                    removed_sessions += 1
                    current_app.logger.info(f"🗑️ [DISK] Sesi {s.get('id')} dihapus — salah satu fase tidak ada di disk: {s.get('test_ids', [])}")
            if removed_sessions:
                save_sessions(kept_sessions)

        if deleted_count > 0:
            save_metadata_async(current_app._get_current_object())

        total, used, free = shutil.disk_usage('/')
        usage_pct = (used / total) * 100

        return jsonify({
            'status':           'success',
            'deleted_count':    deleted_count,
            'freed_mb':         round(freed_mb, 1),
            'kept_count':       min(keep, len(test_dirs)),
            'disk_usage_pct':   round(usage_pct, 1),
            'disk_free_gb':     round(free / 1e9, 2),
            'sessions_removed': removed_sessions,
            'message':          f"Hapus {deleted_count} test lama, bebas {freed_mb:.1f} MB"
        })
    except Exception as e:
        current_app.logger.error(f"🚨 [DISK] Error saat disk cleanup: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
