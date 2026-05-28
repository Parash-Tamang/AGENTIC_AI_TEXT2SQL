"""Example: Using filter_extractor + PermissionValidator for RBAC enforcement.

Demonstrates the complete workflow:
1. Extract filters from user SQL query
2. Validate access using RBAC rules from permissions.json
3. Enforce or reject based on role permissions
"""

from filter_extractor import (
    extract_filters_from_sql,
    flatten_filters,
    PermissionValidator,
    enforce_rbac,
)


def example_customer_own_profile():
    """Customer accessing own profile — should succeed with CustomerID filter."""
    print("\n" + "=" * 70)
    print("Example 1: Customer accessing own profile")
    print("=" * 70)

    sql = "SELECT CustomerID, FirstName, LastName FROM SalesLT.Customer WHERE CustomerID = 123"
    role = "customer"
    table = "SalesLT.Customer"

    # Step 1: Extract filters
    filters = extract_filters_from_sql(sql)
    print(f"\n📋 Extracted Filters:\n{filters}")

    # Step 2: Validate access
    validator = PermissionValidator()
    result = validator.validate_access(role=role, table=table, filters=filters)

    print(f"\n🔐 RBAC Validation Result:")
    print(f"  Allowed: {result['allowed']}")
    print(f"  Reason: {result['reason']}")
    print(f"  Access Level: {result['access_level']}")
    print(f"  Required Filters: {result['required_filters']}")


def example_customer_missing_filter():
    """Customer accessing all records — should FAIL (missing CustomerID filter)."""
    print("\n" + "=" * 70)
    print("Example 2: Customer accessing ALL records (missing filter)")
    print("=" * 70)

    sql = "SELECT CustomerID, FirstName FROM SalesLT.Customer"
    role = "customer"
    table = "SalesLT.Customer"

    filters = extract_filters_from_sql(sql)
    print(f"\n📋 Extracted Filters: {filters}")

    allowed, reason = enforce_rbac(role, table, filters)
    print(f"\n🚫 Access Result:")
    print(f"  Allowed: {allowed}")
    print(f"  Reason: {reason}")


def example_customer_order_with_status():
    """Customer accessing orders with status filter — should succeed."""
    print("\n" + "=" * 70)
    print("Example 3: Customer accessing orders with valid status")
    print("=" * 70)

    sql = """
    SELECT OrderDate, SubTotal
    FROM SalesLT.SalesOrderHeader
    WHERE CustomerID = 456 AND Status IN (1, 2, 3)
    """
    role = "customer"
    table = "SalesLT.SalesOrderHeader"

    filters = extract_filters_from_sql(sql)
    print(f"\n📋 Extracted Filters:\n{filters}")

    validator = PermissionValidator()
    result = validator.validate_access(role=role, table=table, filters=filters)

    print(f"\n🔐 RBAC Validation Result:")
    print(f"  Allowed: {result['allowed']}")
    print(f"  Reason: {result['reason']}")
    print(f"  Required Filters: {result['required_filters']}")


def example_customer_invalid_status():
    """Customer trying to access restricted order statuses — should FAIL."""
    print("\n" + "=" * 70)
    print("Example 4: Customer accessing INVALID status values")
    print("=" * 70)

    sql = """
    SELECT OrderDate
    FROM SalesLT.SalesOrderHeader
    WHERE CustomerID = 789 AND Status = 99
    """
    role = "customer"
    table = "SalesLT.SalesOrderHeader"

    filters = extract_filters_from_sql(sql)
    print(f"\n📋 Extracted Filters:\n{filters}")

    validator = PermissionValidator()
    result = validator.validate_access(role=role, table=table, filters=filters)

    print(f"\n❌ RBAC Validation Result:")
    print(f"  Allowed: {result['allowed']}")
    print(f"  Reason: {result['reason']}")
    if result["invalid_values"]:
        print(f"  Invalid Values: {result['invalid_values']}")


def example_sales_unrestricted():
    """Sales role accessing unrestricted table — should always succeed."""
    print("\n" + "=" * 70)
    print("Example 5: Sales role (unrestricted access)")
    print("=" * 70)

    sql = "SELECT * FROM SalesLT.SalesOrderHeader"
    role = "sales"
    table = "SalesLT.SalesOrderHeader"

    filters = extract_filters_from_sql(sql)
    print(f"\n📋 Extracted Filters: {filters}")

    validator = PermissionValidator()
    result = validator.validate_access(role=role, table=table, filters=filters)

    print(f"\n✅ RBAC Validation Result:")
    print(f"  Allowed: {result['allowed']}")
    print(f"  Reason: {result['reason']}")
    print(f"  Access Level: {result['access_level']}")


def example_flatten_filters():
    """Demonstrate flatten_filters for complex OR queries."""
    print("\n" + "=" * 70)
    print("Example 6: Flattening complex filters")
    print("=" * 70)

    # Complex filter structure with nested OR conditions
    complex_filters = {
        "CustomerID": [{"operator": "=", "value": 123}],
        "Status": [{"operator": "IN", "value": [1, 2, 3]}],
    }

    flat = flatten_filters(complex_filters)
    print(f"\n📋 Original Filters:\n{complex_filters}")
    print(f"\n📊 Flattened:\n{flat}")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("RBAC Filter Extractor Examples")
    print("=" * 70)

    try:
        example_customer_own_profile()
        example_customer_missing_filter()
        example_customer_order_with_status()
        example_customer_invalid_status()
        example_sales_unrestricted()
        example_flatten_filters()

        print("\n" + "=" * 70)
        print("✅ All examples completed!")
        print("=" * 70)

    except Exception as exc:
        print(f"\n❌ Error running examples: {exc}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
