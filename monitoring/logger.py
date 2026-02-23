"""
Logging Setup

Centralized logging configuration.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from config.settings import settings


def setup_logger(name: str = "trading_desk") -> logging.Logger:
    """Set up logger with file and console handlers."""
    logger = logging.getLogger(name)
    level_name = (settings.logging.log_level or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    
    # Remove existing handlers on the named logger to avoid duplicates
    logger.handlers = []
    # Named logger should NOT propagate if root already has a console handler,
    # but we set propagate=False and give it its own handler to avoid double lines.
    logger.propagate = False
    
    # Console handler (shared format)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Root logger: set up once so all OTHER module loggers also get console + file
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
               for h in root.handlers):
        root_console = logging.StreamHandler(sys.stdout)
        root_console.setLevel(logging.INFO)
        root_console.setFormatter(console_formatter)
        root.addHandler(root_console)
    
    if settings.logging.log_rotation:
        settings.logging.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = settings.logging.log_dir / settings.logging.log_file
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=settings.logging.log_max_bytes,
            backupCount=settings.logging.log_backup_count,
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(file_handler)
    return logger


def get_logger(name: str = "trading_desk") -> logging.Logger:
    """Get logger instance."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
