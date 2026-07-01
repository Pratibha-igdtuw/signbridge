"""
Structured JSON rotating-file logger for IDon Portal.
"""
import logging
import json
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "ts":    datetime.utcnow().isoformat(),
            "level": record.levelname,
            "msg":   record.getMessage(),
        }
        for extra in ("user", "ip", "path"):
            if hasattr(record, extra):
                log[extra] = getattr(record, extra)
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        return json.dumps(log)


def setup_logger(app):
    """Attach file + stream handlers to the Flask app logger."""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setFormatter(_JsonFormatter())
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    stream_handler.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
    if not app.logger.handlers:
        app.logger.addHandler(file_handler)
        app.logger.addHandler(stream_handler)
    return app.logger
