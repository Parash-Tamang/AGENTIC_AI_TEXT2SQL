from src.agent.llm.registry import get_llm
import json

llm = get_llm("meta-llama/llama-4-scout-17b-16e-instruct")

path = "C:\\Users\\paras\\Desktop\\my-agent\\assets\\schema\\AdventureWorksLT2019_schema.json"

from pydantic import BaseModel, Field
from typing import List


# 1. Define your exact expected output structure
class TableSelection(BaseModel):
    seed_tables: List[str] = Field(
        description="A list of table names relevant to the user query."
    )
    response_format: str = Field(
        description="The resoning on why was the tables choosen as seeds."
    )


format = TableSelection.model_json_schema()

# Load schema
with open(path, "r") as f:
    schema = json.load(f)

# Define target tables
tables = [
    "Address",
    "Customer",
    "CustomerAddress",
    "SalesOrderHeader",
    "SalesOrderDetail",
    "Product",
    "ProductCategory",
]


for i in schema:
    print(f"Table: {i['table_name']}")
    if i["table_name"] not in tables:
        tables.append(i["table_name"])


print("TABLE AND COLUMN STATISTICS")
print("=" * 60)

total_tables = len(schema)
total_columns = sum(len(t.get("columns", [])) for t in schema)
print(f"Total tables in schema: {total_tables}")
print(f"Total columns in schema: {total_columns}")
print(f"Target tables: {len(tables)}\n")

# ===== BUILD CONTEXT DICT =====
context = {}
for table_info in schema:
    if table_info["table_name"] in tables:
        table_name = table_info["table_name"]
        table_desc = table_info.get("table_description", "")
        columns = table_info.get("columns", [])

        table_context = f"Table: {table_name}\nDescription: {table_desc}\n"

        columns_info = []

        # # Add every column without any token restrictions
        # for col in columns:
        #     col_entry = f"- {col['name']}"
        #     columns_info.append(col_entry)

        # table_context += "\n".join(columns_info)

        context[table_name] = {
            "table_name": table_name,
            "table_description": table_desc,
            "stats": {
                "total_columns_available": len(columns),
                "columns_included_in_context": len(columns_info),
            },
            "columns": columns_info,
            "context": table_context,
        }

# ===== DISPLAY CONTEXT STATISTICS =====
print("CONTEXT DICTIONARY DETAILS")
print("=" * 60)
for table_name, info in context.items():
    stats = info["stats"]
    print(f"\nTable: {table_name}")
    print(f"  Description: {info['table_description']}")
    print(f"  STATS:")
    print(f"    Total Columns Available: {stats['total_columns_available']}")
    print(f"    Columns Included in Context: {stats['columns_included_in_context']}")
    print(f"  Context Preview:")
    print(f"  {'-' * 50}")
    print(f"  {info['context']}")
    print(f"  {'-' * 50}")

# ===== PREPARE LLM PROMPT =====
print("\n" + "=" * 60)
print("QUERYING LLM WITH CONTEXT")
print("=" * 60 + "\n")

table_summary = "Available Tables in Database:\n"
for table_name, info in context.items():
    table_summary += f"\n{table_name}:\n"
    table_summary += f"Description: {info['table_description']}\n"
    table_summary += "Columns:\n"

    for col_entry in info["columns"]:
        table_summary += f"  {col_entry}\n"

system_prompt = f"""You are a helpful assistant that pick the tables names based on the user query and 
the understanding the user intent. As user has no idea about the database schema, and will ask you 
questions in natural language. Your job is to identify which tables are relevant to the user query and return a JSON object with the table names.

This is the database schema and column information that you can use to understand the user query and identify relevant tables:
{table_summary}

return ONLY a JSON array of relevant table names. For example, you might return {{"seed_tables" : ["table_name1", "table_name2"]}} if those tables are relevant to the query. Do not include any other text or explanation, just the JSON array of table names.
Use the available tables and columns listed above to help answer questions """


user = "Which tables should I look at if I want to analyze customer orders and their details on what they buys?"
user_query = f"This is user raw query : {user}"

print(f"System Prompt:\n{system_prompt}\n")
print(f"User Query: {user_query}\n")

response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "table_selection",
        "schema": TableSelection.model_json_schema(),
    },
}
output = llm.generate(
    system_prompt=system_prompt,
    user_prompt=user_query,
    response_format=response_format,
    json_mode=True,
)

print(f"LLM Output:\n{output}\n")
