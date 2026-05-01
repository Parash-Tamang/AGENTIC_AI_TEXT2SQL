import re
import logging
from typing import Optional
from pydantic import BaseModel, field_validator

FORBIDDEN_KEYWORDS = [
    "DROP",
    "DELETE",
    "TRUNCATE",
    "INSERT",
    "UPDATE",
    "ALTER",
    "CREATE",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "REVOKE",
    "DENY",
]

MAX_QUERY_LENGTH = 5000
MIN_QUERY_LENGTH = 5


class QueryValidator(BaseModel):
    sql: str
    max_rows: int = 100

    @field_validator("sql")
    @classmethod
    def validate_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("SQL query cannot be empty")
        return v.strip()

    @field_validator("sql")
    @classmethod
    def validate_length(cls, v):
        if len(v) < MIN_QUERY_LENGTH:
            raise ValueError(f"Query too short (min {MIN_QUERY_LENGTH} chars)")
        if len(v) > MAX_QUERY_LENGTH:
            raise ValueError(f"Query too long (max {MAX_QUERY_LENGTH} chars)")
        return v

    @field_validator("sql")
    @classmethod
    def validate_no_forbidden_keywords(cls, v):
        sql_upper = v.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            # Match whole words only e.g. avoid blocking "EXECUTE" in "EXECUTED"
            pattern = rf"\b{keyword}\b"
            if re.search(pattern, sql_upper):
                raise ValueError(f"Forbidden keyword detected: {keyword}")
        return v

    @field_validator("sql")
    @classmethod
    def validate_starts_with_select(cls, v):
        if not v.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")
        return v

    @field_validator("sql")
    @classmethod
    def validate_single_statement(cls, v):
        # Allow one optional trailing semicolon, but reject semicolons mid-query
        # e.g. "SELECT 1; DROP TABLE users" should be rejected
        if ";" in v.rstrip(";"):
            raise ValueError("Only a single SQL statement is allowed")
        return v

    @field_validator("max_rows")
    @classmethod
    def validate_max_rows(cls, v):
        if v < 1 or v > 10000:
            raise ValueError("max_rows must be between 1 and 10000")
        return v
