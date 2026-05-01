import re
import logging
from typing import Optional
from sqlalchemy import text, inspect
from sqlalchemy.exc import OperationalError
from pydantic import BaseModel, field_validator, model_validator
from ..queries.loader import load_schema_queries
from ..exceptions import (
    UnsafeQueryError,
    DatabaseConnectionError,
    SchemaFetchError,
    DatabaseQueryError,
)

logger = logging.getLogger(__name__)


class ConnectionValidator:

    @staticmethod
    def validate_engine(engine) -> bool:
        """Validate engine can execute a basic query"""
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Engine validation passed")
            return True

        except Exception as e:
            raise e

    @staticmethod
    def validate_database_exists(engine, database: str) -> bool:
        """Check if target database exists"""
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT DB_NAME()")).fetchone()

                if result[0] != database:
                    raise DatabaseConnectionError(
                        f"Connected to '{result[0]}' but expected '{database}'",
                        code="DB_004",
                    )

            logger.info(f"✅ Database '{database}' verified")
            return True

        except DatabaseConnectionError:
            raise
        except Exception as e:
            raise DatabaseConnectionError(
                f"Database existence check failed: {str(e)}", code="DB_005"
            )

    @staticmethod
    def validate_schema_exists(engine, schema: str) -> bool:
        """Check if schema exists in database"""
        try:
            inspector = inspect(engine)
            schemas = inspector.get_schema_names()

            if schema not in schemas:
                raise SchemaFetchError(
                    f"Schema '{schema}' not found. Available: {schemas}", code="SCH_001"
                )

            logger.info(f"✅ Schema '{schema}' verified")
            return True

        except SchemaFetchError:
            raise
        except Exception as e:
            raise SchemaFetchError(
                f"Schema validation failed: {str(e)}", code="SCH_002"
            )

    @staticmethod
    def validate_table_exists(engine, table: str, schema: str) -> bool:
        """Check if a specific table exists"""
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names(schema=schema)

            if table not in tables:
                raise SchemaFetchError(
                    f"Table '{schema}.{table}' not found. " f"Available: {tables}",
                    code="SCH_003",
                )

            logger.info(f"✅ Table '{schema}.{table}' verified")
            return True

        except SchemaFetchError:
            raise
        except Exception as e:
            raise SchemaFetchError(f"Table validation failed: {str(e)}", code="SCH_004")
