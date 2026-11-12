# GigBid Portfolio MCP Server

A read-only MCP server for searching fictional portfolio examples and freelancer skills. The
included profiles and evidence are synthetic; replace them with a user's reviewed portfolio before
using the server for real work. It does not submit proposals or send messages.

## Run from a checkout

From the repository root:

```powershell
python -m pip install -e .
gigbid-portfolio-mcp
```

For development, `python -m mcp_servers.portfolio.server` starts the same stdio server without
installing the console entry point.

## Install from the public GitHub repository

Configure an MCP host with the repository URL:

```json
{
  "mcpServers": {
    "gigbid-portfolio": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/FatikImran/gig-bid.git",
        "gigbid-portfolio-mcp"
      ]
    }
  }
}
```

This installs the project from the public repository into uv's temporary environment and launches
the stdio server. No PyPI release is published.

## Tools, resource, and prompt

| Name | Type | Behavior |
|---|---|---|
| `search_portfolio_evidence` | Tool | Lexically rank evidence by a requirement; supports bounded `k` and filters |
| `get_case_study_tool` | Tool | Load one evidence item by ID |
| `list_portfolio_skills` | Tool | List skills present in a synthetic profile |
| `portfolio://case/{case_id}` | Resource template | Return a full evidence item as JSON |
| `answer_screening_question` | Prompt | Draft an evidence-constrained screening answer |

All tools are read-only and use the local sample data. Ranking uses the current lexical V2
implementation; it is not neural embedding retrieval. See the parent repository's
[`docs/TOOLS.md`](../../docs/TOOLS.md) and
[`docs/DATA_CARD.md`](../../docs/DATA_CARD.md) for the full tool contract and data provenance.
