def format_schema_for_prompt(bfs_result: dict) -> str:
    """
    Converts BFS result into a clean prompt block for the LLM.
    """
    lines = ["## Relevant Schema\n"]

    for table in bfs_result["schema"]:
        lines.append(f"### {table['table']}")
        for col in table["columns"]:
            desc = col.get("description", "")
            col_type = col.get("type", "")
            lines.append(f"  - {col['name']} ({col_type}): {desc}")
        lines.append("")

    if bfs_result["joins"]:
        lines.append("## Join Paths")
        for join in bfs_result["joins"]:
            lines.append(f"  - {join}")

    return "\n".join(lines)
