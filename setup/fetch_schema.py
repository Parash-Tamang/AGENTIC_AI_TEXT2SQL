import pyodbc


SCHEMA_QUERY = """
SELECT 
    s.name AS SchemaName,
    t.name AS TableName,
    c.name AS ColumnName,
    ty.name AS DataType,
    c.is_nullable AS IsNullable,
    CASE 
        WHEN pk.column_id IS NOT NULL THEN 'Primary Key'
        WHEN fk.parent_column_id IS NOT NULL THEN 'Foreign Key'
        ELSE NULL 
    END AS KeyType,
    OBJECT_NAME(fk.referenced_object_id) AS ReferencesTable,
    fk.referenced_column_name AS ReferencesColumn
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.columns c ON t.object_id = c.object_id
JOIN sys.types ty ON c.user_type_id = ty.user_type_id
LEFT JOIN (
    SELECT i.object_id, ic.column_id
    FROM sys.indexes i
    JOIN sys.index_columns ic 
        ON i.object_id = ic.object_id 
        AND i.index_id = ic.index_id
    WHERE i.is_primary_key = 1
) pk ON c.object_id = pk.object_id 
     AND c.column_id = pk.column_id
LEFT JOIN (
    SELECT 
        f.parent_object_id, 
        f.referenced_object_id, 
        fc.parent_column_id, 
        rc.name AS referenced_column_name
    FROM sys.foreign_keys f
    JOIN sys.foreign_key_columns fc 
        ON f.object_id = fc.constraint_object_id
    JOIN sys.columns rc 
        ON fc.referenced_column_id = rc.column_id 
        AND fc.referenced_object_id = rc.object_id
) fk ON c.object_id = fk.parent_object_id 
     AND c.column_id = fk.parent_column_id
ORDER BY s.name, t.name, c.column_id;

"""


def fetch_schema(conn, database_name):

    cursor = conn.cursor()
    cursor.execute(f"USE {database_name}")
    cursor.execute(SCHEMA_QUERY)
    rows = cursor.fetchall()

    schema = {}

    for r in rows:
        schema_name = r.SchemaName
        table_name = r.TableName
        column_name = r.ColumnName

        table_key = f"{database_name}.{schema_name}.{table_name}"

        if table_key not in schema:
            schema[table_key] = {
                "database": database_name,
                "schema": schema_name,
                "table": table_name,
                "columns": {},
            }

        col_obj = {
            "type": r.DataType.upper(),
            "nullable": bool(r.IsNullable),
            "key": None,
            "references": None,
        }

        if r.KeyType == "Primary Key":
            col_obj["key"] = "primary"

        elif r.KeyType == "Foreign Key":
            col_obj["key"] = "foreign"
            col_obj["references"] = {
                "table": r.ReferencesTable,
                "column": r.ReferencesColumn,
            }

        schema[table_key]["columns"][column_name] = col_obj

    return schema
