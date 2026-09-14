class ApplicationError(Exception):
    """Base exception for expected application-level errors."""


class ConfigurationError(ApplicationError):
    """Raised when application configuration is invalid."""
