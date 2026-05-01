from pydantic import BaseModel, ConfigDict


class Setting(BaseModel):
    # This prevents any changes after the model is created
    model_config = ConfigDict(frozen=True)

    MAX_POOL_SIZE: int = 20
    TIMEOUT: int = 30
    MIN_POOL_SIZE: int = 1
    MAX_TIMEOUT: int = 300
    MIN_TIMEOUT: int = 1
    ALLOWED_DB_TYPES: list = ["mssql", "postgresql", "mysql", "sqlite"]
