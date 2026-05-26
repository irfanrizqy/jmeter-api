"""
Recovery module - load & restore test data dari disk

Berisi:
- load_test_from_disk          : load satu test dari disk
- scan_and_recover_all_tests   : scan semua test dari disk saat startup
- load_metadata                : load global metadata dari disk
- cleanup_old_tests_from_memory: buang test lama dari memory (max 50)
"""

import os
import json
from datetime import datetime

import config
import state
from storage.persistence import save_metadata_async


# ==================== MEMORY MANAGEMENT ====================

def cleanup_old_tests_from_memory(app):
    """
    Keep only recent tests in memory (max 50)
    
    Prevents memory bloat and metadata save slowdown
    Does NOT delete data from disk - only removes from memory
    """
    try:
        with state.tests_lock:
            test_count = len(state.running_tests)

            if test_count <= config.MAX_TESTS_IN_MEMORY:
                return
            
            # Sort by creation time (oldest first)
            sorted_tests = sorted(
                state.running_tests.items(),
                key=lambda x: x[1].get('created_time', datetime.min)
            )

            removed = 0
            for test_id, test in sorted_tests[:test_count - config.MAX_TESTS_IN_MEMORY]:
                # Don't remove running/pending tests
                if test['status'] not in [config.STATUS_RUNNING, config.STATUS_PENDING]:
                    del state.running_tests[test_id]
                    removed += 1
            
            if removed > 0:
                app.logger.info(f"🧹 [RECOVER] Memory cleanup: hapus {removed} test lama dari memory (tersisa {len(state.running_tests)})")
                save_metadata_async(app)

    except Exception as e:
        app.logger.error(f"🚨 [RECOVER] Error di cleanup memory: {e}")


# ==================== HELPERS ====================

def _restore_file_paths(test, test_dir):
    """Restore file path fields yang tidak tersimpan di summary/metadata."""
    # JTL results file
    jtl = os.path.join(test_dir, 'results.jtl')
    if os.path.exists(jtl):
        test['results_file'] = jtl

    # Request-level CSV: cek apakah file ada dan format baru (BOM UTF-8)
    csv_path = os.path.join(test_dir, 'requests.csv')
    if os.path.exists(csv_path):
        try:
            with open(csv_path, 'rb') as f:
                is_new_format = f.read(3) == b'\xef\xbb\xbf'
        except OSError:
            is_new_format = False
        if is_new_format:
            test['requests_csv_file'] = csv_path
            test['csv_request_status'] = 'ready'


# ==================== RECOVERY FUNCTIONS ====================

def load_test_from_disk(app, test_id):
    """
    Load a specific test from disk
    
    Tries to load from:
    1. summary.json (complete results)
    2. test_info.json (critical info)
    
    Returns: dict or None
    """
    try:
        test_dir = os.path.join(config.RESULTS_DIR, test_id)
        
        if not os.path.exists(test_dir):
            return None
        
        # Try summary.json first (complete data)
        summary_file = os.path.join(test_dir, 'summary.json')
        if os.path.exists(summary_file):
            with open(summary_file, 'r') as f:
                data = json.load(f)

            test = {
                'test_id': test_id,
                'status': data.get('status', config.STATUS_COMPLETED),
                'parameters': data.get('parameters', {}),
                'results': data.get('results', {})
            }

            # Parse timestamps
            for field in ['start_time', 'end_time', 'created_time']:
                if field in data and data[field]:
                    try:
                        test[field] = datetime.fromisoformat(data[field])
                    except:
                        pass

            _restore_file_paths(test, test_dir)
            return test

        # Fallback to test_info.json (critical data)
        info_file = os.path.join(test_dir, 'test_info.json')
        if os.path.exists(info_file):
            with open(info_file, 'r') as f:
                data = json.load(f)

            test = {
                'test_id': test_id,
                'status': data.get('status', config.STATUS_PENDING),
                'parameters': data.get('parameters', {})
            }

            if 'created_time' in data:
                try:
                    test['created_time'] = datetime.fromisoformat(data['created_time'])
                except:
                    pass

            _restore_file_paths(test, test_dir)
            return test
        
        return None
        
    except Exception as e:
        app.logger.error(f"🚨 [RECOVER] Gagal load test {test_id} dari disk: {e}")
        return None


def scan_and_recover_all_tests(app):
    """
    Scan disk and recover all tests
    
    This provides full recovery capability even if:
    - metadata.json is corrupted
    - Server crashed during operation
    - Metadata was never saved
    """
    try:
        if not os.path.exists(config.RESULTS_DIR):
            app.logger.warning(f"⚠️ [RECOVER] Results directory tidak ada: {config.RESULTS_DIR}")
            return 0
        
        recovered = 0
        
        for test_id in os.listdir(config.RESULTS_DIR):
            test_dir = os.path.join(config.RESULTS_DIR, test_id)
            
            if not os.path.isdir(test_dir):
                continue
            
            # Skip if already in memory
            with state.tests_lock:
                if test_id in state.running_tests:
                    continue
            
            # Load from disk
            test = load_test_from_disk(app, test_id)
            
            if test:
                # Mark as failed if was running during crash
                if test['status'] == config.STATUS_RUNNING:
                    test['status'] = config.STATUS_FAILED
                    test['error'] = 'Server restarted during test execution'
                
                with state.tests_lock:
                    state.running_tests[test_id] = test
                
                recovered += 1
        
        if recovered > 0:
            app.logger.info(f"🔄 [RECOVER] Berhasil recover {recovered} test dari disk")

        return recovered

    except Exception as e:
        app.logger.error(f"🚨 [RECOVER] Error saat scan disk recovery: {e}")
        return 0


def load_metadata(app):
    """Load metadata from disk (if exists)"""
    try:
        if not os.path.exists(config.METADATA_FILE):
            app.logger.info(f"ℹ️ [RECOVER] Metadata file tidak ada di {config.METADATA_FILE}, mulai fresh")
            return
        
        with open(config.METADATA_FILE, 'r') as f:
            metadata = json.load(f)
        
        loaded = 0
        with state.tests_lock:
            for test_id, test in metadata.items():
                # Skip tests whose directory was deleted from disk
                test_dir = os.path.join(config.RESULTS_DIR, test_id)
                if not os.path.exists(test_dir):
                    continue

                # Convert ISO timestamps back to datetime
                for field in ['created_time', 'start_time', 'end_time']:
                    if field in test and test[field]:
                        try:
                            test[field] = datetime.fromisoformat(test[field])
                        except:
                            pass

                # Mark running tests as failed
                if test['status'] == config.STATUS_RUNNING:
                    test['status'] = config.STATUS_FAILED
                    test['error'] = 'Server restarted during execution'

                state.running_tests[test_id] = test
                loaded += 1

        app.logger.info(f"✅ [RECOVER] Load metadata selesai: {loaded} test dimuat, {len(metadata) - loaded} dilewati (folder sudah terhapus)")

    except Exception as e:
        app.logger.error(f"🚨 [RECOVER] Gagal load metadata: {e}")
