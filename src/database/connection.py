import hashlib
import logging
import threading
from sqlalchemy import create_engine, text
from pydantic import BaseModel, field_validator, model_validator

from .validations.connection_validator import ConnectionValidator
from .exceptions import DatabaseConnectionError
from .error_parser import DatabaseErrorParser

logger = logging.getLogger(__name__)


class HealthCheckResult(BaseModel):
    """Validated health check response."""

    status: str
    server: str | None = None
    database: str | None = None
    version: str | None = None
    error: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in ["healthy", "unhealthy"]:
            raise ValueError("status must be 'healthy' or 'unhealthy'")
        return v

    @model_validator(mode="after")
    def validate_healthy_has_fields(self):
        if self.status == "healthy":
            if not self.server or not self.database:
                raise ValueError("Healthy status requires server and database")
        return self

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"


class DatabaseConnection:
    _engines = {}
    _lock = threading.Lock()

    HEALTH_QUERIES = {
        "mssql": {
            "version": "SELECT @@VERSION",
            "database": "SELECT DB_NAME()",
            "server": "SELECT @@SERVERNAME",
        },
        "postgresql": {
            "version": "SELECT version()",
            "database": "SELECT current_database()",
            "server": "SELECT inet_server_addr()",
        },
        "mysql": {
            "version": "SELECT version()",
            "database": "SELECT DATABASE()",
            "server": "SELECT @@hostname",
        },
        "sqlite": {
            "version": "SELECT sqlite_version()",
            "database": None,
            "server": None,
        },
    }

    @classmethod
    def create_engine(
        cls,
        connection_string: str,
        pool_size: int = 5,
        pool_timeout: int = 30,
        dialect: str = "mssql",
    ):
        """
        Create and cache a SQLAlchemy engine per connection string.
        If engine for this connection already exists, return the cached one.

        Raises:
            DatabaseConnectionError: with a safe, user-facing message
        """
        conn_hash = hashlib.md5(connection_string.encode()).hexdigest()

        # Fast path — check outside lock first
        if conn_hash in cls._engines:
            logger.info(f"Returning cached engine for hash: {conn_hash}")
            return cls._engines[conn_hash]

        with cls._lock:
            # Re-check inside lock — another thread may have created it
            if conn_hash in cls._engines:
                logger.info(f"Returning cached engine for hash: {conn_hash}")
                return cls._engines[conn_hash]

            try:
                logger.info(f"Creating NEW engine for hash: {conn_hash}")
                engine = create_engine(
                    connection_string,
                    pool_pre_ping=True,
                    pool_size=pool_size,
                    pool_timeout=pool_timeout,
                )
                ConnectionValidator.validate_engine(engine)
                cls._engines[conn_hash] = engine
                logger.info("Engine created, validated, and cached successfully.")
                return engine

            except Exception as e:
                cls._engines.pop(conn_hash, None)
                parsed = DatabaseErrorParser.parse(e, dialect=dialect)
                logger.error(
                    "Engine creation failed [%s]: %s",
                    parsed["error_type"],
                    str(e),
                )
                raise DatabaseConnectionError(parsed["message"], code="DB_001")

    @classmethod
    def get_engine(cls, connection_string: str = None):
        """
        Return a cached engine for the given connection string.
        If no connection_string provided, returns first available engine or None.
        """
        conn_hash = hashlib.md5(connection_string.encode()).hexdigest()
        return cls._engines.get(conn_hash)

    @classmethod
    def health_check(
        cls, connection_string: str = None, dialect: str = "mssql"
    ) -> HealthCheckResult:
        """
        Run a lightweight health check against the database.
        If no connection_string provided, checks the first available engine.

        Returns HealthCheckResult — never raises.
        """
        engine = cls.get_engine(connection_string)
        if engine is None:
            return HealthCheckResult(
                status="unhealthy",
                error="Engine not initialized — call create_engine() first.",
            )

        queries = cls.HEALTH_QUERIES.get(dialect)
        if queries is None:
            return HealthCheckResult(
                status="unhealthy",
                error=f"Unsupported dialect: {dialect}",
            )

        try:
            with engine.connect() as conn:

                def _query(sql: str | None) -> str | None:
                    if sql is None:
                        return None
                    row = conn.execute(text(sql)).fetchone()
                    return row[0] if row else None

                version = _query(queries["version"])
                database = _query(queries["database"])
                server = _query(queries["server"])

            return HealthCheckResult(
                status="healthy",
                server=str(server) if server else dialect,
                database=str(database) if database else engine.url.database,
                version=str(version).splitlines()[0][:100] if version else None,
            )

        except Exception as e:
            parsed = DatabaseErrorParser.parse(e, dialect=dialect)
            logger.error(
                "Health check failed [%s]: %s",
                parsed["error_type"],
                str(e),
            )
            return HealthCheckResult(
                status="unhealthy",
                error=parsed["message"],
            )

    @classmethod
    def verify(cls, connection_string: str = None, dialect: str = "mssql") -> bool:
        """
        Verify an engine can still connect.

        Raises:
            DatabaseConnectionError: if engine is missing or validation fails
        """
        engine = cls.get_engine(connection_string)
        if engine is None:
            raise DatabaseConnectionError(
                "Engine not initialized — call create_engine() first.", code="DB_002"
            )

        try:
            ConnectionValidator.validate_engine(engine)
            return True

        except DatabaseConnectionError:
            raise

        except Exception as e:
            parsed = DatabaseErrorParser.parse(e, dialect=dialect)
            logger.error("Verification failed [%s]: %s", parsed["error_type"], str(e))
            raise DatabaseConnectionError(parsed["message"], code="DB_002")

    @classmethod
    def dispose(cls, connection_string: str = None):
        """
        Dispose connection pool(s).
        If connection_string provided, dispose only that engine.
        If not provided, dispose all engines.
        """
        with cls._lock:
            if connection_string:
                conn_hash = hashlib.md5(connection_string.encode()).hexdigest()
                if conn_hash in cls._engines:
                    cls._engines[conn_hash].dispose()
                    del cls._engines[conn_hash]
                    logger.info(f"Connection pool disposed for hash: {conn_hash}")
            else:
                for conn_hash, engine in list(cls._engines.items()):
                    engine.dispose()
                    del cls._engines[conn_hash]
                logger.info("All connection pools disposed.")
