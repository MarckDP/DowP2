# src/core/logger/manager.py
import logging
import sys
from datetime import datetime

class CustomFormatter(logging.Formatter):
    """Custom formatter to provide a clean, timestamped output."""
    def format(self, record):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record.msg = f"[{timestamp}] {record.levelname:<8} [DowP] {record.msg}"
        return super().format(record)

def setup_logger():
    """Initializes and returns the global logger."""
    logger = logging.getLogger("DowP")
    logger.setLevel(logging.DEBUG)

    # Console Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    
    # Custom Formatter (Using the CustomFormatter class defined above)
    formatter = CustomFormatter()
    ch.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(ch)
    
    return logger

# Global logger instance
logger = setup_logger()
