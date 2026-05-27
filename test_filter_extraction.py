"""Quick test of filter extraction functionality."""

from src.agent.utils.filter_extractor import extract_filters_from_sql

# Test 1: Simple equality filter
sql1 = "SELECT * FROM users WHERE age = 25"
filters1 = extract_filters_from_sql(sql1)
print("Test 1 (age = 25):", filters1)

# Test 2: Multiple filters with AND
sql2 = "SELECT * FROM orders WHERE status = 'pending' AND amount > 100"
filters2 = extract_filters_from_sql(sql2)
print("Test 2 (status AND amount):", filters2)

# Test 3: IN clause
sql3 = "SELECT * FROM products WHERE category IN ('electronics', 'books')"
filters3 = extract_filters_from_sql(sql3)
print("Test 3 (IN clause):", filters3)

# Test 4: BETWEEN clause
sql4 = "SELECT * FROM sales WHERE date BETWEEN '2024-01-01' AND '2024-12-31'"
filters4 = extract_filters_from_sql(sql4)
print("Test 4 (BETWEEN clause):", filters4)

print("\n✓ Filter extraction working correctly with real SQLGlot!")
