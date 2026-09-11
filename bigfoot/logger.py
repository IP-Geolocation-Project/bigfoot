import atexit
import logging
import logging.handlers
import queue
import sys
from pathlib import Path
from typing import Optional

from colorama import Fore, Style, init as colorama_init

PACKAGE_LOGGER_NAME = "bigfoot"

_PLAIN_FMT = "%(asctime)s - %(filename)s - %(levelname)s - [Thread: %(thread)d] - %(message)s"


class CustomFormatter(logging.Formatter):
    _green = Fore.GREEN
    _grey = Style.DIM
    _yellow = Fore.YELLOW
    _red = Fore.RED
    _bold_red = f"{Style.BRIGHT}{Fore.RED}"
    _reset = Style.RESET_ALL

    FORMATS = {
        logging.DEBUG: _grey + _PLAIN_FMT + _reset,
        logging.INFO: _green + _PLAIN_FMT + _reset,
        logging.WARNING: _yellow + _PLAIN_FMT + _reset,
        logging.ERROR: _red + _PLAIN_FMT + _reset,
        logging.CRITICAL: _bold_red + _PLAIN_FMT + _reset,
    }

    def __init__(self):
        super().__init__()
        self._formatters = {
            level: logging.Formatter(fmt) for level, fmt in self.FORMATS.items()
        }
        self._default = logging.Formatter(_PLAIN_FMT)

    def format(self, record: logging.LogRecord) -> str:
        return self._formatters.get(record.levelno, self._default).format(record)


class LibLogger:
    """
    Async logger wrapper.

    Uses a python queue to store the records and flushes them using a background `QueueListener`, so log calls never block the caller.
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._output_handlers: list[logging.Handler] = []
        self._listener: Optional[logging.handlers.QueueListener] = None

        for h in list(self._logger.handlers):
            self._logger.removeHandler(h)

        self._queue: queue.Queue = queue.Queue()
        self._logger.addHandler(logging.handlers.QueueHandler(self._queue))

        self._stderr_default: Optional[logging.Handler] = logging.StreamHandler(sys.stderr)
        self._stderr_default.setLevel(logging.ERROR)
        self._stderr_default.setFormatter(logging.Formatter(_PLAIN_FMT))
        self._output_handlers.append(self._stderr_default)

        atexit.register(self.shutdown)

    def __getattr__(self, name):
        if name in ("debug", "info", "warning", "error", "critical", "exception", "log"):
            self._ensure_listener()
        return getattr(self._logger, name)

    def _ensure_listener(self) -> None:
        if not self._listener and self._output_handlers:
            self._listener = logging.handlers.QueueListener(
                self._queue, *self._output_handlers, respect_handler_level=True
            )
            self._listener.start()

    def _remove_stderr_default(self) -> None:
        if self._stderr_default and self._stderr_default in self._output_handlers:
            self._output_handlers.remove(self._stderr_default)
            self._stderr_default = None

    def to_console(self, level: int = logging.INFO) -> None:
        """
        A method to configure the StreamHandler for the logger. 

        :param: level: int - sets the desired logging level. By default is logging.INFO.
        :return: None
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(CustomFormatter())
        self._remove_stderr_default()
        self._output_handlers.append(handler)

    def to_file(self, path: str = "bigfoot.log", level: int = logging.INFO) -> None:
        """
        A method to configure the FileHandler for the logger.

        :param: path: str - sets the desired path for the log file. By default is "bigfoot.log".
        :param: level: int - sets the desired logging level. By default is logging.INFO.
        :return: None
        """
        filepath = Path(path)
        if filepath.suffix != ".log":
            filepath = filepath.with_suffix(".log")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(filepath, mode="w")
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(_PLAIN_FMT))
        self._remove_stderr_default()
        self._output_handlers.append(handler)

    @property
    def logger(self) -> logging.Logger:
        """
        A property to return the logger instance.

        :return: logging.Logger - the logger instance.
        """
        return self._logger

    def shutdown(self) -> None:
        """
        A method to shutdown the logger.

        :return: None
        """
        if self._listener:
            self._listener.stop()
            self._listener = None


_lib_logger: Optional[LibLogger] = None


def configure_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure the package-level "bigfoot" logger.

    All `logging.getLogger(__name__)` calls inside the `bigfoot` package will propagate their records up to this logger and use its handlers.

    Re-calling this function tears down the previous configuration (stopping the background listener) and installs a fresh one, so it is safe to be called more than once (e.g. to swap the log file).

    :param: level: Minimum log level for both stdout and file handlers.
    :param: log_file: Optional path; when provided, records are also written here.
    :return: logging.Logger - the package-level "bigfoot" logger.
    """
    global _lib_logger

    colorama_init()

    if _lib_logger is not None:
        _lib_logger.shutdown()

    _lib_logger = LibLogger(PACKAGE_LOGGER_NAME)
    _lib_logger.to_console(level=level)
    if log_file is not None:
        _lib_logger.to_file(log_file, level=level)

    _lib_logger._ensure_listener()
    return _lib_logger.logger


def get_lib_logger() -> Optional[LibLogger]:
    """
    A function to get the active `LibLogger` instance, or None if `configure_logging` has not been called yet.
    
    :return: Optional[LibLogger] - the active `LibLogger` instance, or None if `configure_logging` has not been called yet.
    """
    return _lib_logger