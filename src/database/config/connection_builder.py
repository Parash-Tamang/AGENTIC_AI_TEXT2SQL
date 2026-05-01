import urllib
import logging
from pydantic import BaseModel, field_validator, model_validator, ValidationError
from typing import Optional
from ..validations.database_config_validator import DatabaseConfigValidator

logger = logging.getLogger(__name__)


class ConnectionBuilder(BaseModel):
    """
    Accepts raw config, validates via DatabaseConfigValidator,
    and builds the correct connection string per DB type.
    """

    DB_TYPE: str
    SERVER: Optional[str] = None
    DATABASE: str
    USERNAME: str
    PASSWORD: str
    POOL_SIZE: int = 5
    TIMEOUT: int = 30
    PORT: Optional[int] = None
    # SCHEMA: str = "dbo"

    # ── Validate on init ─────────────────────────────
    def model_post_init(self, __context):
        """Run DatabaseConfigValidator after init with clean error handling"""
        try:
            DatabaseConfigValidator(
                DB_TYPE=self.DB_TYPE,
                SERVER=self.SERVER,
                DATABASE=self.DATABASE,
                USERNAME=self.USERNAME,
                PASSWORD=self.PASSWORD,
                POOL_SIZE=self.POOL_SIZE,
                TIMEOUT=self.TIMEOUT,
            )
        except ValidationError as e:
            # Extract first error for clean message
            first_error = e.errors()[0]
            field = first_error["loc"][0]
            msg = first_error["msg"]
            logger.error(f"Config validation failed: {field} - {msg}")
            raise ValueError(f"Invalid {field}: {msg}") from e

    # ── Build ────────────────────────────────────────
    def build(self) -> str:
        """Build connection string based on DB_TYPE"""
        builders = {
            "mssql": self._build_mssql,
            "postgresql": self._build_postgresql,
            "mysql": self._build_mysql,
            "sqlite": self._build_sqlite,
        }
        conn_str = builders[self.DB_TYPE]()
        logger.info(
            f"✅ Connection string built for " f"{self.DB_TYPE} → {self.DATABASE}"
        )
        return conn_str

    # ── MSSQL ────────────────────────────────────────
    def _build_mssql(self) -> str:
        params = urllib.parse.quote_plus(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={self.SERVER};"
            f"DATABASE={self.DATABASE};"
            f"UID={self.USERNAME};"
            f"PWD={self.PASSWORD};"
            f"TrustServerCertificate=yes;"
        )
        return f"mssql+pyodbc:///?odbc_connect={params}"

    # ── PostgreSQL ───────────────────────────────────
    def _build_postgresql(self) -> str:
        port = self.PORT or 5432
        return (
            f"postgresql+psycopg2://"
            f"{self.USERNAME}:{self.PASSWORD}"
            f"@{self.SERVER}:{port}/{self.DATABASE}"
        )

    # ── MySQL ────────────────────────────────────────
    def _build_mysql(self) -> str:
        port = self.PORT or 3306
        return (
            f"mysql+mysqlconnector://"
            f"{self.USERNAME}:{self.PASSWORD}"
            f"@{self.SERVER}:{port}/{self.DATABASE}"
        )

    # ── SQLite ───────────────────────────────────────
    def _build_sqlite(self) -> str:
        return f"sqlite:///{self.DATABASE}.db"
