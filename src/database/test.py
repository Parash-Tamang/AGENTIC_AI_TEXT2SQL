import logging
from .executor import (
    build_executor,
    generate_schema,
    execute_query,
    generate_views,
    execute_view,
)
from pydantic import ValidationError
from src.database.service.schema_service import SchemaService, ExclusionConfig
from src.database.service.view_service import ViewService

# Configure logging to display in terminal
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# try:
#     # Optional: Create exclusion config to skip certain schemas/tables/columns
#     exclusions = ExclusionConfig(
#         schemas=["dbo", "test_internal"],
#         tables=["public.users", "sales.private_deals"],
#         columns=[
#             "SalesLT.Customer.PasswordHash",
#             "SalesLT.Customer.PasswordSalt",
#         ],
#     )

#     schema = generate_schema(
#         db_type="mssql",
#         server="(localdb)\\MSSQLLocalDB",
#         database="AdventureWorksLT2019",
#         username="sa",
#         password="1234567890",
#         timeout=1,
#         exclusions=exclusions,
#     )
#     print(type(schema))
#     if schema is not None:
#         print("Schema generated successfully:")
#         SchemaService.save_schema_snapshot(schema)
#     else:
#         print("Failed to generate schema.")

# except Exception as e:
#     print("Validation error:", e)

try:

    schema = execute_query(
        sql="""SELECT 
    EmailAddress,
    DIFFERENCE(EmailAddress, 'erin1@adventure-') AS match_score
FROM SalesLT.Customer
WHERE 
    DIFFERENCE(EmailAddress, 'erin1@adventure-') >= 3
    OR EmailAddress LIKE '%erin1@adventure-%'
ORDER BY match_score DESC
""",
        db_type="mssql",
        server="(localdb)\\MSSQLLocalDB",
        database="AdventureWorksLT2019",
        username="sa",
        password="1234567890",
        timeout=1,
    )
    print(schema)

except Exception as e:
    print("Validation error:", e)


# try:

#     schema = execute_view(
#         view_name="vGetAllCategories",
#         db_type="mssql",
#         server="(localdb)\\MSSQLLocalDB",
#         database="AdventureWorksLT2019",
#         username="sa",
#         password="1234567890",
#         timeout=1,
#     )
#     if schema is not None:
#         print(schema)
#     else:
#         print("Failed to generate schema.")

# except Exception as e:
#     print("Validation error:", e)
