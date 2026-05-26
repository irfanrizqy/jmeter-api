"""
Global shared state for JMeter API Server

Semua modul mengimport dari sini agar tidak ada circular import
dan state tersentralisasi di satu tempat.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

# Store running tests
running_tests = {}

# Thread safety
tests_lock = threading.Lock()

# Shutdown flag
shutdown_flag = False

# Thread pool for async operations
metadata_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='metadata')
