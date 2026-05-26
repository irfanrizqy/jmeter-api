"""
Persistence module - save/load metadata ke disk

Berisi:
- save_critical_test_info  : simpan info kritis per-test (SYNC)
- save_metadata            : simpan global metadata ke disk
- save_metadata_async      : schedule metadata save di background
- periodic_metadata_save   : auto-backup setiap 60 detik
"""

import os
import json
import time
from datetime import datetime

import config
import state


# ==================== SAFE SAVE FUNCTIONS ====================

def save_critical_test_info(app, test_id, test_data):
    """
    Save critical test info per-test (SYNC - immediate)
    
    This ensures test info is saved immediately even if:
    - Server crashes
    - Async save fails
    - Metadata save is delayed
    
    Returns: bool (success/failure)
    """
    try:
        test_dir = os.path.join(config.RESULTS_DIR, test_id)
        os.makedirs(test_dir, exist_ok=True)
        
        # Prepare critical info
        critical_info = {
            'test_id': test_id,
            'status': test_data.get('status', config.STATUS_PENDING),
            'parameters': test_data.get('parameters', {}),
            'created_time': test_data.get('created_time', datetime.now()).isoformat() 
                           if isinstance(test_data.get('created_time'), datetime) 
                           else str(test_data.get('created_time', datetime.now())),
            'saved_at': datetime.now().isoformat()
        }
        
        # Save to disk atomically (SYNC): tulis ke .tmp dulu, lalu rename
        info_file = os.path.join(test_dir, 'test_info.json')
        tmp_file  = info_file + '.tmp'
        with open(tmp_file, 'w') as f:
            json.dump(critical_info, f, indent=2)
        os.replace(tmp_file, info_file)
        
        app.logger.info(f"💾 [PERSIST] Critical info tersimpan: {test_id}")
        return True

    except IOError as e:
        app.logger.error(f"🚨 [PERSIST] Disk I/O error, gagal simpan critical info {test_id}: {e}")
        return False
    except Exception as e:
        app.logger.error(f"💥 [PERSIST] Error tidak terduga saat simpan critical info {test_id}: {e}")
        return False


def save_metadata(app):
    """
    Save global test metadata to disk

    This is the master index of all tests.
    Safe to fail - can be rebuilt from individual test_info.json files

    Note: 'results' (timeline data) intentionally excluded to keep file small.
    Full results tetap tersimpan di summary.json per test directory.
    """
    try:
        metadata = {}

        with state.tests_lock:
            for test_id, test in state.running_tests.items():
                # Create serializable copy
                test_copy = test.copy()

                # Remove non-serializable objects
                if 'process' in test_copy:
                    del test_copy['process']

                # Exclude results — data besar (timeline), sudah ada di summary.json
                # Saat recovery, results di-load ulang dari summary.json via load_test_from_disk
                if 'results' in test_copy:
                    del test_copy['results']

                # Convert datetime to ISO format
                for field in ['created_time', 'start_time', 'end_time']:
                    if field in test_copy and test_copy[field]:
                        if isinstance(test_copy[field], datetime):
                            test_copy[field] = test_copy[field].isoformat()

                metadata[test_id] = test_copy
        
        # Save to disk
        temp_file = config.METADATA_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Atomic rename
        os.replace(temp_file, config.METADATA_FILE)
        
        app.logger.debug(f"💾 [PERSIST] Metadata tersimpan: {len(metadata)} test")
        return True

    except IOError as e:
        app.logger.error(f"🚨 [PERSIST] Disk I/O error di save_metadata: {e}")
        return False
    except Exception as e:
        app.logger.error(f"💥 [PERSIST] Error tidak terduga di save_metadata: {e}")
        return False


def save_metadata_async(app):
    """Schedule metadata save in background (non-blocking)"""
    try:
        state.metadata_executor.submit(save_metadata, app)
        app.logger.debug("Metadata save scheduled")
    except Exception as e:
        app.logger.error(f"🚨 [PERSIST] Gagal jadwalkan metadata save: {e}")


def periodic_metadata_save(app):
    """
    Periodic metadata save (every 60 seconds)
    
    Provides additional safety layer - ensures metadata is regularly saved
    even if async saves fail or are delayed
    """
    while not state.shutdown_flag:
        try:
            time.sleep(60)
            
            if not state.shutdown_flag:
                success = save_metadata(app)
                if success:
                    app.logger.info(f"📦 [PERSIST] Periodic backup selesai — {len(state.running_tests)} test di memory")

        except Exception as e:
            app.logger.error(f"🚨 [PERSIST] Error di periodic save: {e}")