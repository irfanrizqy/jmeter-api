"""
Post-processing setelah JMeter selesai jalan.
Dipisahkan dari runner supaya run_jmeter_test tidak terlalu panjang.
Dua skenario: punya JTL (parse dari file) atau no_jtl (parse dari stdout).
"""

import json
import os
import threading

import config
import state
from storage.persistence import save_metadata_async
from jmeter.parser import parse_jmeter_results


def process_results(app, test_id, test_dir, results_file, params, status, start_time, end_time):
    # Parse JTL di background thread supaya endpoint status tidak nunggu parsing selesai.
    # Setelah selesai, update memory state dan simpan summary.json ke disk.
    def _run():
        try:
            app.logger.info(f"🔍 [JTL] Mulai parsing JTL: {test_id}")
            stats = parse_jmeter_results(app, results_file)

            if not stats:
                app.logger.warning(f"⚠️ [JTL] Parse selesai tapi tidak ada data untuk {test_id} — JTL mungkin kosong")
                with state.tests_lock:
                    state.running_tests[test_id]['status'] = config.STATUS_FAILED
                    state.running_tests[test_id]['error']  = 'JTL ada tapi parse tidak menghasilkan data'
                save_metadata_async(app)
                return

            summary_file = os.path.join(test_dir, "summary.json")
            with open(summary_file, 'w') as f:
                json.dump({
                    'test_id':    test_id,
                    'parameters': params,
                    'status':     status,
                    'start_time': start_time.isoformat(),
                    'end_time':   end_time.isoformat(),
                    'results':    stats,
                }, f, indent=2)

            with state.tests_lock:
                state.running_tests[test_id]['results'] = stats

            total = stats.get('total_requests', '?')
            err_r = stats.get('error_rate', '?')
            tput  = stats.get('throughput', '?')
            app.logger.info(f"📊 [JTL] Hasil tersedia: {test_id} | total={total} req err_rate={err_r}% tput={tput} rps")
            save_metadata_async(app)

        except Exception as e:
            app.logger.error(f"❌ [JTL] Parse error untuk {test_id}: {e}", exc_info=True)
            with state.tests_lock:
                state.running_tests[test_id]['status'] = config.STATUS_FAILED
                state.running_tests[test_id]['error']  = f'Parse error: {e}'
            save_metadata_async(app)

    threading.Thread(target=_run, daemon=True).start()


def process_no_jtl(app, test_id, test_dir, params, status, start_time, end_time, stdout_stats):
    # Untuk mode no_jtl (hemat disk), hasil hanya dari stdout JMeter.
    # Simpan ke summary.json supaya recovery tetap bisa baca setelah restart.
    def _run():
        try:
            if not stdout_stats:
                app.logger.warning(f"⚠️ [JTL] Tidak ada stdout stats untuk {test_id} — JMeter tidak cetak summary")
                with state.tests_lock:
                    state.running_tests[test_id]['status'] = config.STATUS_FAILED
                    state.running_tests[test_id]['error']  = 'Tidak ada data dari stdout JMeter'
                save_metadata_async(app)
                return

            summary_file = os.path.join(test_dir, "summary.json")
            with open(summary_file, 'w') as f:
                json.dump({
                    'test_id':    test_id,
                    'parameters': params,
                    'status':     status,
                    'start_time': start_time.isoformat(),
                    'end_time':   end_time.isoformat(),
                    'results':    stdout_stats,
                }, f, indent=2)

            with state.tests_lock:
                state.running_tests[test_id]['results'] = stdout_stats

            total = stdout_stats.get('total_requests', '?')
            err_r = stdout_stats.get('error_rate', '?')
            tput  = stdout_stats.get('throughput', '?')
            app.logger.info(f"📊 [JTL] Hasil no_jtl tersimpan: {test_id} | total={total} req err_rate={err_r}% tput={tput} rps")
            save_metadata_async(app)

        except Exception as e:
            app.logger.error(f"❌ [JTL] no_jtl result error untuk {test_id}: {e}", exc_info=True)
            with state.tests_lock:
                state.running_tests[test_id]['status'] = config.STATUS_FAILED
                state.running_tests[test_id]['error']  = f'Parse error: {e}'
            save_metadata_async(app)

    threading.Thread(target=_run, daemon=True).start()
