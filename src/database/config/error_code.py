# ── Shared Types ─────────────────────────────────────────────────
# Each entry: "CODE": ("ERROR_TYPE", "Safe user-facing message")
# Pattern map: ("pattern", "ERROR_TYPE", "Safe user-facing message")

GENERIC_SAFE_MESSAGE = (
    "Unable to establish a connection. Please verify that the "
    "connection string is correct and the database is reachable."
)

# ── MSSQL ─────────────────────────────────────────────────────────
MSSQL_CODE_MAP = {
    "4060": (
        "DATABASE_NOT_FOUND",
        "Database not found — verify the database name and permissions.",
    ),
    "18456": ("AUTHENTICATION_FAILED", "Login failed — check USERNAME and PASSWORD."),
    "28000": ("AUTHENTICATION_FAILED", "Login failed — check USERNAME and PASSWORD."),
    "08001": (
        "SERVER_NOT_FOUND",
        "Cannot reach SQL Server — verify SERVER name and network.",
    ),
    "08S01": (
        "CONNECTION_DROPPED",
        "Network connection dropped — check network stability.",
    ),
    "HYT00": (
        "CONNECTION_TIMEOUT",
        "Connection timed out — check TIMEOUT or firewall rules.",
    ),
    "HYT01": (
        "CONNECTION_TIMEOUT",
        "Connection timed out waiting for server response.",
    ),
    "42000": (
        "PERMISSION_DENIED",
        "Permission denied — check database user privileges.",
    ),
    "23000": ("CONSTRAINT_VIOLATION", "Data integrity constraint violated."),
    "40001": ("DEADLOCK_DETECTED", "Deadlock detected — please retry the operation."),
    "IM002": (
        "DRIVER_NOT_FOUND",
        "ODBC driver not found — ensure the correct driver is installed.",
    ),
}

MSSQL_PATTERN_MAP = [
    (
        "cannot open database",
        "DATABASE_NOT_FOUND",
        "Database not found — verify the database name.",
    ),
    (
        "login failed",
        "AUTHENTICATION_FAILED",
        "Login failed — check USERNAME and PASSWORD.",
    ),
    (
        "server not found",
        "SERVER_NOT_FOUND",
        "Cannot reach SQL Server — verify SERVER name.",
    ),
    (
        "invalid object name",
        "INVALID_TABLE",
        "Table or view does not exist — check schema.",
    ),
    (
        "invalid column name",
        "INVALID_COLUMN",
        "Column does not exist — check column name.",
    ),
    (
        "timeout expired",
        "CONNECTION_TIMEOUT",
        "Connection timed out — increase TIMEOUT.",
    ),
    ("network-related", "NETWORK_ERROR", "Network error — check connectivity."),
    ("permission", "PERMISSION_DENIED", "Permission denied — check user privileges."),
    ("deadlock", "DEADLOCK_DETECTED", "Deadlock detected — please retry."),
    ("driver", "DRIVER_NOT_FOUND", "ODBC driver issue — check driver installation."),
    ("ssl", "SSL_ERROR", "SSL/TLS error — check certificate settings."),
]

# ── PostgreSQL ────────────────────────────────────────────────────
POSTGRES_CODE_MAP = {
    "28P01": (
        "AUTHENTICATION_FAILED",
        "Password authentication failed — check USERNAME and PASSWORD.",
    ),
    "28000": ("AUTHENTICATION_FAILED", "Authentication failed — check credentials."),
    "3D000": (
        "DATABASE_NOT_FOUND",
        "Database does not exist — check the DATABASE name.",
    ),
    "3F000": ("SCHEMA_NOT_FOUND", "Schema does not exist — check the schema name."),
    "08006": (
        "CONNECTION_FAILED",
        "Connection to server lost — check SERVER and network.",
    ),
    "08001": (
        "SERVER_NOT_FOUND",
        "Cannot reach PostgreSQL server — verify SERVER address.",
    ),
    "08004": (
        "CONNECTION_REJECTED",
        "Server rejected connection — check pg_hba.conf or permissions.",
    ),
    "42P01": ("INVALID_TABLE", "Table does not exist — check table name and schema."),
    "42703": ("INVALID_COLUMN", "Column does not exist — check column name."),
    "42501": ("PERMISSION_DENIED", "Insufficient privileges — check user permissions."),
    "23505": (
        "UNIQUE_VIOLATION",
        "Duplicate entry — a record with this value already exists.",
    ),
    "23503": (
        "FOREIGN_KEY_VIOLATION",
        "Foreign key violation — referenced record does not exist.",
    ),
    "23502": (
        "NOT_NULL_VIOLATION",
        "NOT NULL violation — a required field is missing.",
    ),
    "40P01": ("DEADLOCK_DETECTED", "Deadlock detected — please retry the operation."),
    "57014": (
        "QUERY_CANCELLED",
        "Query was cancelled — check for timeout or manual cancel.",
    ),
    "53300": (
        "TOO_MANY_CONNECTIONS",
        "Too many connections — increase pool size or check server limits.",
    ),
    "08003": ("CONNECTION_NOT_OPEN", "Connection is not open — reconnect and retry."),
}

POSTGRES_PATTERN_MAP = [
    (
        "password authentication failed",
        "AUTHENTICATION_FAILED",
        "Password authentication failed — check USERNAME and PASSWORD.",
    ),
    (
        "database",
        "DATABASE_NOT_FOUND",
        "Database does not exist — check the DATABASE name.",
    ),
    (
        "could not connect to server",
        "SERVER_NOT_FOUND",
        "Cannot reach PostgreSQL server — verify SERVER address.",
    ),
    (
        "connection refused",
        "SERVER_NOT_FOUND",
        "Connection refused — ensure PostgreSQL is running on SERVER:PORT.",
    ),
    (
        "could not translate host name",
        "SERVER_NOT_FOUND",
        "Unknown hostname — verify the SERVER address.",
    ),
    ("ssl", "SSL_ERROR", "SSL error — check certificate and encryption settings."),
    (
        "timeout",
        "CONNECTION_TIMEOUT",
        "Connection timed out — check TIMEOUT or firewall.",
    ),
    (
        "too many connections",
        "TOO_MANY_CONNECTIONS",
        "Too many connections — reduce POOL_SIZE or check server limits.",
    ),
    (
        "permission denied",
        "PERMISSION_DENIED",
        "Permission denied — check user privileges.",
    ),
    (
        "deadlock",
        "DEADLOCK_DETECTED",
        "Deadlock detected — please retry the operation.",
    ),
    ("duplicate key", "UNIQUE_VIOLATION", "Duplicate entry — record already exists."),
    ("not null", "NOT_NULL_VIOLATION", "Required field is missing — check your input."),
]

# ── MySQL ─────────────────────────────────────────────────────────
MYSQL_CODE_MAP = {
    "1045": ("AUTHENTICATION_FAILED", "Access denied — check USERNAME and PASSWORD."),
    "1049": ("DATABASE_NOT_FOUND", "Unknown database — check the DATABASE name."),
    "1044": (
        "PERMISSION_DENIED",
        "Access denied to database — check user permissions.",
    ),
    "1142": ("PERMISSION_DENIED", "Command denied — check table-level permissions."),
    "2003": (
        "SERVER_NOT_FOUND",
        "Cannot connect to MySQL server — verify SERVER and PORT.",
    ),
    "2005": ("SERVER_NOT_FOUND", "Unknown MySQL server host — verify SERVER address."),
    "2006": (
        "CONNECTION_LOST",
        "MySQL server has gone away — check network or increase wait_timeout.",
    ),
    "2013": (
        "CONNECTION_LOST",
        "Lost connection during query — check network stability.",
    ),
    "1040": (
        "TOO_MANY_CONNECTIONS",
        "Too many connections — reduce POOL_SIZE or increase MySQL max_connections.",
    ),
    "1146": ("INVALID_TABLE", "Table does not exist — check table name and database."),
    "1054": ("INVALID_COLUMN", "Unknown column — check column name."),
    "1062": (
        "UNIQUE_VIOLATION",
        "Duplicate entry — a record with this value already exists.",
    ),
    "1452": (
        "FOREIGN_KEY_VIOLATION",
        "Foreign key violation — referenced record does not exist.",
    ),
    "1048": (
        "NOT_NULL_VIOLATION",
        "Column cannot be null — a required field is missing.",
    ),
    "1213": ("DEADLOCK_DETECTED", "Deadlock detected — please retry the operation."),
    "1205": (
        "LOCK_TIMEOUT",
        "Lock wait timeout — another transaction is holding the lock.",
    ),
}

MYSQL_PATTERN_MAP = [
    (
        "access denied",
        "AUTHENTICATION_FAILED",
        "Access denied — check USERNAME and PASSWORD.",
    ),
    (
        "unknown database",
        "DATABASE_NOT_FOUND",
        "Database does not exist — check DATABASE name.",
    ),
    (
        "can't connect to",
        "SERVER_NOT_FOUND",
        "Cannot connect to MySQL server — verify SERVER and PORT.",
    ),
    (
        "unknown mysql server host",
        "SERVER_NOT_FOUND",
        "Unknown hostname — verify the SERVER address.",
    ),
    (
        "server has gone away",
        "CONNECTION_LOST",
        "MySQL server disconnected — check network or timeout settings.",
    ),
    (
        "too many connections",
        "TOO_MANY_CONNECTIONS",
        "Too many connections — check POOL_SIZE or MySQL limits.",
    ),
    ("ssl", "SSL_ERROR", "SSL error — check certificate and encryption settings."),
    (
        "timeout",
        "CONNECTION_TIMEOUT",
        "Connection timed out — check TIMEOUT or firewall.",
    ),
    (
        "deadlock",
        "DEADLOCK_DETECTED",
        "Deadlock detected — please retry the operation.",
    ),
    ("duplicate entry", "UNIQUE_VIOLATION", "Duplicate entry — record already exists."),
    (
        "cannot be null",
        "NOT_NULL_VIOLATION",
        "Required field is missing — check your input.",
    ),
]

# ── SQLite ────────────────────────────────────────────────────────
SQLITE_CODE_MAP = {}  # SQLite has no standard error codes

SQLITE_PATTERN_MAP = [
    (
        "unable to open database",
        "DATABASE_NOT_FOUND",
        "Database file not found — check the file path.",
    ),
    ("no such table", "INVALID_TABLE", "Table does not exist — check table name."),
    ("no such column", "INVALID_COLUMN", "Column does not exist — check column name."),
    (
        "unique constraint failed",
        "UNIQUE_VIOLATION",
        "Duplicate entry — a record with this value already exists.",
    ),
    (
        "foreign key constraint",
        "FOREIGN_KEY_VIOLATION",
        "Foreign key violation — referenced record does not exist.",
    ),
    (
        "not null constraint failed",
        "NOT_NULL_VIOLATION",
        "Required field is missing — check your input.",
    ),
    (
        "database is locked",
        "DATABASE_LOCKED",
        "Database is locked by another process — retry or check connections.",
    ),
    (
        "disk i/o error",
        "IO_ERROR",
        "Disk I/O error — check file permissions and disk health.",
    ),
    (
        "database disk image is malformed",
        "CORRUPT_DATABASE",
        "Database file is corrupted — restore from backup.",
    ),
    (
        "attempt to write a readonly",
        "PERMISSION_DENIED",
        "Database is read-only — check file permissions.",
    ),
    (
        "unable to open",
        "FILE_NOT_FOUND",
        "Cannot open database file — check the path and permissions.",
    ),
    (
        "out of memory",
        "OUT_OF_MEMORY",
        "SQLite ran out of memory — reduce query size or dataset.",
    ),
    (
        "too many open files",
        "TOO_MANY_CONNECTIONS",
        "Too many open files — reduce connection pool size.",
    ),
    (
        "permission denied",
        "PERMISSION_DENIED",
        "Permission denied — check file system permissions.",
    ),
    (
        "readonly database",
        "PERMISSION_DENIED",
        "Database is read-only — check file permissions.",
    ),
    ("syntax error", "SYNTAX_ERROR", "SQL syntax error — check your query."),
]

# ── Registry — maps dialect name to its (code_map, pattern_map) ──
# To add a new dialect: add its maps above, then register it here
DIALECT_CONFIG = {
    "mssql": (MSSQL_CODE_MAP, MSSQL_PATTERN_MAP),
    "postgresql": (POSTGRES_CODE_MAP, POSTGRES_PATTERN_MAP),
    "mysql": (MYSQL_CODE_MAP, MYSQL_PATTERN_MAP),
    "sqlite": (SQLITE_CODE_MAP, SQLITE_PATTERN_MAP),
}
