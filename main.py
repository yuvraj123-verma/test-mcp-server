from fastmcp import FastMCP
import json
import random

mcp = FastMCP("Simple Calculator", "1.0.0")


# Add to value mcp tool
@mcp.tool
def add(a: float, b: float) -> float:
    """
    Add two number together and return the result.

    Args:
        a (float): The first number to add.
        b (float): The second number to add.

    Returns:
        float: The sum of a and b.
    """
    return a + b


# Generate a random number between 1 and 100
@mcp.tool
def generate_random() -> int:
    """
    Generate a random number between 1 and 100.
    Returns:
        int: A random number between 1 and 100.
    """
    return random.randint(1, 100)


# Provide Server info
@mcp.tool
def server_info() -> str:
    """
    Provide information about the server.

    Returns:
        str: Information about the server.
    """
    info = {
        "name": "Simple Calculator MCP Server",
        "version": "1.0.0",
        "description": "A simple MCP server that provides basic calculator functions and random number generation."
    }
    return json.dumps(info, indent=4)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)


