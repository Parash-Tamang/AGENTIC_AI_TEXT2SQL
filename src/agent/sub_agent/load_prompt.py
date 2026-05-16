import os
import frontmatter


def load_prompt(file_name: str, **kwargs) -> tuple[dict, str]:
    """
    Loads a markdown prompt file, extracts metadata,
    and formats the prompt string with dynamic variables.
    """
    # Construct the path to your prompt folder
    base_dir = "C:\\Users\\paras\\Desktop\\my-agent\\src\\agent\\prompt"
    file_path = os.path.join(base_dir, base_dir, file_name)

    # Parse the markdown file
    with open(file_path, "r", encoding="utf-8") as f:
        post = frontmatter.load(f)

    # post.metadata contains the YAML config as a dictionary
    config = post.metadata
    raw_prompt = post.content

    # Inject dynamic variables if any are provided
    # formatted_prompt = raw_prompt.format(**kwargs) if kwargs else raw_prompt

    return config, raw_prompt


# --- Example Usage ---

# Simulate a dynamic user input
user_input = "A modern navbar with a dark mode toggle"

# Load the prompt and inject the variable
config, prompt_string = load_prompt("refiner.md", user_request=user_input)

# Now you have everything ready for your LLM API call
print("--- MODEL CONFIGURATION ---")
print(f"Temperature: {config.get('temperature')}\n")

print("--- FINAL PROMPT STRING ---")
print(prompt_string)
