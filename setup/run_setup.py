import json
import os
import pyodbc
from dotenv import load_dotenv

from .fetch_schema import fetch_schema
from .format_schema import enrich_schema
from .generate_descriptions.runner import generate_all
from .data_ingestion import ingest_tables, get_collection

load_dotenv()


def parse_pyodbc_error(error: pyodbc.Error, connection_string: str = None) -> dict:
    """
    Parse pyodbc errors and provide user-friendly error messages.

    Uses ODBC error codes first, then specific keyword patterns.

    Args:
        error: pyodbc.Error exception
        connection_string: Connection string (for context)

    Returns:
        dict: {"error_type": str, "message": str}
    """
    error_str = str(error).lower()

    # ═══════════════════════════════════════════════════════════
    # CHECK FOR SPECIFIC ERROR CONDITIONS FIRST (before state codes)
    # ═══════════════════════════════════════════════════════════

    # Extract ODBC error code and state from error args
    error_code = None
    error_state = None
    if error.args:
        try:
            error_code = error.args[0]  # Usually a tuple like ('08001', '...')
            if isinstance(error_code, tuple):
                error_state = error_code[0]  # e.g., '08001'
        except (IndexError, TypeError):
            pass

    # ═══════════════════════════════════════════════════════════
    # ODBC ERROR CODES - Priority Order:
    # 4060 > 18456 > 28000 > 08001
    # ═══════════════════════════════════════════════════════════
    print(error_str)
    print("error code:", error_code)
    print("error state:", type(error_state))
    # 4060 = Database not found (most specific)
    print("error state:", error_code == "08001")
    if error_code == "4060" and "cannot open database" in error_str:
        return {
            "error_type": "DATABASE_ACCESS_ERROR",
            "message": "The specified database could not be accessed. Please verify the database name and permissions.",
        }

    # 15517 or 42000 = Permission error (e.g., user does not exist or lacks permissions)
    elif "15517" in error_str or "42000" in error_str:
        return {
            "error_type": "PERMISSION_ERROR",
            "message": "Database execution context error. Required database user does not exist or does not have a permission.",
        }

    # 18456 = Login failed with invalid username/password
    elif error_code == "18456" or "(18456)" in error_str:
        return {
            "error_type": "AUTHENTICATION_FAILED",
            "message": "Login failed. Please check the username and password.",
        }

    # 28000 = General authentication error
    elif error_code == "28000" or "login failed" in error_str:
        return {
            "error_type": "AUTHENTICATION_FAILED",
            "message": "Authentication failed. Please verify the authentication method or access permissions.",
        }

    # 08001 = Connection error (least specific)
    elif error_code == "08001":

        return {
            "error_type": "CONNECTION_FAILED",
            "message": "Could not connect to the SQL Server. Please verify the server name, instance, or network connectivity.",
        }

    # ═══════════════════════════════════════════════════════════
    # FALLBACK: Generic error response
    # ═══════════════════════════════════════════════════════════

    # Generic fallback
    return {
        "error_type": "CONNECTION_ERROR",
        "message": "An error occurred while connecting to the database. Please verify your connection settings.",
    }


def verify_connection(payload: dict, timeout: int = 10) -> dict:
    """
    Verify database connection before schema extraction using unified auth logic.

    Args:
        payload: dict with connection parameters (server, database_name, auth_mode, username, password, etc)
        timeout: Connection timeout in seconds

    Returns:
        dict: {"success": bool, "message": str, "version": str or None}
    """
    try:
        from agent_root.app.src.connection_builder import ConnectionStringBuilder

        builder = ConnectionStringBuilder()
        validation = builder.validate_payload(payload)
        if not validation["valid"]:
            return {
                "success": False,
                "message": validation["error"],
                "error_type": "INVALID_PAYLOAD",
            }
        connection_string = builder.build(**payload)
        database_name = payload.get("database_name", "")
        server_name = payload.get("server", "")
        auth_mode = payload.get("auth_mode", "sql").lower()
        username = payload.get("username", "")
        password = payload.get("password", "")

        # Print connection details for debugging
        print("\n" + "=" * 80)
        print("🔍 VERIFYING DATABASE CONNECTION")
        print("=" * 80)
        print(f"📍 Server: {server_name}")
        print(f"📦 Database: {database_name}")
        print(f"🔐 Auth Mode: {auth_mode.upper()}")
        if auth_mode == "sql":
            print(f"👤 Username: {username}")
            print(f"🔑 Password: {'*' * len(password) if password else '[EMPTY]'}")
        else:
            print(f"👤 Username: [Windows Integrated Auth]")
        print(f"⏱️  Timeout: {timeout} seconds")
        print("=" * 80)

        print(f"\n🔄 Attempting connection...")
        conn = pyodbc.connect(connection_string, timeout=timeout)
        cursor = conn.cursor()

        # Get SQL Server version (initial connection check)
        print("✅ Connected to SQL Server instance")
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]

        # Switch to target database using USE statement
        print(f"🔄 Switching to database: {database_name}")
        cursor.execute(f"USE {database_name}")
        print(f"✅ Successfully switched to database: {database_name}")

        # Verify we're in the correct database
        cursor.execute("SELECT DB_NAME()")
        current_db = cursor.fetchone()[0]
        if current_db != database_name:
            raise Exception(
                f"Database mismatch: Expected {database_name}, got {current_db}"
            )
        print(f"✅ Verified current database: {current_db}")

        # Count tables to verify database access
        cursor.execute(f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES")
        table_count = cursor.fetchone()[0]
        print(f"✅ Database has {table_count} tables")

        cursor.close()
        conn.close()

        print(f"\n✅ CONNECTION SUCCESSFUL!")
        print("=" * 80)
        print(f"📍 Server: {server_name}")
        print(f"📦 Database: {database_name}")
        print(f"👤 Connected as: {auth_mode.upper()}")
        print(f"📊 Tables found: {table_count}")
        print(f"🔧 SQL Server: {version.split(',')[0][:60]}...")
        print("=" * 80)

        return {
            "success": True,
            "message": f"Connection successful to {database_name}",
            "version": version,
        }
    except pyodbc.Error as e:
        error_info = parse_pyodbc_error(e)
        error_msg = str(e)

        print(f"\n❌ CONNECTION FAILED!")
        print("=" * 80)
        print(f"📍 Server: {server_name}")
        print(f"📦 Database: {database_name}")
        print(f"🔐 Auth Mode: {auth_mode.upper()}")
        if auth_mode == "sql":
            print(f"👤 Username: {username}")
        else:
            print(f"👤 Auth: Windows Integrated")
        print("=" * 80)

        print(f"\n📋 Error Type: {error_info['error_type']}")
        print(f"❌ {error_info['message']}")
        return {
            "success": False,
            "message": error_info["message"],
            "error_type": error_info["error_type"],
            "raw_error": error_msg,
        }
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Verification error: {error_msg}")
        return {
            "success": False,
            "message": "Connection verification failed",
            "error": error_msg,
        }


def run(
    payload: dict,
    db_id: str,
    role: str = None,
) -> dict:
    """
    Dynamic knowledge base setup from auth payload.

    Builds schema from database, generates semantic descriptions,
    and ingests into ChromaDB collection named by db_id.

    Args:
        payload: dict with connection parameters (server, database_name, auth_mode, username, password, trust_certificate, connection_timeout)
        db_id: Collection identifier for ChromaDB
        role: Optional role to assume when fetching schema

    Returns:
        dict with status, message, and metadata

    Raises:
        RuntimeError: If setup fails at any stage
        pyodbc.Error: If database connection fails
    """
    from agent_root.app.src.connection_builder import ConnectionStringBuilder

    builder = ConnectionStringBuilder()
    validation = builder.validate_payload(payload)
    if not validation["valid"]:
        return {
            "success": False,
            "message": validation["error"],
            "error_type": "INVALID_PAYLOAD",
            "db_id": db_id,
        }

    connection_string = builder.build(**payload)
    database_name = payload.get("database_name", "")

    schema_path, semantic_path = get_paths(db_id)

    print("\n" + "=" * 80)
    print("[KNOWLEDGE BASE SETUP - Dynamic Configuration]")
    print(f"  Database: {database_name}")
    print(f"  Collection: {db_id}")
    print(f"  Role: {role or 'default'}")
    print("=" * 80)

    try:
        # ─────────────────────────────
        # CASE 1: Schema already exists
        # ─────────────────────────────
        if os.path.exists(schema_path):
            print(f"📄 Found existing schema: {schema_path}")
            print("➡️ Skipping DB fetch")

            generate_all(schema_file=schema_path, output_file=semantic_path)

            # Load semantic descriptions and ingest into ChromaDB
            with open(semantic_path, "r", encoding="utf-8") as f:
                semantic_data = json.load(f)
            ingest_tables(semantic_data, collection_name=db_id)
            print(f"✅ Schema ingested into ChromaDB collection: {db_id}")

            return {
                "success": True,
                "message": "✅ Knowledge base setup completed (using cached schema)",
                "db_id": db_id,
                "collection_name": db_id,
                "database_name": database_name,
            }

        # ─────────────────────────────
        # CASE 2: Build schema from DB
        # ─────────────────────────────
        print("📄 Schema not found — building from database")

        # ✅ VERIFY CONNECTION BEFORE SCHEMA EXTRACTION
        verification = verify_connection(payload)
        if not verification["success"]:
            print(f"\n❌ Connection verification failed")
            return {
                "success": False,
                "message": verification["message"],
                "error_type": verification.get("error_type", "UNKNOWN"),
                "db_id": db_id,
            }

        # Connect to database
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # ✅ Select correct database
        cursor.execute(f"USE {database_name}")

        # ✅ Switch role context if provided
        if role:
            cursor.execute(f"EXECUTE AS USER = '{role}'")

        print("✅ Connected to database")

        # Fetch schema from database
        schema = fetch_schema(conn, database_name=database_name)
        print("✅ Schema fetched")

        # Enrich schema with samples and descriptions
        enriched = enrich_schema(schema=schema, conn=conn)
        print("✅ Schema enriched")

        # Close database connection
        cursor.close()
        conn.close()

        # Save enriched schema to file
        os.makedirs(os.path.dirname(schema_path), exist_ok=True)

        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=2)

        print(f"✅ Schema written to {schema_path}")

        # Generate semantic descriptions using LLM
        generate_all(schema_file=schema_path, output_file=semantic_path)
        print("✅ Semantic descriptions generated")

        # Load semantic descriptions and ingest into ChromaDB
        with open(semantic_path, "r", encoding="utf-8") as f:
            semantic_data = json.load(f)
        ingest_tables(semantic_data, collection_name=db_id)
        print(f"✅ Schema ingested into ChromaDB collection: {db_id}")

        return {
            "success": True,
            "message": "✅ Knowledge base setup completed successfully",
            "db_id": db_id,
            "collection_name": db_id,
            "database_name": database_name,
            "schema_path": schema_path,
            "semantic_path": semantic_path,
        }

    except pyodbc.Error as e:
        # Use custom error parsing for database errors
        error_info = parse_pyodbc_error(e, connection_string)
        print(f"❌ {error_info['message']}")

        return {
            "success": False,
            "message": error_info["message"],
            "error_type": error_info["error_type"],
            "db_id": db_id,
        }
    except Exception as e:
        print(f"❌ Setup error: {e}")
        return {
            "success": False,
            "message": f"Knowledge base setup failed: {str(e)}",
            "db_id": db_id,
            "error": str(e),
        }


def update(
    payload: dict,
    db_id: str,
    role: str = None,
) -> dict:
    """
    Update an existing knowledge base collection with fresh data from database.

    Fetches current schema from database, generates new semantic descriptions,
    and replaces data in the existing ChromaDB collection.

    Args:
        payload: dict with connection parameters (server, database_name, auth_mode, username, password, trust_certificate, connection_timeout)
        db_id: Collection identifier for ChromaDB (must exist)
        role: Optional role to assume when fetching schema

    Returns:
        dict with status, message, and metadata

    Raises:
        RuntimeError: If update fails at any stage
        pyodbc.Error: If database connection fails
    """
    from agent_root.app.src.connection_builder import ConnectionStringBuilder
    from .data_ingestion import clear_collection
    from .client import collection_exists

    # ✅ VALIDATE COLLECTION EXISTS BEFORE PROCEEDING
    if not collection_exists(db_id):
        print(f"❌ Collection '{db_id}' does not exist in ChromaDB")
        return {
            "success": False,
            "message": f"Collection '{db_id}' does not exist. Cannot update non-existent collection. Please create it first using the Setup endpoint.",
            "error_type": "COLLECTION_NOT_FOUND",
            "db_id": db_id,
        }

    builder = ConnectionStringBuilder()
    validation = builder.validate_payload(payload)
    if not validation["valid"]:
        return {
            "success": False,
            "message": validation["error"],
            "error_type": "INVALID_PAYLOAD",
            "db_id": db_id,
        }

    connection_string = builder.build(**payload)
    database_name = payload.get("database_name", "")

    schema_path, semantic_path = get_paths(db_id)

    print("\n" + "=" * 80)
    print("[KNOWLEDGE BASE UPDATE - Refreshing Data]")
    print(f"  Database: {database_name}")
    print(f"  Collection: {db_id}")
    print(f"  Role: {role or 'default'}")
    print("=" * 80)

    try:
        # ✅ VERIFY CONNECTION BEFORE SCHEMA EXTRACTION
        print("🔍 Verifying database connection...")
        verification = verify_connection(payload)
        if not verification["success"]:
            print(f"❌ Connection verification failed")
            return {
                "success": False,
                "message": verification["message"],
                "error_type": verification.get("error_type", "UNKNOWN"),
                "db_id": db_id,
            }

        # Connect to database
        print("🔄 Connecting to database...")
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # ✅ Select correct database
        cursor.execute(f"USE {database_name}")

        # ✅ Switch role context if provided
        if role:
            cursor.execute(f"EXECUTE AS USER = '{role}'")

        print("✅ Connected to database")

        # Fetch fresh schema from database
        print("📄 Fetching fresh schema from database...")
        schema = fetch_schema(conn, database_name=database_name)
        print("✅ Schema fetched")

        # Enrich schema with samples and descriptions
        print("🔧 Enriching schema with samples and descriptions...")
        enriched = enrich_schema(schema=schema, conn=conn)
        print("✅ Schema enriched")

        # Close database connection
        cursor.close()
        conn.close()

        # Save enriched schema to file (overwrite existing)
        os.makedirs(os.path.dirname(schema_path), exist_ok=True)
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=2)
        print(f"✅ Updated schema written to {schema_path}")

        # ✅ DELETE OLD SEMANTIC DESCRIPTIONS TO FORCE REGENERATION
        if os.path.exists(semantic_path):
            os.remove(semantic_path)
            print(f"🗑️ Removed old semantic descriptions: {semantic_path}")

        # Generate fresh semantic descriptions using LLM
        print("🤖 Generating fresh semantic descriptions...")
        generate_all(schema_file=schema_path, output_file=semantic_path)
        print("✅ Semantic descriptions generated")

        # ✅ CLEAR EXISTING COLLECTION
        print(f"🗑️ Clearing existing collection: {db_id}...")
        clear_result = clear_collection(collection_name=db_id)
        if not clear_result["success"]:
            return {
                "success": False,
                "message": f"Failed to clear collection: {clear_result['message']}",
                "db_id": db_id,
                "error": clear_result.get("error"),
            }
        print(f"✅ Cleared {clear_result['cleared_count']} old documents")

        # Load new semantic descriptions and ingest into ChromaDB
        print("📦 Ingesting fresh data into ChromaDB...")
        with open(semantic_path, "r", encoding="utf-8") as f:
            semantic_data = json.load(f)
        ingest_tables(semantic_data, collection_name=db_id)
        print(f"✅ Fresh schema ingested into ChromaDB collection: {db_id}")

        print("\n" + "=" * 80)
        print("✅ KNOWLEDGE BASE UPDATE COMPLETED SUCCESSFULLY")
        print("=" * 80)

        return {
            "success": True,
            "message": "✅ Knowledge base updated successfully",
            "db_id": db_id,
            "collection_name": db_id,
            "database_name": database_name,
            "schema_path": schema_path,
            "semantic_path": semantic_path,
            "cleared_count": clear_result["cleared_count"],
        }

    except pyodbc.Error as e:
        # Use custom error parsing for database errors
        error_info = parse_pyodbc_error(e, connection_string)
        print(f"❌ {error_info['message']}")

        return {
            "success": False,
            "message": error_info["message"],
            "error_type": error_info["error_type"],
            "db_id": db_id,
        }
    except Exception as e:
        print(f"❌ Update error: {e}")
        return {
            "success": False,
            "message": f"Knowledge base update failed: {str(e)}",
            "db_id": db_id,
            "error": str(e),
        }


def get_paths(db_id: str):
    """
    Generate dynamic schema and semantic paths based on database_id.
    Args:
        db_id: Database/collection identifier
    Returns:
        tuple: (schema_path, semantic_path)
    """
    schema_path = f"app/src/knowledgebase/schemas/{db_id}/schema.json"
    semantic_path = f"app/src/knowledgebase/schemas/{db_id}/semantic_descriptions.json"
    return schema_path, semantic_path


if __name__ == "__main__":
    # Legacy: Direct execution (requires .env setup)
    database_name = os.getenv("DB_NAME")
    if not database_name:
        raise RuntimeError("❌ DB_NAME not set in .env")

    # This would need updated to use new signature
    print("ℹ️  Use API endpoint for knowledge base setup")
    print("Direct execution no longer supported with new dynamic configuration")
