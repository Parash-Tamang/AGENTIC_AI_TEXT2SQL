from openai import OpenAI

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    ",  # your key
)
user_query = "hi"
response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "system", "content": "You are a SQL generator..."},
        {"role": "user", "content": user_query},
    ],
    temperature=0.1,
    max_tokens=500,
)

sql = response.choices[0].message.content

print(sql)
