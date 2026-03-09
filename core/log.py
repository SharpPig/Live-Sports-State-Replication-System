#Logging config for 

import logging
import sys
from pathlib import Path

# Console format - timestamp first
CONSOLE_FORMAT = "%(asctime)s.%(msecs)03d  %(levelname)-5s  %(name)s  %(message)s"
CONSOLE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# File format - [timestamp] prefix for easy parsing
FILE_FORMAT = "[%(asctime)s.%(msecs)03d]  %(levelname)-5s  %(name)s  %(message)s"
FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str, level: int = logging.INFO, log_file: bool = True) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=CONSOLE_DATE_FORMAT))
        logger.addHandler(console_handler)
        
        # File handler - only if requested
        if log_file:
            log_path = Path("logs")
            log_path.mkdir(exist_ok=True)
            file_handler = logging.FileHandler(log_path / f"{name.replace('.', '_')}.log")
            file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=FILE_DATE_FORMAT))
            logger.addHandler(file_handler)
    
    logger.setLevel(level)
    return logger
