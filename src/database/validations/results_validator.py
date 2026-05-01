import logging
from ..exceptions import (
    UnsafeQueryError,
    DatabaseConnectionError,
    SchemaFetchError,
    DatabaseQueryError,
)

logger = logging.getLogger(__name__)


class ResultValidator:

    @staticmethod
    def validate_not_empty(df, query: str):
        """Raise if query returned no rows"""
        if df.empty:
            raise DatabaseQueryError(
                f"Query returned no results: {query[:100]}", code="SQL_002"
            )

    @staticmethod
    def validate_expected_columns(df, expected: list):
        """Check result has expected columns"""
        missing = set(expected) - set(df.columns)
        if missing:
            raise DatabaseQueryError(
                f"Missing expected columns: {missing}", code="SQL_003"
            )

    @staticmethod
    def validate_row_limit(df, max_rows: int):
        """Warn if result exceeds expected row count"""
        if len(df) > max_rows:
            logger.warning(f"⚠️ Result has {len(df)} rows, expected max {max_rows}")
