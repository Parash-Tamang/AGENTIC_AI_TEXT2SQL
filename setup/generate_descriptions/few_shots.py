FEW_SHOTS_1 = """
INPUT:
{
  "table": "Customer",
  "columns": {
    "CustomerID": { "type": "int", "constraint": "Primary Key", "relation": null },
    "FirstName": { "type": "nvarchar", "constraint": "not null", "relation": null }
  }
}

OUTPUT:
{
  "table_name": "Customer",
  "table_description": "Stores customer identity information.",
  "columns": [
    {
      "name": "CustomerID",
      "type": "int",
      "constraint": "Primary Key",
      "relation": null,
      "description": "Unique identifier for each customer."
    },
    {
      "name": "FirstName",
      "type": "nvarchar",
      "constraint": "not null",
      "relation": null,
      "description": "Customer's first name."
    }
  ]
}
"""

FEW_SHOTS_2 = """
INPUT:
{
  "table": "Order",
  "columns": {
    "OrderID": { "type": "int", "constraint": "Primary Key", "relation": null },
    "CustomerID": {
      "type": "int",
      "constraint": "Foreign Key",
      "relation": "Customer.CustomerID"
    }
  }
}

OUTPUT:
{
  "table_name": "Order",
  "table_description": "Represents customer purchase transactions.",
  "columns": [
    {
      "name": "OrderID",
      "type": "int",
      "constraint": "Primary Key",
      "relation": null,
      "description": "Unique identifier for each order."
    },
    {
      "name": "CustomerID",
      "type": "int",
      "constraint": "Foreign Key",
      "relation": "Customer.CustomerID",
      "description": "References the customer who placed the order."
    }
  ]
}
"""


FEW_SHOTS_3 = """
INPUT:
{
  "table": "log",
  "columns": {
    "id": {
      "type": "INT",
      "constraint": "Primary Key",
      "relation": null,
      "sample_values": [1, 2, 3]
    },
    "action": {
      "type": "TEXT",
      "constraint": "nullable",
      "relation": null,
      "sample_values": ["LOGIN", "LOGOUT", "UPDATE_PROFILE"]
    }
  }
}

OUTPUT:
{
  "table_name": "log",
  "table_description": "Stores system activity records.",
  "columns": [
    {
      "name": "id",
      "type": "INT",
      "constraint": "Primary Key",
      "relation": null,
      "description": "Unique identifier for each log record."
    },
    {
      "name": "action",
      "type": "TEXT",
      "constraint": "nullable",
      "relation": null,
      "description": "Type of action performed in the system."
    }
  ]
}
"""
