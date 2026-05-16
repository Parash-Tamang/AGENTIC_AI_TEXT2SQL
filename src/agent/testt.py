import json
import os
import tiktoken
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("api_key")
client = Groq(api_key=api_key)

# ---------------------------------------------------------------------------
# 1. REAL AdventureWorksLT2019 SCHEMA
# ---------------------------------------------------------------------------
SCHEMA = """
Tables:

  SalesLT.Customer (
      CustomerID, NameStyle, Title, FirstName, MiddleName, LastName, Suffix,
      CompanyName, SalesPerson, EmailAddress, Phone,
      PasswordHash  
      PasswordSalt  
      rowguid, ModifiedDate
  )

  SalesLT.SalesOrderHeader (
      SalesOrderID, RevisionNumber, OrderDate, DueDate, ShipDate,
      Status,           -- tinyint: 1=In process, 2=Approved, 3=Backordered,
                        --          4=Rejected,   5=Shipped,  6=Cancelled
      SalesOrderNumber, PurchaseOrderNumber, AccountNumber,
      CustomerID, TerritoryID, BillToAddressID, ShipToAddressID,
      ShipMethod, SubTotal, TaxAmt, Freight, TotalDue, Comment,
      rowguid, ModifiedDate
  )

  SalesLT.SalesOrderDetail (
      SalesOrderID, SalesOrderDetailID, OrderQty, ProductID,
      UnitPrice, UnitPriceDiscount,
      LineTotal,  -- computed: UnitPrice * (1 - UnitPriceDiscount) * OrderQty
      rowguid, ModifiedDate
  )

  SalesLT.Product (
      ProductID, Name, ProductNumber, Color, StandardCost, ListPrice,
      Size, Weight, ProductCategoryID, ProductModelID,
      SellStartDate, SellEndDate, DiscontinuedDate,
      rowguid, ModifiedDate
  )

  SalesLT.ProductCategory (
      ProductCategoryID, ParentProductCategoryID, Name,
      rowguid, ModifiedDate
  )

  SalesLT.Address (
      AddressID, AddressLine1, AddressLine2,
      City, StateProvince, PostalCode, CountryRegion,
      rowguid, ModifiedDate
  )

  SalesLT.CustomerAddress (
      CustomerID, AddressID, AddressType,
      rowguid, ModifiedDate
  )
"""

# ---------------------------------------------------------------------------
# 2. PERMISSION DICT
# ---------------------------------------------------------------------------
#
#  Column rules:
#    {"filter": "id",   "values": None}  -> WHERE col = <runtime value>   [REQUIRED]
#    {"filter": "enum", "values": [...]} -> WHERE col IN (...)             [REQUIRED]
#    column absent from dict             -> freely selectable, no filter
#
#  Table rules:
#    table with column dict  -> accessible; only listed columns have required filters
#    table as {}             -> fully accessible, all columns, no filters at all
#    table absent            -> fully DENIED
#
PERMISSIONS = {
    "john_doe": {
        "SalesLT.Customer": {
            "CustomerID": {"filter": "id", "values": None},
            #"SalesPerson": {"filter": "id", "values": None},
        },
        "SalesLT.SalesOrderHeader": {
            "CustomerID": {"filter": "id", "values": None},
            "TerritoryID": {"filter": "id", "values": None},
            "Status": {"filter": "enum", "values": ["1", "2", "3"]},
        },
        "SalesLT.SalesOrderDetail": {
            "SalesOrderID": {"filter": "id", "values": None},
        },
        "SalesLT.Product": {
            "ProductCategoryID": {"filter": "id", "values": None},
        },
        "SalesLT.ProductCategory": {},  # full table, no filters
    },
    "admin": {
        "SalesLT.Customer": {},
        "SalesLT.SalesOrderHeader": {},
        "SalesLT.SalesOrderDetail": {},
        "SalesLT.Product": {},
        "SalesLT.ProductCategory": {},
        "SalesLT.Address": {},
        "SalesLT.CustomerAddress": {},
    },
}

# ---------------------------------------------------------------------------
# 3. RUNTIME ID VALUES  (populated from login/session at startup)
# ---------------------------------------------------------------------------
RUNTIME_VALUES = {
    "john_doe": {
        "SalesLT.Customer": {
            "CustomerID": "29531",
            "SalesPerson": "adventure-works\\linda3",
        },
        "SalesLT.SalesOrderHeader": {"CustomerID": "29531", "TerritoryID": "4"},
        "SalesLT.SalesOrderDetail": {"SalesOrderID": None},
        "SalesLT.Product": {"ProductCategoryID": "18"},
    }
}


# ---------------------------------------------------------------------------
# 4. BUILD PERMISSION BLOCK FOR SYSTEM PROMPT
# ---------------------------------------------------------------------------
def build_permission_block(user: str) -> str:
    perms = PERMISSIONS.get(user, {})
    rvals = RUNTIME_VALUES.get(user, {})
    lines = [f"Active user: {user}", ""]
    lines.append("ACCESS RULES (strictly enforced — never deviate):")

    for table, columns in perms.items():
        lines.append(f"\n  Table: {table}")

        if not columns:
            lines.append(
                "    • Full access — all columns selectable, no filters required."
            )
            continue

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

        lines.append(
            f"    → All other columns in {table} are selectable with no filter."
        )

    all_tables = [
        "SalesLT.Customer",
        "SalesLT.SalesOrderHeader",
        "SalesLT.SalesOrderDetail",
        "SalesLT.Product",
        "SalesLT.ProductCategory",
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
        "2. Never expose keys like id in sql.",
        "3. Denied tables cannot appear anywhere in the query.",
        "4. Combine all required filters with AND.",
        "5. If the request cannot be fulfilled within these rules, return error JSON.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. AGENT
# ---------------------------------------------------------------------------
def sql_agent(user: str, user_query: str) -> dict:
    permission_block = build_permission_block(user)

    system_prompt = f"""You are a SQL expert for the AdventureWorks LT 2019 database (SQL Server / T-SQL syntax).

SCHEMA:
{SCHEMA}

PERMISSIONS:
{permission_block}

Return ONLY valid JSON. No markdown, no text outside the JSON object.
"""

    encoding = tiktoken.get_encoding("o200k_base")
    token_count = len(encoding.encode(system_prompt + user_query))
    print(f"[tokens] {token_count}")

    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "sql_output",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "generated_sql": {
                        "type": "string",
                        "description": "Complete T-SQL query, or empty string if denied.",
                    },
                    "error": {
                        "type": "string",
                        "description": "Permission violation message, or empty string if no error.",
                    },
                    "filters_applied": {
                        "type": "string",
                        "description": "Comma-separated filters injected from permissions.",
                    },
                },
                "required": ["generated_sql", "error", "filters_applied"],
                "additionalProperties": False,
            },
        },
    }

    chunks = []
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ],
        response_format=response_schema,
        temperature=1,
        top_p=1,
        reasoning_effort="medium",
        stream=True,
        stop=None,
    )

    print("[streaming]")
    for chunk in completion:
        piece = chunk.choices[0].delta.content or ""
        print(piece, end="", flush=True)
        chunks.append(piece)

    print("\n")
    raw = "".join(chunks)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 6. RUN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    USER = "john_doe"

    queries = [
        "Show me the top 5 customers by total sales amount.",
        "Show all status for my orders.",
        "Show me the PasswordHash for customer 29531.",
        "Show all data from SalesLT.Address.",
        "List all product categories.",
    ]

    for q in queries:
        print("=" * 60)
        print(f"QUERY : {q}")
        print("=" * 60)
        result = sql_agent(USER, q)
        if result.get("error"):
            print(f"  ERROR   : {result['error']}")
        else:
            print(f"  FILTERS : {result['filters_applied']}")
            print(f"  SQL     :\n{result['generated_sql']}")
        print()
