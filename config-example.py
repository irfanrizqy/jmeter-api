import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

JMETER_HOME = os.getenv("JMETER_HOME", "/opt/jmeter/current")
JMETER_BIN = os.path.join(JMETER_HOME, "bin", "jmeter")
JMETER_TEMPLATE = os.getenv(
    "JMETER_TEMPLATE",
    os.path.join(BASE_DIR, "templates", "load_test_template.jmx")
)

RESULTS_DIR = os.getenv("RESULTS_DIR", os.path.join(BASE_DIR, "test_results"))
LOGS_DIR = os.getenv("LOGS_DIR", os.path.join(BASE_DIR, "logs"))

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "8080"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

DEFAULT_NUM_THREADS = int(os.getenv("DEFAULT_NUM_THREADS", "100"))
DEFAULT_RAMP_TIME = int(os.getenv("DEFAULT_RAMP_TIME", "10"))
DEFAULT_DURATION = int(os.getenv("DEFAULT_DURATION", "60"))
DEFAULT_TARGET_HOST = os.getenv("DEFAULT_TARGET_HOST", "127.0.0.1")
DEFAULT_TARGET_PORT = int(os.getenv("DEFAULT_TARGET_PORT", "80"))
DEFAULT_HTTP_PATH = os.getenv("DEFAULT_HTTP_PATH", "/")

MAX_THREADS = int(os.getenv("MAX_THREADS", "10000"))
MAX_DURATION = int(os.getenv("MAX_DURATION", "3600"))
MAX_TESTS_IN_MEMORY = int(os.getenv("MAX_TESTS_IN_MEMORY", "50"))

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"

METADATA_FILE = os.getenv(
    "METADATA_FILE",
    os.path.join(BASE_DIR, "test_metadata.json")
)

QLEARNING_REDIS_HOST = os.getenv("QLEARNING_REDIS_HOST", "127.0.0.1")
QLEARNING_REDIS_PORT = int(os.getenv("QLEARNING_REDIS_PORT", "6379"))

BACKEND_IP_TO_NAME = {
    os.getenv("BACKEND_1_HOST", "127.0.0.1"): os.getenv("BACKEND_1_NAME", "web01"),
    os.getenv("BACKEND_2_HOST", "127.0.0.2"): os.getenv("BACKEND_2_NAME", "web02"),
    os.getenv("BACKEND_3_HOST", "127.0.0.3"): os.getenv("BACKEND_3_NAME", "web03"),
}