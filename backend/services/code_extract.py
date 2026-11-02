import re

def extract_python(text: str) -> str:
    """Extract the largest fenced code block, or keep a plain-code reply."""
    blocks = re.findall(
        r"```(?:[a-zA-Z0-9_+-]+)?\s*\n?(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return max(blocks, key=len).strip() if blocks else text.strip()
