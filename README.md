[README.md](https://github.com/user-attachments/files/33054961/README.md)
# Enterprise Agent MCP Server v2.0

A unified **Model Context Protocol (MCP) Gateway** that exposes enterprise systems, databases, document processing, filesystem operations, OCR, and collaboration platforms through a single MCP endpoint.

The server is designed to act as an independent integration layer between AI agents/frameworks and enterprise systems.

Instead of implementing separate integrations inside the AI agent framework, the framework connects to this MCP server and invokes the required tools through a common MCP interface.

---

## Architecture

```text
                    AI Agent / Agentic Framework
                              |
                              | MCP
                              v
                  +-------------------------+
                  |   MCP Gateway Server    |
                  |       server.py         |
                  +-------------------------+
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
      Enterprise           Database          Local Content
      Connectors           Connector          Connectors
          |                   |                   |
   +------+------+       +---------+       +-------------+
   | GitHub      |       |PostgreSQL|       | Files       |
   | Jira        |       +---------+        | PDF         |
   | TestRail    |                          | Word        |
   | Confluence  |                          | Excel       |
   | SharePoint  |                          | PowerPoint  |
   | OneDrive    |                          | CSV/MD/Text |
   | Teams       |                          | OCR/Image   |
   | Outlook     |                          +-------------+
   | GitHub Ent. |
   +-------------+
```

The MCP Gateway dynamically loads the available connector modules and merges their tools into a single MCP server.

---

# Key Features

- Unified MCP gateway for multiple enterprise systems
- 12 connector modules
- 153 MCP operations
- HTTP Streamable MCP transport
- STDIO transport
- Asynchronous/non-blocking architecture
- Parallel client request handling
- PostgreSQL database integration
- GitHub and GitHub Enterprise integration
- Jira and Confluence integration
- TestRail integration
- Microsoft 365 integrations
- Local document and filesystem operations
- OCR and image analysis
- PDF, Word, Excel, CSV, Markdown and PowerPoint support
- Connector-level failure isolation
- Environment-based configuration
- Optional Base64-prefixed configuration values
- Standalone connector support
- Unified client for testing and invoking MCP tools

---

# Connector Overview

| Connector | Module | Operations | Purpose |
|---|---|---:|---|
| GitHub | `github.py` | 12 | GitHub repositories, files and issues |
| GitHub Enterprise | `github_enterprise.py` | 11 | Self-hosted GitHub Enterprise |
| TestRail | `testrail.py` | 21 | Projects, test cases, runs and milestones |
| PostgreSQL | `postgresql.py` | 9 | Database access and SQL execution |
| Jira | `jira.py` | 13 | Issues, comments and projects |
| Confluence | `confluence.py` | 11 | Spaces, pages and comments |
| SharePoint | `sharepoint.py` | 13 | Sites, lists, items and files |
| OneDrive | `onedrive.py` | 9 | Files, folders and search |
| Microsoft Teams | `teams.py` | 11 | Teams, channels, chats and messages |
| Outlook | `outlook.py` | 14 | Email, folders and calendar |
| Image Analysis | `image.py` | 1 | OCR and image intent analysis |
| Local Files | `files.py` | 28 | Documents and filesystem operations |
| **Total** | | **153** | |

---

# Project Structure

```text
enterprise-agent-mcp-server/
│
├── server.py
├── client.py
├── env_config.py
│
├── github.py
├── github_enterprise.py
├── jira.py
├── confluence.py
├── testrail.py
├── postgresql.py
│
├── sharepoint.py
├── onedrive.py
├── teams.py
├── outlook.py
│
├── image.py
├── files.py
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

# How the MCP Gateway Works

The main entry point is:

```text
server.py
```

The gateway maintains a list of connector modules and loads their MCP tools into one server.

At startup, `server.py`:

1. Imports each connector.
2. Loads its MCP tools.
3. Merges the tools into the gateway.
4. Skips connectors that cannot be loaded.
5. Reports loaded and skipped connectors.
6. Exposes all successfully loaded tools through one MCP endpoint.

This allows the AI agent/framework to communicate with multiple enterprise systems through a single MCP server.

---

# Connector Isolation

A failure in one connector does not bring down the complete gateway.

For example:

```text
GitHub       -> Loaded
PostgreSQL   -> Loaded
Jira         -> Loaded
TestRail     -> Loaded
SharePoint   -> Skipped
```

If SharePoint credentials or dependencies are missing, the other connectors can continue to operate.

The server reports the skipped connector and the reason during startup.

---

# Installation

## 1. Clone the repository

For a clean installation:

```bash
git clone https://github.com/DuraiMurugan-2494/enterprise-agent-mcp-server.git
cd enterprise-agent-mcp-server
```

For the v2 development branch:

```bash
git checkout mcp-server-v2
```

---

## 2. Create a virtual environment

### Windows

```powershell
python -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\Activate.ps1
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

The current implementation uses the MCP 1.x API. The MCP dependency is intentionally constrained to the 1.x series because the connector implementation uses the `FastMCP` API.

---

# Configuration

Create a local `.env` file.

```text
.env
```

Do not commit this file to GitHub.

The repository contains:

```text
.env.example
```

as the configuration template.

Credentials can be supplied either as normal values or using the `base64:` prefix.

Example:

```env
JIRA_BASE_URL=https://company.atlassian.net
```

or:

```env
JIRA_BASE_URL=base64:aHR0cHM6Ly9jb21wYW55LmF0bGFzc2lhbi5uZXQ=
```

### Important

Base64 is **encoding, not encryption**.

Never commit production credentials, API keys, database passwords, client secrets, or access tokens to Git.

---

# PostgreSQL / Neon Configuration

The PostgreSQL connector supports PostgreSQL-compatible databases such as Neon PostgreSQL.

Typical configuration:

```env
PG_HOST=<database-host>
PG_PORT=5432
PG_DATABASE=<database-name>
PG_USER=<database-user>
PG_PASSWORD=<database-password>
```

The connector provides:

```text
pg_list_tables
pg_describe_table
pg_create_table
pg_drop_table
pg_select_rows
pg_insert_row
pg_update_rows
pg_delete_rows
pg_execute_query
```

This allows an AI agent to retrieve and manipulate structured enterprise data through MCP.

---

# Running the Server

## Standalone Smoke Test

Run:

```bash
python server.py
```

This performs startup validation and displays:

- Loaded connectors
- Skipped connectors
- Number of merged MCP operations
- Available MCP tool names

---

# Run Using STDIO

```bash
python server.py --serve
```

STDIO mode is useful when an MCP client launches the server as a subprocess.

---

# Run Using HTTP

For enterprise agent framework integration:

```bash
python server.py --serve --transport http --port 8000
```

The MCP endpoint becomes:

```text
http://127.0.0.1:8000/mcp
```

The server runs independently and accepts requests from external MCP clients.

---

# Custom Host and Port

Default host:

```text
127.0.0.1
```

Default HTTP port:

```text
8000
```

You can change them:

```bash
python server.py --serve --transport http --host 0.0.0.0 --port 8000
```

For local development, prefer binding to `127.0.0.1`.

---

# MCP Client

`client.py` provides a command-line MCP client for testing the gateway.

## List Available Tools

```bash
python client.py --http http://127.0.0.1:8000/mcp list
```

## Invoke an MCP Tool

Example:

```bash
python client.py --http http://127.0.0.1:8000/mcp call pg_list_tables "{\"schema\":\"public\"}"
```

Example PostgreSQL query:

```bash
python client.py --http http://127.0.0.1:8000/mcp call pg_execute_query "{\"query\":\"SELECT * FROM fleet_devices\"}"
```

---

# PostgreSQL Operations

The PostgreSQL connector supports:

```text
pg_list_tables
pg_describe_table
pg_create_table
pg_drop_table
pg_select_rows
pg_insert_row
pg_update_rows
pg_delete_rows
pg_execute_query
```

Example:

```sql
SELECT *
FROM fleet_devices
WHERE maintenance_status = 'Due';
```

For values supplied dynamically by an application, prefer parameterized queries.

---

# Local File and Document Processing

The `files.py` connector provides local content and filesystem operations.

Supported formats include:

```text
PDF
Microsoft Word
Microsoft Excel
CSV
Markdown
Plain Text
PowerPoint
Local folders
Windows filesystem
```

Examples include:

```text
fs_list_dir
fs_get_info
fs_create_dir
fs_move
fs_copy
fs_delete
```

---

# PDF

Supported operations include:

```text
pdf_read_text
pdf_get_info
pdf_create
pdf_append_page
```

---

# Word

Supported operations include:

```text
docx_read
docx_create
docx_append_paragraph
docx_replace_text
```

---

# Excel

Supported operations include:

```text
xlsx_read
xlsx_create
xlsx_update_cell
xlsx_append_row
```

---

# CSV

Supported operations include:

```text
csv_read
csv_write
csv_append_row
csv_to_xlsx
```

---

# PowerPoint

Supported operations include:

```text
pptx_read
pptx_create
pptx_modify
pptx_add_slide
```

The PowerPoint functionality supports reading, creating and modifying presentations.

---

# Image Analysis and OCR

The `image.py` connector provides:

```text
image_analyze
```

It can analyze local images and perform OCR when the required OCR dependencies are installed.

The implementation uses OCR/runtime dependencies such as RapidOCR and ONNX Runtime.

---

# Enterprise Connectors

## GitHub

The GitHub connector supports repository, file and issue operations.

Examples:

```text
github_get_user
github_list_repos
github_get_file
github_create_repo
github_update_repo
github_delete_repo
github_create_issue
github_update_issue
github_delete_issue
github_create_or_update_file
github_delete_file
http_request
```

---

## GitHub Enterprise

For self-hosted GitHub Enterprise environments, the server provides corresponding repository, file and issue operations.

---

## Jira

The Jira connector supports:

- Issue retrieval
- Issue search
- Issue creation
- Issue updates
- Issue deletion
- Comments
- Projects

Examples:

```text
jira_get_issue
jira_search_issues
jira_create_issue
jira_update_issue
jira_delete_issue
jira_get_comments
jira_add_comment
jira_update_comment
jira_delete_comment
jira_list_projects
jira_get_project
jira_create_project
jira_delete_project
```

---

## Confluence

The Confluence connector supports:

- Spaces
- Pages
- Page search
- Comments

Examples:

```text
confluence_list_spaces
confluence_get_space
confluence_list_pages
confluence_get_page
confluence_create_page
confluence_update_page
confluence_delete_page
confluence_search_pages
confluence_list_comments
confluence_add_comment
confluence_delete_comment
```

---

## TestRail

TestRail operations cover:

- Projects
- Test cases
- Test runs
- Milestones

---

# Microsoft 365 Connectors

The gateway includes connectors for:

```text
SharePoint
OneDrive
Microsoft Teams
Outlook
```

These connectors use Microsoft/Azure authentication configuration.

---

# SharePoint

Supports:

- Sites
- Subsites
- Lists
- List items
- Files

---

# OneDrive

Supports:

- File browsing
- Folder browsing
- File reading
- Folder creation
- Upload
- Move
- Copy
- Delete
- Search

---

# Microsoft Teams

Supports:

- Teams
- Channels
- Channel messages
- Chats

---

# Outlook

Supports:

- Email
- Mail search
- Drafts
- Folders
- Calendar events

---

# Enterprise Agent Framework Integration

The MCP server operates independently from the AI agent framework.

Recommended architecture:

```text
+-----------------------------------+
|       Enterprise AI Framework     |
|                                   |
|  Agents                           |
|  Workflows                        |
|  RAG                              |
|  Guardrails                       |
|  Orchestration                    |
+----------------+------------------+
                 |
                 | MCP / HTTP
                 v
+-----------------------------------+
|        Enterprise MCP Server      |
|                                   |
|        server.py                  |
+-----------------------------------+
                 |
       +---------+---------+
       |         |         |
       v         v         v
    Jira      Neon DB   GitHub
       |
       +---- Microsoft 365
       |
       +---- Local Documents
```

The AI framework does not need to contain the implementation details of each enterprise integration.

Instead:

```text
Agent
  |
  | Selects required tool
  v
MCP Client
  |
  | MCP request
  v
MCP Gateway
  |
  | Routes tool
  v
Connector
  |
  v
Enterprise System
```

This provides a clean separation between:

- Agent orchestration
- AI reasoning
- Guardrails
- MCP integration
- Enterprise systems

---

# Example: Fleet Management Use Case

For an HP printer fleet maintenance workflow, the agent can retrieve printer information from PostgreSQL through MCP.

```text
Fleet Management Agent
          |
          v
      MCP Client
          |
          v
     MCP Gateway
          |
          v
   PostgreSQL Connector
          |
          v
     Neon PostgreSQL
          |
          v
     fleet_devices
```

Example query:

```sql
SELECT *
FROM fleet_devices
WHERE maintenance_status = 'Due';
```

The MCP server retrieves the data and returns it to the agent framework.

The framework can then combine the retrieved information with:

- Agent logic
- RAG
- Guardrails
- Workflow orchestration
- Recommendation logic

---

# Development

To add a new connector:

1. Create a new connector module.
2. Create a `FastMCP` instance.
3. Implement operations using `@mcp.tool()`.
4. Keep network/database operations asynchronous where appropriate.
5. Add the module to the connector list in `server.py`.
6. Start the gateway.
7. Verify the connector appears in the startup output.
8. Verify its tools using `client.py`.

Example:

```python
@mcp.tool()
async def example_operation(...):
    ...
```

---

# Testing

Start with the smoke test:

```bash
python server.py
```

Then start HTTP mode:

```bash
python server.py --serve --transport http --port 8000
```

Check available operations:

```bash
python client.py --http http://127.0.0.1:8000/mcp list
```

Invoke an individual operation:

```bash
python client.py --http http://127.0.0.1:8000/mcp call <tool_name> <arguments>
```

---

# Security Considerations

Never commit:

```text
.env
API tokens
API keys
database passwords
Azure client secrets
GitHub tokens
Jira tokens
TestRail API keys
```

Some operations are destructive, for example:

```text
pg_drop_table
github_delete_repo
fs_delete
jira_delete_*
sharepoint_delete_*
onedrive_delete_*
```

Use appropriate authorization and application-level guardrails before exposing destructive operations to autonomous AI agents.

---

# Dependency Security

Before production deployment, periodically review dependencies:

```bash
pip-audit -r requirements.txt
```

Dependency versions should be reviewed and updated as new security advisories are published.

---

# Current Version

```text
Enterprise Agent MCP Server
Version: 2.0
Architecture: Unified MCP Gateway
Connectors: 12
MCP Operations: 153
Primary Transport: Streamable HTTP
Additional Transport: STDIO
```

---

# Repository

GitHub repository:

https://github.com/DuraiMurugan-2494/enterprise-agent-mcp-server

Recommended v2 branch:

```text
mcp-server-v2
```

---

# Quick Start

```powershell
# Create environment
python -m venv .venv

# Activate
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure credentials
# Create .env

# Verify connectors
python server.py

# Start MCP server
python server.py --serve --transport http --port 8000

# In another terminal, list tools
python client.py --http http://127.0.0.1:8000/mcp list
```

The MCP server is then available at:

```text
http://127.0.0.1:8000/mcp
```

and can be consumed by an MCP-compatible AI agent framework.
