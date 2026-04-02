from internal.mcp.client_builder import McpClient

package_docs = McpClient(
    command="npx",
    args=[
        "-y",
        "@smithery/cli@latest",
        "run",
        "@cdugo/mcp-get-docs",
        "--config",
        "'{}'"
    ],
    tool_prefix="package-docs_",
)