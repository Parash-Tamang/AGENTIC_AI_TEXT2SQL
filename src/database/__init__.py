# from sqlalchemy import create_engine, text
# import urllib
# import pandas as pd

# params = urllib.parse.quote_plus(
#     "DRIVER={ODBC Driver 17 for SQL Server};"
#     "SERVER=(localdb)\\MSSQLLocalDB;"
#     "DATABASE=AdventureWorksLT2019;"
#     "UID=sa;"
#     "PWD=1234567890;"
#     "TrustServerCertificate=yes;"
# )

# engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")

# # Test
# try:
#     with engine.connect() as conn:
#         result = conn.execute(text("SELECT @@VERSION"))
#         print("✅ Connected!", result.fetchone())

# except Exception as e:
#     print(f"❌ Error: {e}")
