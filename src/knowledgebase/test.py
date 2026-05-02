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

from .indexer import Indexer
from .embedder import Embedder
from .vector_store import VectorStore

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
        count = indexer.index_json_from_file(str(schema_file))
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
            views_data = json.loads(Path(views_file).read_text(encoding="utf-8"))
            views_list = views_data if isinstance(views_data, list) else [views_data]
            views_count = indexer.index_json_data_views(views_list)
            logger.info(
                f"✅ Indexed {views_count} views into 'view_schemas' collection"
            )
        except Exception as e:
            logger.error(f"❌ Failed to load views: {e}")
    else:
        logger.warning(f"⚠️ Views file not found: {views_file}")


example_index_from_file()

# ── Example 2: Query the Vector Store ────────────────────────────────────


def example_query_vector_store(query_text):
    """Query tables and views by similarity."""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 2: Query Vector Store")
    logger.info("=" * 70)

    # Initialize components
    embedder = Embedder()
    store = VectorStore()

    # Example query: "Find customer information tables"
    # query_text = "customer information "
    logger.info(f"\n🔍 Searching for: '{query_text}'")

    # Embed the query
    query_embedding = embedder.embed(query_text)
    logger.info(f"📊 Query embedding generated ({len(query_embedding)} dimensions)")

    # Query schema collection
    logger.info("\n📚 Results from 'table_schemas' collection:")
    schema_results = store.query_schemas(query_embedding, top_k=3)
    for i, result in enumerate(schema_results, 1):
        logger.info(f"\n  {i}. {result['metadata'].get('table_name', 'Unknown')}")
        logger.info(f"     Distance: {result['distance']:.4f}")
        logger.info(f"     Document: {result['document'][:150]}...")

    # Query view collection
    logger.info("\n🔎 Results from 'view_schemas' collection:")
    view_results = store.query_views(query_embedding, top_k=3)
    if view_results:
        for i, result in enumerate(view_results, 1):
            logger.info(f"\n  {i}. {result['metadata'].get('view_name', 'Unknown')}")
            logger.info(f"     Distance: {result['distance']:.4f}")
    else:
        logger.info("  No views found")

    # Query all collections merged
    logger.info("\n🔄 Combined results from both collections:")
    all_results = store.query_all(query_embedding, top_k=5)
    for i, result in enumerate(all_results, 1):
        item_type = result["metadata"].get("type", "unknown")
        name = result["metadata"].get("table_name") or result["metadata"].get(
            "view_name", "Unknown"
        )
        logger.info(f"  {i}. [{item_type}] {name} (distance: {result['distance']:.4f})")


while True:
    user_input = input("\nEnter a query (or 'exit' to quit): ")
    if user_input.lower() == "exit":
        logger.info("👋 Exiting test script. Goodbye!")
        break
    example_query_vector_store(user_input)


# ── Example 3: Query with Database Filter ──────────────────────────────────


def example_query_by_database():
    """Query tables and views filtered by database name."""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 3: Query by Database Filter")
    logger.info("=" * 70)

    # Initialize components
    embedder = Embedder()
    store = VectorStore()

    # Example query: "Find address information"
    query_text = "address"
    logger.info(f"\n🔍 Searching for: '{query_text}'")
    logger.info(f"📊 Database filter: 'AdventureWorksLT2019'")

    # Embed the query
    query_embedding = embedder.embed(query_text)

    # Query schema collection with database filter
    logger.info("\n📚 Filtered Results from 'table_schemas' collection:")
    results = store._schema_col.query(
        query_embeddings=[query_embedding],
        where={"database_name": "AdventureWorksLT2019"},
        n_results=5,
        include=["documents", "metadatas", "distances"],
    )

    if results and results.get("documents"):
        for i, (doc, meta, dist) in enumerate(
            zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ),
            1,
        ):
            db = meta.get("database_name", "Unknown")
            table = meta.get("table_name", "Unknown")
            logger.info(f"\n  {i}. [{db}] {table}")
            logger.info(f"     Distance: {dist:.4f}")
            logger.info(f"     Document: {doc[:100]}...")
    else:
        logger.info("  No results found for this database")

    # Query views collection with database filter
    logger.info("\n🔎 Filtered Results from 'view_schemas' collection:")
    view_results = store._views_col.query(
        query_embeddings=[query_embedding],
        where={"database_name": "AdventureWorksLT2019"},
        n_results=5,
        include=["documents", "metadatas", "distances"],
    )

    if view_results and view_results.get("documents"):
        for i, (doc, meta, dist) in enumerate(
            zip(
                view_results["documents"][0],
                view_results["metadatas"][0],
                view_results["distances"][0],
            ),
            1,
        ):
            db = meta.get("database_name", "Unknown")
            view = meta.get("view_name", "Unknown")
            logger.info(f"\n  {i}. [{db}] {view}")
            logger.info(f"     Distance: {dist:.4f}")
    else:
        logger.info("  No views found for this database")


# ── Example 4: View Statistics ────────────────────────────────────────────


def example_statistics():
    """Display vector store statistics."""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 4: Vector Store Statistics")
    logger.info("=" * 70)

    store = VectorStore()
    stats = store.stats()

    logger.info("\n📊 Vector Store Statistics:")
    logger.info(f"  Persist Directory: {stats['persist_directory']}")
    logger.info(f"  Total Documents: {stats['total_documents']}")
    logger.info(f"\n  Schema Collection:")
    logger.info(f"    Name: {stats['schema_collection']['name']}")
    logger.info(f"    Documents: {stats['schema_collection']['document_count']}")
    logger.info(f"\n  Views Collection:")
    logger.info(f"    Name: {stats['views_collection']['name']}")
    logger.info(f"    Documents: {stats['views_collection']['document_count']}")


# ── Example 5: Custom Settings ──────────────────────────────────────────────


# ── Example 7: Clear Collections ────────────────────────────────────────────


def example_clear_collections():
    """Clear collections (useful for testing/resetting)."""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 6: Clear Collections")
    logger.info("=" * 70)

    store = VectorStore()

    logger.info("Before clearing:")
    stats = store.stats()
    logger.info(f"  Schema docs: {stats['schema_collection']['document_count']}")
    logger.info(f"  View docs: {stats['views_collection']['document_count']}")

    # Uncomment to actually clear (be careful!)
    logger.info("\n🗑️ Clearing schema collection...")
    store.clear_schemas()
    logger.info("🗑️ Clearing views collection...")
    store.clear_views()

    logger.info("\nAfter clearing:")
    stats = store.stats()
    logger.info(f"  Schema docs: {stats['schema_collection']['document_count']}")
    logger.info(f"  View docs: {stats['views_collection']['document_count']}")


# ── Main Test Runner ───────────────────────────────────────────────────────


def main():
    """Run all examples."""
    logger.info("🚀 Starting Vector Store Tests\n")

    try:
        # Run examples
        example_index_from_file()
        # example_query_vector_store()
        example_query_by_database()
        example_statistics()
        # example_custom_settings()
        example_clear_collections()

        logger.info("\n" + "=" * 70)
        logger.info("✅ All examples completed!")
        logger.info("=" * 70)

    except Exception as exc:
        logger.error(f"❌ Error during testing: {exc}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
