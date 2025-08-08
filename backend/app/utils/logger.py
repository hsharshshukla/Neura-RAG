# logger.py — Lightweight analytics logger for chat and upload events
import logging
import os
from datetime import datetime

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(log_dir, "analytics.log"),
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

def log_event(event_type: str, data: dict):
    try:
        log_str = f"{event_type.upper()} | {data}"
        logging.info(log_str)
    except Exception as e:
        logging.error(f"LOGGING_FAILED | {e}")
