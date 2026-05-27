with open("permissions.json", "r") as f:
    lines = f.readlines()

# Keep only the first 460 lines (which includes the proper JSON closing at line 460)
cleaned_lines = lines[:460]

# Make sure the last line has a newline
if cleaned_lines and not cleaned_lines[-1].endswith("\n"):
    cleaned_lines[-1] += "\n"

with open("permissions.json", "w") as f:
    f.writelines(cleaned_lines)

print(f"Cleaned permissions.json: kept first {len(cleaned_lines)} lines")

# Verify it's valid JSON now
import json

with open("permissions.json", "r") as f:
    data = json.load(f)
print(f"✓ JSON is now valid")
print(f"✓ Roles available: {list(data['permissions'].keys())}")
