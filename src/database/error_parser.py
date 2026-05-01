import logging
from sqlalchemy.exc import (
    OperationalError,
    ProgrammingError,
    IntegrityError,
    TimeoutError as SATimeoutError,
)
from src.database.config.error_code import DIALECT_CONFIG, GENERIC_SAFE_MESSAGE

logger = logging.getLogger(__name__)


class DatabaseErrorParser:

    @classmethod
    def parse(cls, error: Exception, dialect: str = "mssql") -> dict:
        """
        Parse a database error into a safe structured response.

        Returns:
            {
                "error_type": "AUTHENTICATION_FAILED",
                "message":    "Login failed — check USERNAME and PASSWORD.",
                "dialect":    "mssql"
            }
        """
        raw_error = cls._unwrap(error)

        if dialect not in DIALECT_CONFIG:
            logger.error("Unhandled dialect '%s': %s", dialect, error)
            return {
                "error_type": "DATABASE_CONNECTION_ERROR",
                "message": GENERIC_SAFE_MESSAGE,
                "dialect": dialect,
            }

        code_map, pattern_map = DIALECT_CONFIG[dialect]
        code, error_str = cls._extract_code(raw_error, dialect)
        result = cls._match(code, error_str, code_map, pattern_map)
        result["dialect"] = dialect
        return result

    @classmethod
    def _unwrap(cls, error: Exception) -> Exception:
        """Strip SQLAlchemy wrapper to get the real driver error."""
        if isinstance(
            error, (OperationalError, ProgrammingError, IntegrityError, SATimeoutError)
        ):
            return error.__cause__ or error.__context__ or error
        return error

    @classmethod
    def _extract_code(cls, error: Exception, dialect: str) -> tuple[str | None, str]:
        """
        Extract (error_code, error_string) based on dialect.

        - mssql      → args[0] SQLSTATE string
        - postgresql → error.pgcode attribute
        - mysql      → args[0] numeric code
        - sqlite     → no codes, string only
        """
        error_str = str(error).lower()

        if dialect == "postgresql":
            code = getattr(error, "pgcode", None)

        elif dialect == "sqlite":
            # Combine error string + args[0] for better pattern coverage
            detail = ""
            if hasattr(error, "args") and len(error.args) >= 1:
                detail = str(error.args[0]).lower()
            error_str = f"{error_str} {detail}".strip()
            code = None

        else:
            # mssql and mysql both use args[0] as code
            code = None
            if hasattr(error, "args") and len(error.args) >= 1:
                try:
                    candidate = str(error.args[0]).strip()
                    if len(candidate) <= 6:  # SQLSTATE/MySQL codes are short
                        code = candidate
                except (IndexError, TypeError):
                    pass

        return code, error_str

    @classmethod
    def _match(
        cls,
        code: str | None,
        error_str: str,
        code_map: dict,
        pattern_map: list,
    ) -> dict:
        # 1. Exact code match
        if code and code in code_map:
            error_type, message = code_map[code]
            return {"error_type": error_type, "message": message}

        # 2. String pattern fallback
        for pattern, error_type, message in pattern_map:
            if pattern in error_str:
                return {"error_type": error_type, "message": message}

        # 3. Generic fallback — log real error, return safe message
        logger.error("Unmatched error (code=%s): %s", code, error_str)
        return {
            "error_type": "UNKNOWN_ERROR",
            "message": GENERIC_SAFE_MESSAGE,
        }
