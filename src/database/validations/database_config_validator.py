import re
import logging
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator
from ..config.setting import Setting

logger = logging.getLogger(__name__)

# Create an instance of Setting to access the default values
_setting = Setting()
MAX_POOL_SIZE = _setting.MAX_POOL_SIZE
MIN_POOL_SIZE = _setting.MIN_POOL_SIZE
MAX_TIMEOUT = _setting.MAX_TIMEOUT
MIN_TIMEOUT = _setting.MIN_TIMEOUT
ALLOWED_DB_TYPES = _setting.ALLOWED_DB_TYPES


class DatabaseConfigValidator(BaseModel):
    DB_TYPE: str
    SERVER: Optional[str] = None  # ← optional for SQLite
    DATABASE: str
    USERNAME: str  # Optional[str] = None  # ← optional
    PASSWORD: str  # Optional[str] = None  # ← optional
    POOL_SIZE: int
    TIMEOUT: int

    # ── DB_TYPE ──────────────────────────────────
    @field_validator("DB_TYPE")
    @classmethod
    def validate_db_type(cls, v):
        if v not in ALLOWED_DB_TYPES:
            raise ValueError(
                f"Invalid DB_TYPE '{v}'. " f"Must be one of {ALLOWED_DB_TYPES}"
            )
        return v

    # ── SERVER ───────────────────────────────────
    @field_validator("SERVER")
    @classmethod
    def validate_server(cls, v):
        if v is not None and not v.strip():
            raise ValueError("SERVER cannot be blank")
        return v.strip() if v else None

    # ── DATABASE ─────────────────────────────────
    @field_validator("DATABASE")
    @classmethod
    def validate_database(cls, v):
        if not v or not v.strip():
            raise ValueError("DATABASE name cannot be empty")
        if not re.match(r"^[\w\-]+$", v):
            raise ValueError(f"Invalid DATABASE name: '{v}'")
        return v.strip()

    # ── USERNAME ─────────────────────────────────
    @field_validator("USERNAME")
    @classmethod
    def validate_username(cls, v):
        if v is not None:
            if not v.strip():
                raise ValueError("USERNAME cannot be blank")
            if len(v.strip()) < 2:
                raise ValueError("USERNAME must be at least 2 characters")
        return v.strip() if v else None

    # ── PASSWORD ─────────────────────────────────
    @field_validator("PASSWORD")
    @classmethod
    def validate_password(cls, v):
        if v is not None:
            if not v.strip():
                raise ValueError("PASSWORD cannot be blank")
            if len(v) < 6:
                raise ValueError("PASSWORD must be at least 6 characters")
        return v

    # ── POOL_SIZE ────────────────────────────────
    @field_validator("POOL_SIZE")
    @classmethod
    def validate_pool_size(cls, v):
        if not MIN_POOL_SIZE <= v <= MAX_POOL_SIZE:
            raise ValueError(
                f"POOL_SIZE must be between " f"{MIN_POOL_SIZE} and {MAX_POOL_SIZE}"
            )
        return v

    # ── TIMEOUT ──────────────────────────────────
    @field_validator("TIMEOUT")
    @classmethod
    def validate_timeout(cls, v):
        if not MIN_TIMEOUT <= v <= MAX_TIMEOUT:
            raise ValueError(
                f"TIMEOUT must be between " f"{MIN_TIMEOUT} and {MAX_TIMEOUT} seconds"
            )
        return v

    # ── Cross field ──────────────────────────────
    @model_validator(mode="after")
    def validate_server_required_for_non_sqlite(self):
        """Server required for all databases except SQLite"""
        if self.DB_TYPE != "sqlite" and not self.SERVER:
            raise ValueError(f"SERVER is required for DB_TYPE '{self.DB_TYPE}'")
        return self

    @model_validator(mode="after")
    def validate_credentials(self):
        """USERNAME and PASSWORD must both be present or both absent"""
        if bool(self.USERNAME) != bool(self.PASSWORD):
            raise ValueError(
                "Both USERNAME and PASSWORD must be "
                "provided together or both left empty"
            )
        return self


# if __name__ == "__main__":

#     # ── Test 1: SQL Auth ─────────────────────────────────
#     DatabaseConfigValidator(
#         DB_TYPE="mssql",
#         SERVER="(localdb)\\MSSQLLocalDB",
#         DATABASE="AdventureWorksLT",
#         USERNAME="sa",
#         PASSWORD="123456789",
#         POOL_SIZE=5,
#         TIMEOUT=30,
#     )
#     print("✅ Passed - Test 1: SQL Auth")

#     # ── Test 2: No credentials — should fail ─────────────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="mssql",
#             SERVER="(localdb)\\MSSQLLocalDB",
#             DATABASE="AdventureWorksLT",
#             USERNAME=None,  # ❌ required
#             PASSWORD=None,  # ❌ required
#             POOL_SIZE=5,
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 2: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 2: Correctly blocked — {e}")

#     # ── Test 3: SQLite no credentials — should fail ───────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="sqlite",
#             DATABASE="mydb",
#             USERNAME=None,  # ❌ required
#             PASSWORD=None,  # ❌ required
#             POOL_SIZE=5,
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 3: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 3: Correctly blocked — {e}")

#     # ── Test 4: Only username — should fail ───────────────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="mssql",
#             SERVER="localhost",
#             DATABASE="mydb",
#             USERNAME="sa",
#             PASSWORD=None,  # ❌ required
#             POOL_SIZE=5,
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 4: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 4: Correctly blocked — {e}")

#     # ── Test 5: Invalid DB_TYPE — should fail ─────────────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="oracle",  # ❌ not allowed
#             SERVER="localhost",
#             DATABASE="mydb",
#             USERNAME="user",
#             PASSWORD="pass123",
#             POOL_SIZE=5,
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 5: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 5: Correctly blocked — {e}")

#     # ── Test 6: No server for mssql — should fail ─────────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="mssql",
#             SERVER=None,  # ❌ required for mssql
#             DATABASE="mydb",
#             USERNAME="sa",
#             PASSWORD="pass123",
#             POOL_SIZE=5,
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 6: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 6: Correctly blocked — {e}")

#     # ── Test 7: Pool size out of range — should fail ───────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="mssql",
#             SERVER="localhost",
#             DATABASE="mydb",
#             USERNAME="sa",
#             PASSWORD="pass123",
#             POOL_SIZE=25,  # ❌ max is 20
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 7: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 7: Correctly blocked — {e}")

#     # ── Test 8: Short password — should fail ──────────────
#     try:
#         DatabaseConfigValidator(
#             DB_TYPE="mssql",
#             SERVER="localhost",
#             DATABASE="mydb",
#             USERNAME="sa",
#             PASSWORD="123",  # ❌ min 6 chars
#             POOL_SIZE=5,
#             TIMEOUT=30,
#         )
#         print("❌ Failed  - Test 8: Should have raised ValueError")
#     except Exception as e:
#         print(f"✅ Passed - Test 8: Correctly blocked — {e}")

#     print("\n🎉 All tests completed!")
