#!/usr/bin/env python3
"""
Test script demonstrating how to use Indexer, Embedder, and VectorStore.

Usage:
    python test.py

This script shows:
1. Loading JSON schema files
2. Indexing tables and views into separate collections
3. Querying the vector store
4. Viewing statistics
"""

import json
import logging
from pathlib import Path

from src.knowledgebase.stores.indexer import Indexer
from src.knowledgebase.stores.embedder import Embedder
from src.knowledgebase.stores.vector_store import VectorStore
from src.knowledgebase.stores.indexer import SchemaType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ── Example 1: Basic Indexing from JSON File ────────────────────────────────


def example_index_from_file():
    """Index table schemas from a JSON file."""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 1: Index Tables from JSON File")
    logger.info("=" * 70)

    # Initialize indexer
    indexer = Indexer()

    # Path to your schema JSON
    schema_file = (
        Path(__file__).parent.parent.parent
        / "assets"
        / "schema"
        / "AdventureWorksLT2019_schema.json"
    )

    if schema_file.exists():
        logger.info(f"📂 Loading schema from: {schema_file}")
        count = indexer.index_json_from_file(
            schema_type=SchemaType.TABLE, json_path=str(schema_file)
        )
        logger.info(f"✅ Indexed {count} tables into 'table_schemas' collection")
    else:
        logger.warning(f"⚠️ Schema file not found: {schema_file}")

    # Path to views JSON
    views_file = (
        Path(__file__).parent.parent.parent
        / "assets"
        / "views"
        / "AdventureWorksLT2019_views.json"
    )

    if views_file.exists():
        logger.info(f"\n📂 Loading views from: {views_file}")
        try:
            # views_data = json.loads(Path(views_file).read_text(encoding="utf-8"))
            views_count = indexer.index_json_from_file(
                schema_type=SchemaType.VIEW, json_path=str(views_file)
            )
            logger.info(
                f"✅ Indexed {views_count} views into 'view_schemas' collection"
            )
        except Exception as e:
            logger.error(f"❌ Failed to load views: {e}")
    else:
        logger.warning(f"⚠️ Views file not found: {views_file}")


# example_index_from_file()


from src.knowledgebase.stores.retriever import retrieve_schemas, retrieve_views

store = VectorStore()
embedder = Embedder()
queries = [
    "List all tables in the SalesLT schema",
    "What are the columns in the Product table?",
]
database_name = "AdventureWorksLT2019"

results = retrieve_schemas(
    queries=queries, store=store, embedder=embedder, database_name=database_name
)

print(results)
