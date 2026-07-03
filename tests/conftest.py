import os
import tempfile

# Isolate the MCP server's call log to a temp file during tests (it's read at import time).
os.environ.setdefault("SKIM_LOG_FILE", os.path.join(tempfile.gettempdir(), "skim_test_calls.jsonl"))
