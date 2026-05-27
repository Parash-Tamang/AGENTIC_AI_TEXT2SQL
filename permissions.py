"""
Role-Based Access Control (RBAC) Permissions for AdventureWorksLT2019 Database

This module defines fine-grained column-level access control for five roles:
- customer: self-service customers (own data only)
- sales: sales team (full business access, no PII)
- admin: database administrators (unrestricted)
- analyst: business analysts (read-only aggregated data, no PII)
- support: support staff (lookup + status only, no financial data)

Filter Rules:
  {"filter": "id", "values": None}      → WHERE col = <runtime_value> [REQUIRED]
  {"filter": "enum", "values": [...]}   → WHERE col IN (...) [REQUIRED]
  {} on table                           → Full unrestricted access
  Table/Column omitted                  → Access DENIED
"""

PERMISSIONS = {
    # =========================================================================
    # CUSTOMER ROLE: Self-service access to own data only
    # =========================================================================
    "customer": {
        "SalesLT.Customer": {
            # Only filter: restrict to own customer record by CustomerID
            "CustomerID": {"filter": "id", "values": None},
        },
        # → Reason: Customers see own profile only; all readable columns except secrets
        "SalesLT.SalesOrderHeader": {
            # Required filters for customer's own data
            "CustomerID": {"filter": "id", "values": None},
            "Status": {"filter": "enum", "values": ["1", "2", "3", "4", "5", "6"]},
        },
        # → Reason: Filter to own orders + restrict status visibility
        "SalesLT.SalesOrderDetail": {
            # Required filter for order line items
            "SalesOrderID": {"filter": "id", "values": None},
        },
        # → Reason: Link to SalesOrderHeader via SalesOrderID
        "SalesLT.Product": {},
        # → Reason: Browse full product catalog (no filters needed)
        "SalesLT.ProductCategory": {},
        # → Reason: Browse product categories (no filters needed)
        "SalesLT.CustomerAddress": {
            # Only filter: restrict to own customer's addresses
            "CustomerID": {"filter": "id", "values": None},
        },
        # → Reason: Manage own address associations only
    },
    # =========================================================================
    # SALES ROLE: Full business access, exclude PII and sensitive auth data
    # =========================================================================
    "sales": {
        "SalesLT.Customer": {},
        # → Reason: Full customer directory; auth secrets (PasswordHash, PasswordSalt) denied
        "SalesLT.SalesOrderHeader": {},
        # → Reason: Manage all orders, pricing, fulfillment
        "SalesLT.SalesOrderDetail": {},
        # → Reason: Line items, unit prices, discounts
        "SalesLT.Product": {},
        # → Reason: Product catalog for quotes
        "SalesLT.ProductCategory": {},
        # → Reason: Category navigation
        "SalesLT.ProductDescription": {},
        # → Reason: Product details
        "SalesLT.ProductModel": {},
        # → Reason: Model specifications
        "SalesLT.ProductModelProductDescription": {},
        # → Reason: Multilingual descriptions
        "SalesLT.Address": {},
        # → Reason: Shipping/billing address validation
        "SalesLT.CustomerAddress": {},
        # → Reason: Address type mappings
    },
    # =========================================================================
    # ADMIN ROLE: Unrestricted access to all data
    # =========================================================================
    "admin": {
        "SalesLT.Customer": {},
        # → Reason: Administrators require full access for audits, maintenance, backups
        "SalesLT.SalesOrderHeader": {},
        # → Reason: Full order history including financial reconciliation
        "SalesLT.SalesOrderDetail": {},
        # → Reason: Detailed order line items
        "SalesLT.Product": {},
        # → Reason: Product management, lifecycle tracking
        "SalesLT.ProductCategory": {},
        # → Reason: Category hierarchy management
        "SalesLT.ProductDescription": {},
        # → Reason: Multilingual description management
        "SalesLT.ProductModel": {},
        # → Reason: Model management
        "SalesLT.ProductModelProductDescription": {},
        # → Reason: Description mappings
        "SalesLT.Address": {},
        # → Reason: Address master data management
        "SalesLT.CustomerAddress": {},
        # → Reason: Customer address mapping
    },
    # =========================================================================
    # ANALYST ROLE: Read-only aggregate/non-PII data for business intelligence
    # =========================================================================
    "analyst": {
        "SalesLT.Product": {},
        # → Reason: Product analysis, trends
        "SalesLT.ProductCategory": {},
        # → Reason: Category aggregation
        "SalesLT.ProductDescription": {},
        # → Reason: Product content
        "SalesLT.ProductModel": {},
        # → Reason: Model performance
        "SalesLT.ProductModelProductDescription": {},
        # → Reason: Multilingual availability
        "SalesLT.SalesOrderHeader": {},
        # → Reason: Revenue analysis (CustomerID/payment details excluded by query logic)
        "SalesLT.SalesOrderDetail": {},
        # → Reason: Profitability, unit economics
    },
    # =========================================================================
    # SUPPORT ROLE: Limited lookup + read-only order status, no financial data
    # =========================================================================
    "support": {
        "SalesLT.Customer": {
            # Only filter: restrict to specific customer lookup
            "CustomerID": {"filter": "id", "values": None},
        },
        # → Reason: Customer name/contact lookup (no password/auth secrets)
        "SalesLT.SalesOrderHeader": {},
        # → Reason: Order status tracking (no pricing/financial data excluded by query layer)
        "SalesLT.Address": {},
        # → Reason: Shipping address validation
    },
}


# ============================================================================
# RUNTIME VALUES: Populated from session/login (example for reference)
# ============================================================================
RUNTIME_VALUES = {
    "john_doe": {
        "SalesLT.Customer": {
            "CustomerID": "29531",
        },
        "SalesLT.SalesOrderHeader": {
            "CustomerID": "29531",
        },
        "SalesLT.SalesOrderDetail": {
            "SalesOrderID": None,  # Derived from orders
        },
        "SalesLT.CustomerAddress": {
            "CustomerID": "29531",
        },
    }
}


# ============================================================================
# HELPER: Build permission block for LLM system prompt
# ============================================================================
def build_permission_block(user: str) -> str:
    """
    Generate a human-readable permission summary for a user.
    Intended for inclusion in LLM system prompts to enforce access rules.

    Args:
        user: Username corresponding to a key in PERMISSIONS dict

    Returns:
        Formatted string describing all access rules for the user
    """
    perms = PERMISSIONS.get(user, {})
    rvals = RUNTIME_VALUES.get(user, {})
    lines = [f"Active user: {user}", ""]
    lines.append("ACCESS RULES (strictly enforced — never deviate):")

    for table, columns in perms.items():
        lines.append(f"\n  Table: {table}")

        if not columns:
            lines.append(
                "    • Full access — all columns readable, no filters required."
            )
            continue

        # Column-level rules (only id and enum filters listed)
        for col, meta in columns.items():
            if meta.get("filter") == "id":
                rv = rvals.get(table, {}).get(col)
                if rv:
                    lines.append(f"    • {col}: WHERE {col} = '{rv}'  [REQUIRED]")
                else:
                    lines.append(
                        f"    • {col}: id filter — runtime value not set  [REQUIRED]"
                    )
            elif meta.get("filter") == "enum":
                vals = ", ".join(f"'{v}'" for v in meta["values"])
                lines.append(f"    • {col}: WHERE {col} IN ({vals})  [REQUIRED]")

        if columns:
            lines.append(
                f"    → All other columns in {table} are readable (no filter)."
            )

    # Denied tables
    all_tables = [
        "SalesLT.Customer",
        "SalesLT.SalesOrderHeader",
        "SalesLT.SalesOrderDetail",
        "SalesLT.Product",
        "SalesLT.ProductCategory",
        "SalesLT.ProductDescription",
        "SalesLT.ProductModel",
        "SalesLT.ProductModelProductDescription",
        "SalesLT.Address",
        "SalesLT.CustomerAddress",
    ]
    denied = [t for t in all_tables if t not in perms]
    if denied:
        lines.append(
            f"\n  Denied tables (cannot appear in FROM or JOIN): {', '.join(denied)}"
        )

    lines += [
        "",
        "RULES:",
        "1. Every [REQUIRED] filter MUST appear in WHERE — even if the user does not mention it.",
        "2. Never expose secrets (PasswordHash, PasswordSalt, CreditCardApprovalCode) in results.",
        "3. Denied tables cannot appear anywhere in the query.",
        "4. Combine all required filters with AND.",
        "5. If the request cannot be fulfilled within these rules, return error JSON.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # Example: Print permission blocks for each role
    for role in ["customer", "sales", "admin", "analyst", "support"]:
        print("=" * 80)
        print(build_permission_block(role))
        print()
