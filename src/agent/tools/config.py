from dataclasses import dataclass
from typing import Optional


@dataclass
class ConnectionConfig:
    db_type: str
    server: str
    database: str
    username: Optional[str]
    password: Optional[str]
    port: Optional[int] = None
    pool_size: int = 5
    timeout: int = 30


_config: Optional[ConnectionConfig] = None


def set_connection_config(config: ConnectionConfig):
    global _config
    _config = config


def get_connection_config() -> ConnectionConfig:
    global _config
    if _config is None:
        return ConnectionConfig(
            db_type="mssql",
            server=r"(localdb)\MSSQLLocalDB",
            database="AdventureWorksLT2019",
            username="sa",
            password="1234567890",
            port=None,
            pool_size=5,
            timeout=30,
        )
    return _config


def reset_connection_config():
    global _config
    _config = None
