import logging
import logging.handlers
import os
from pathlib import Path

from src.settings import get_data_path


LOG_MAX_BYTES = 3 * 1024 * 1024
LOG_BACKUP_COUNT = 2


def get_log_path() -> Path:
    try:
        base_dir = get_data_path()
    except TypeError:
        base_dir = Path.cwd() / 'data'

    log_dir = base_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / 'tweeticcini.log'


def prune_stale_log_backups(log_path: Path, backup_count: int = LOG_BACKUP_COUNT) -> None:
    for backup in log_path.parent.glob(f'{log_path.name}.*'):
        suffix = backup.name.removeprefix(f'{log_path.name}.')
        if suffix.isdigit() and int(suffix) > backup_count:
            backup.unlink(missing_ok=True)


class LogFormatter(logging.Formatter):

    LEVEL_COLORS = [
        (logging.DEBUG, '\x1b[40;1m'),
        (logging.INFO, '\x1b[34;1m'),
        (logging.WARNING, '\x1b[33;1m'),
        (logging.ERROR, '\x1b[31m'),
        (logging.CRITICAL, '\x1b[41m'),
    ]

    def setFORMATS(self, is_exc_info_colored):
        if is_exc_info_colored:
            self.FORMATS = {
                level: logging.Formatter(
                    f'\x1b[30;1m%(asctime)s\x1b[0m {color}%(levelname)-8s\x1b[0m '
                    f'\x1b[35m%(name)s\x1b[0m -> %(message)s',
                    '%Y-%m-%d %H:%M:%S'
                )
                for level, color in self.LEVEL_COLORS
            }
        else:
            self.FORMATS = {
                item[0]: logging.Formatter(
                    '%(asctime)s %(levelname)-8s %(name)s -> %(message)s',
                    '%Y-%m-%d %H:%M:%S'
                )
                for item in self.LEVEL_COLORS
            }

    def format(self, record, is_exc_info_colored=False):
        self.setFORMATS(is_exc_info_colored)
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]

        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            if is_exc_info_colored:
                record.exc_text = f'\x1b[31m{text}\x1b[0m'
            else:
                record.exc_text = text

        output = formatter.format(record)
        record.exc_text = None
        return output


class ConsoleFormatter(LogFormatter):
    def format(self, record):
        return super().format(record, is_exc_info_colored=True)


def setup_logger(module_name: str) -> logging.Logger:
    log_path = get_log_path()
    prune_stale_log_backups(log_path)

    library, _, _ = module_name.partition('.py')
    logger = logging.getLogger(library)
    logger.setLevel(logging.INFO)

    if not logger.handlers:

        # Console (colored, for systemd journal)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(ConsoleFormatter())

        # Rotating persistent file handler
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            encoding='utf-8',
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
        )
        file_handler.setFormatter(LogFormatter())

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
