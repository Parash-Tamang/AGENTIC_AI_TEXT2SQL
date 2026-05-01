from src.exceptions import AppBaseException


class UnsafeQueryError(AppBaseException):
    """Raised when a query is deemed unsafe or contains malicious content"""

    pass


class DatabaseConnectionError(AppBaseException):
    """Raised when database connection fails"""

    pass


class SchemaFetchError(AppBaseException):
    """Raised when schema fetch from database fails"""

    pass


class DatabaseQueryError(AppBaseException):
    """Raised when database query execution fails or returns invalid results"""

    pass
