import tiktoken
from groq import Groq
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get GROQ_API_KEY from environment
api_key = os.getenv("api_key")
client = Groq(api_key=api_key)
user_input = (
    "Write a SQL query to find the top 5 customers by total sales in the last month."
)


# Load the specific encoding for the gpt-oss models
encoding = tiktoken.get_encoding("o200k_base")

# Or, if using the very latest library version that supports it explicitly:
encoding = tiktoken.encoding_for_model("gpt-oss-20b")

text = "The cat sat on a mat"
tokens = encoding.encode(text)

print(f"Token Count: {len(tokens)}")
print(f"Token IDs: {tokens}")
completion = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[
        {
            "role": "system",
            "content": "You are a SQL expert. Return only the SQL query.",
        },
        {"role": "user", "content": user_input},
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "sql_output",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "generated_sql": {
                        "type": "string",
                        "description": "The complete, executable SQL query.",
                    }
                },
                "required": ["generated_sql"],
                "additionalProperties": False,
            },
        },
    },
    temperature=1,
    # max_completion_tokens=8192,
    top_p=1,
    reasoning_effort="medium",
    stream=True,
    stop=None,
)

for chunk in completion:
    print(chunk.choices[0].delta.content or "", end="")
