import json
import os
from .client import get_chroma_client, get_collection


def delete_collection(collection_name: str = None):
    """
    Permanently delete a ChromaDB collection and its associated schema files.

    Deletes:
    1. ChromaDB collection
    2. Schema files (schema.json, semantic_descriptions.json)
    3. Collection directory

    Args:
        collection_name: Name of the ChromaDB collection to delete

    Returns:
        dict with status and message
    """
    try:
        # ✅ DELETE FROM CHROMADB
        client = get_chroma_client()
        client.delete_collection(name=collection_name)
        print(f"✅ Deleted ChromaDB collection: {collection_name}")

        # ✅ DELETE SCHEMA FILES
        schema_dir = f"app/src/knowledgebase/schemas/{collection_name}"
        if os.path.exists(schema_dir):
            import shutil

            shutil.rmtree(schema_dir)
            print(f"🗑️ Deleted schema directory: {schema_dir}")
            print(f"   - Removed: schema.json")
            print(f"   - Removed: semantic_descriptions.json")
        else:
            print(f"ℹ️ Schema directory not found: {schema_dir}")

        return {
            "success": True,
            "message": f"Collection '{collection_name}' and all associated files deleted successfully",
            "collection_name": collection_name,
        }
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            print(f"ℹ️ Collection {collection_name} not found in ChromaDB")

            # ✅ Still try to delete schema files even if collection not in ChromaDB
            schema_dir = f"app/src/knowledgebase/schemas/{collection_name}"
            if os.path.exists(schema_dir):
                try:
                    import shutil

                    shutil.rmtree(schema_dir)
                    print(f"🗑️ Deleted orphaned schema directory: {schema_dir}")
                    print(f"   - Removed: schema.json")
                    print(f"   - Removed: semantic_descriptions.json")
                except Exception as cleanup_error:
                    print(f"⚠️ Could not delete schema files: {str(cleanup_error)}")

            return {
                "success": True,
                "message": f"Collection '{collection_name}' not found in ChromaDB (already deleted). Schema files cleaned up.",
                "collection_name": collection_name,
            }
        else:
            print(f"❌ Error deleting collection: {error_msg}")
            return {
                "success": False,
                "message": f"Failed to delete collection: {error_msg}",
                "error": error_msg,
            }


def clear_collection(collection_name: str = None):
    """
    Clear all documents from a Chroma collection.

    Args:
        collection_name: Name of the ChromaDB collection to clear

    Returns:
        dict with status and message
    """
    try:
        collection = get_collection(collection_name)

        # Get all IDs from collection
        all_docs = collection.get()
        ids_to_delete = all_docs.get("ids", [])

        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            print(
                f"✅ Cleared {len(ids_to_delete)} documents from collection: {collection_name}"
            )
            return {
                "success": True,
                "message": f"Cleared {len(ids_to_delete)} documents",
                "cleared_count": len(ids_to_delete),
            }
        else:
            print(f"ℹ️ Collection {collection_name} is already empty")
            return {
                "success": True,
                "message": "Collection is already empty",
                "cleared_count": 0,
            }
    except Exception as e:
        print(f"❌ Error clearing collection: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to clear collection: {str(e)}",
            "error": str(e),
        }


def ingest_tables(schema_data: list[dict], collection_name: str = None):
    """
    Ingest one semantic document per table into Chroma.
    Embeddings = semantic meaning
    Metadata = full schema structure

    Args:
        schema_data: List of table schema objects
        collection_name: Optional ChromaDB collection name (defaults to env VECTOR_COLLECTION_NAME)
    """

    collection = get_collection(collection_name)
    ids, docs, metadatas = [], [], []

    for table in schema_data:
        table_name = table["table_name"]
        table_desc = table["table_description"]
        db_name = table["database_name"]

        # ---------- SEMANTIC DOCUMENT ----------
        semantic_lines = [
            f"Database: {db_name}",
            f"Table: {table_name}",
            f"Description: {table_desc}",
            "",
            "Columns:",
        ]

        for col in table["columns"]:
            semantic_lines.append(f"- {col['name']}: {col.get('description', '')}")

        combined_text = "\n".join(semantic_lines)

        # Stable ID (safe for re-ingestion)
        doc_id = f"{db_name}.{table_name}"

        ids.append(doc_id)
        docs.append(combined_text)

        # ---------- STRUCTURAL METADATA ----------
        column_metadata = {
            col["name"]: {
                "type": col.get("type"),
                "constraint": col.get("constraint"),
                "relation": col.get("relation"),
                "sample_values": col.get("sample_values", []),
            }
            for col in table["columns"]
        }

        metadatas.append(
            {
                "database": db_name,
                "table": table_name,
                "schema_name": table.get("schema_name"),
                "num_columns": len(table["columns"]),
                "columns_json": json.dumps(column_metadata),
            }
        )

    # 🔒 Use upsert to handle re-ingestion safely
    collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
    count = collection.count()
    print(f"📦 Chroma collection count: {count}")

    print(f"✅ Ingested {len(ids)} tables into Chroma")
