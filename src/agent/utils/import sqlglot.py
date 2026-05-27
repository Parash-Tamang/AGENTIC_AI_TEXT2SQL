import sqlglot
from sqlglot import exp

sql = """
SELECT SalesLT.Customer.FirstName, SalesLT.Customer.LastName, SalesLT.Customer.CompanyName 
FROM SalesLT.Customer 
WHERE SalesLT.Customer.CustomerID = 60
"""

parsed = sqlglot.parse_one(sql, dialect="tsql")

print(parsed)
