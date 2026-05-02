#!/usr/bin/env python3
"""
Test script to demonstrate indexing JSON schema into two separate vector database collections:
- Collection 1: table_schemas (for tables)
- Collection 2: view_schemas (for views)
"""

import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.knowledgebase.indexer import Indexer


def main():
    """Index schemas from JSON files into separate vector database collections."""

    base_path = Path(__file__).parent
    schema_json = base_path / "assets" / "schema" / "AdventureWorksLT2019_schema.json"
    views_json = base_path / "assets" / "views" / "AdventureWorksLT2019_views.json"

    indexer = Indexer()
    total_indexed = 0

    # Index tables into table_schemas collection
    if schema_json.exists():
        print(f"📂 Loading tables from: {schema_json}")
        tables_count = indexer.index_json_from_file(str(schema_json))
        total_indexed += tables_count
        print(f"   ✅ Tables indexed: {tables_count}\n")
    else:
        print(f"⚠️  Schema file not found: {schema_json}\n")

    # Index views into view_schemas collection
    if views_json.exists():
        print(f"📂 Loading views from: {views_json}")
        views_count = indexer.index_views_from_file(str(views_json))
        total_indexed += views_count
        print(f"   ✅ Views indexed: {views_count}\n")
    else:
        print(f"⚠️  Views file not found: {views_json}\n")

    if total_indexed > 0:
        print(f"✅ Total indexed into vector database: {total_indexed} items")
        print("   - Collection 1: table_schemas")
        print("   - Collection 2: view_schemas")
        return 0
    else:
        print("❌ Failed to index any items")
        return 1


if __name__ == "__main__":
    sys.exit(main())
