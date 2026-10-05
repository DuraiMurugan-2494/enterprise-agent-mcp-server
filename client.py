"""
MCP Client — connects to any one of the servers in this folder
(github.py, testrail.py, postgresql.py, jira.py) and calls its operations
directly. This is the "agent uses MCP connectivity" side: no LLM
tool-selection loop required — your own code decides which operation to
call and with what arguments.
 
List what a server can do:
    python client.py --script server.py list
 
Call an operation by name with JSON arguments (server.py is the unified
gateway — it exposes every connector's operations under one endpoint).
On Windows cmd.exe, quoting inline JSON gets painful fast (see --args-file
below instead), but for simple cases:
    python client.py --script server.py call jira_get_issue "{\"issue_key\": \"PROJ-1\"}"
    python client.py --script server.py call pg_select_rows "{\"table\": \"users\", \"limit\": 5}"
    python client.py --script server.py call testrail_list_projects "{}"
    python client.py --script server.py call github_get_user "{\"username\": \"anthropics\"}"
 
Or avoid shell quoting entirely by putting the arguments in a file:
    echo {"issue_key": "PROJ-1"} > args.json
    python client.py call jira_get_issue --args-file args.json

For `pptx_read`, the client can prompt for only the input file and uses
the server defaults for the rest.

For `pptx_modify`, you can also omit the JSON and let the client prompt
you for a natural-language edit description, then it will map that into
the structured PPTX modify arguments.

For `docx_read`, the client can prompt for the input file and prints a JSON
payload that preserves the document's paragraph and table layout.

For every other operation — csv_write, csv_append_row, docx_append_paragraph,
docx_replace_text, pdf_create, pdf_append_page, xlsx_*, and anything from the
non-files connectors too — if you call it with no inline JSON and no
--args-file, and you're at an interactive terminal, the client looks up that
tool's schema from the server and prompts you for each argument (including
the file path) one at a time:
    python client.py --script files.py call csv_append_row
    python client.py --script files.py call docx_replace_text
 
Connect to a server already running independently over HTTP instead of
spawning it as a subprocess (server started with
`python <script> --serve --transport http --port <port>`):
    python client.py --http http://127.0.0.1:8000/mcp list
    python client.py --http http://127.0.0.1:8000/mcp call jira_get_issue --args-file args.json
"""
 
import argparse
import asyncio
import json
import re
import sys
import traceback
from datetime import date
from pathlib import Path
 
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
 
 
async def call_operation(session: ClientSession, name: str, arguments: dict) -> str:
    """Call one MCP tool/operation by name and return its text result."""
    if name == "docx_read" and "structured" not in arguments:
        arguments = {**arguments, "structured": True}
    result = await session.call_tool(name, arguments=arguments)
    parts = []
    for block in result.content:
        if block.type == "text":
            parts.append(block.text)
        else:
            parts.append(f"[{block.type} content]")
    text = "\n".join(parts)
    if name == "docx_read":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        return json.dumps(
            {
                "path": arguments.get("path"),
                "line_count": len(text.splitlines()) if text else 0,
                "lines": text.splitlines() if text else [],
                "text": text,
            },
            indent=2,
            ensure_ascii=False,
        )
    if name == "pdf_read_text":
        pages = text.split("\n\x0c\n") if text else []
        return json.dumps(
            {
                "path": arguments.get("path"),
                "max_pages": arguments.get("max_pages"),
                "page_count": len(pages),
                "pages": [
                    {"page": index + 1, "text": page}
                    for index, page in enumerate(pages)
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    if name == "image_analyze":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        return json.dumps(
            {
                "path": arguments.get("path"),
                "text": text,
            },
            indent=2,
            ensure_ascii=False,
        )
    return text


def _clean_quoted_text(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _strip_rename_instruction(text: str) -> str:
    rename_match = re.search(
        r"(?:[,.]\s*)?(?:and also\s+)?rename\s+(?:the\s+)?(?:update|output)\s+file[^.]*\.?",
        text,
        flags=re.IGNORECASE,
    )
    if not rename_match:
        return text
    return (text[: rename_match.start()] + text[rename_match.end() :]).strip(" ,.")


def _normalize_pptx_output_path(source_path: str, destination_path: str) -> str:
    source = Path(source_path)
    destination_text = destination_path.strip()
    if not destination_text:
        destination_dir = source.parent
        return str(destination_dir / f"{source.stem}_{date.today().isoformat()}{source.suffix or '.pptx'}")

    destination = Path(destination_text)
    if destination_text.endswith(("\\", "/")) or (destination.exists() and destination.is_dir()):
        return str(destination / f"{source.stem}_{date.today().isoformat()}{source.suffix or '.pptx'}")

    if destination.suffix:
        return str(destination)

    return str(destination.with_suffix(source.suffix or ".pptx"))


def _parse_pptx_modify_instruction(source_path: str, destination_path: str, instruction_text: str) -> dict:
    instruction_text = re.sub(r"^(?:\s*Paste the instruction text:\s*)+", "", instruction_text, flags=re.IGNORECASE)
    rename_requested = bool(re.search(r"\brename\s+(?:the\s+)?(?:update|output)\s+file\b", instruction_text, re.IGNORECASE))
    text = _strip_rename_instruction(instruction_text.strip())
    if not text:
        raise ValueError("No update instructions were provided")

    output_path = _normalize_pptx_output_path(source_path, destination_path)
    if rename_requested:
        output = Path(output_path)
        today = date.today().isoformat()
        if today not in output.stem:
            output_path = str(output.with_name(f"{output.stem}_{today}{output.suffix}"))
    arguments: dict = {
        "source_path": source_path,
        "path": output_path,
    }

    date_match = re.search(r"\b(?:enter|add|put)\s+(?:the\s+|today'?s\s+|current\s+)?date\s+(?:in|on)\s+all\s+(?:the\s+)?slides\b(?P<footer>\s+as\s+(?:a\s+)?footer)?", text, re.IGNORECASE)
    if date_match:
        arguments["date_all_slides"] = date.today().isoformat()
        if date_match.group("footer"):
            arguments["date_as_footer"] = True
        text = text[:date_match.start()] + text[date_match.end():]

    insert_match = re.search(
        r"(?:and also\s+)?add a section by the name\s+(?P<title>.+?)\s+in the new slide after slide\s+(?P<slide>\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if insert_match:
        arguments["insert_after_slide_number"] = int(insert_match.group("slide"))
        arguments["slides"] = [{"title": insert_match.group("title").strip(), "body": ""}]
        text = text[: insert_match.start()] + text[insert_match.end() :]

    normalized_clauses = re.split(r"\s*,\s*|\s+and also\s+|(?<=[.!?])\s+(?=[a-z])", text, flags=re.IGNORECASE)
    replacements = []
    for clause in normalized_clauses:
        clause = clause.strip().strip(".")
        if not clause:
            continue

        if re.fullmatch(r"create\s+(?:a\s+)?master\s+slide(?:\s+too)?", clause, flags=re.IGNORECASE):
            arguments["create_master"] = True
            continue

        scoped_edit = re.fullmatch(
            r"(?P<action>add|insert|update|edit|replace|remove|delete)\s+(?:the\s+)?"
            r"(?P<target>header|footer|master slide)\s+(?P<value>.+?)"
            r"(?:\s+(?:on|in)\s+slide\s+(?P<slide>\d+))?",
            clause,
            flags=re.IGNORECASE,
        )
        if scoped_edit:
            action = scoped_edit.group("action").lower()
            target = "master" if scoped_edit.group("target").lower() == "master slide" else scoped_edit.group("target").lower()
            edit = {"action": "add" if action in {"add", "insert"} else "delete" if action in {"remove", "delete"} else "edit", "target": target}
            if scoped_edit.group("slide"):
                edit["slide_number"] = int(scoped_edit.group("slide"))
            value = scoped_edit.group("value")
            if edit["action"] == "edit":
                old, separator, new = re.sub(r"\s+with\s+", " to ", value, flags=re.IGNORECASE).partition(" to ")
                if not separator:
                    raise ValueError(f"Update requires 'old text to new text': {clause!r}")
                edit.update(find=_clean_quoted_text(old), replace=_clean_quoted_text(new))
            elif edit["action"] == "delete":
                edit["find"] = _clean_quoted_text(value)
            else:
                edit["text"] = _clean_quoted_text(value)
            arguments.setdefault("edits", []).append(edit)
            continue

        slide_text_edit = re.fullmatch(
            r"(?P<action>add|insert|remove|delete)\s+text\s+(?P<text>.+?)\s+"
            r"(?:to|in|on|from)\s+slide\s+(?P<slide>\d+)", clause, flags=re.IGNORECASE,
        )
        if slide_text_edit:
            action = slide_text_edit.group("action").lower()
            arguments.setdefault("edits", []).append({
                "action": "add" if action in {"add", "insert"} else "delete",
                "target": "slide",
                "slide_number": int(slide_text_edit.group("slide")),
                "text" if action in {"add", "insert"} else "find": _clean_quoted_text(slide_text_edit.group("text")),
            })
            continue

        clause = re.sub(
            r"^(?:update\s+the\s+command\s+to\s+)?(?:change|update|replace)\s+(?:the\s+)?",
            "",
            clause,
            flags=re.IGNORECASE,
        )

        revenue_match = re.fullmatch(r"Revenue Impact:\s*(\$[\d,.]+[KMB]?)", clause, flags=re.IGNORECASE)
        if revenue_match:
            replacements.append({
                "find_regex": r"Revenue Impact:\s*\$[\d,.]+[KMB]?",
                "replace": f"Revenue Impact: {revenue_match.group(1)}",
            })
            continue

        add_match = re.fullmatch(
            r"(?:in\s+slide\s+(?P<slide_before>\d+)\s+add|add\s+(?:in|to)\s+slide\s+(?P<slide_after>\d+))\s+(?P<text>.+)",
            clause,
            flags=re.IGNORECASE,
        )
        if add_match:
            arguments.setdefault("add_text_to_slides", []).append({
                "slide_number": int(add_match.group("slide_before") or add_match.group("slide_after")),
                "text": _clean_quoted_text(add_match.group("text")),
            })
            continue

        match = re.search(
            r"(?P<find>.+?)\s+in\s+slide\s+(?P<slide>\d+)\s+to\s+(?P<replace>.+)$",
            clause,
            flags=re.IGNORECASE,
        )
        if not match:
            arguments.setdefault("unhandled_requests", []).append(clause)
            continue

        replacements.append(
            {
                "slide_number": int(match.group("slide")),
                "find": _clean_quoted_text(match.group("find")),
                "replace": _clean_quoted_text(match.group("replace")),
            }
        )

    if replacements:
        arguments["replacements"] = replacements

    if len(arguments) == 2 and "slides" not in arguments:
        raise ValueError(
            "Could not parse any PPTX edits. Use clauses like 'text in Slide 4 to new text' "
            "and/or 'add a section by the name Title in the new slide after slide 4'."
        )

    return arguments


async def _prompt_pptx_modify_arguments() -> dict:
    instruction_text = await asyncio.to_thread(
        input,
        "What do you want to update? Paste the instruction text: ",
    )
    source_path = _clean_quoted_text(
        await asyncio.to_thread(input, "Source PPTX path: ")
    )
    destination_path = _clean_quoted_text(
        await asyncio.to_thread(
            input,
            "Output PPTX path or folder (blank uses the source folder with today's date): ",
        )
    )
    return _parse_pptx_modify_instruction(source_path, destination_path, instruction_text)


async def _prompt_pptx_read_arguments() -> dict:
    path = _clean_quoted_text(
        await asyncio.to_thread(input, "Input PPTX file path: ")
    )
    if not path:
        raise ValueError("No input file was provided")
    return {"path": path}


async def _prompt_docx_read_arguments() -> dict:
    path = _clean_quoted_text(
        await asyncio.to_thread(input, "Input DOCX file path: ")
    )
    if not path:
        raise ValueError("No input file was provided")
    return {"path": path}


async def _prompt_arguments_from_schema(session: ClientSession, tool_name: str) -> dict:
    """
    Generic interactive fallback for any tool that doesn't have a dedicated
    natural-language prompt (like docx_read / pptx_modify above). Looks up
    the tool's schema from the server and asks for each argument one at a
    time — this is what lets file paths (and everything else) be supplied
    at runtime for csv_write, csv_append_row, docx_append_paragraph,
    docx_replace_text, pdf_create, pdf_append_page, xlsx_* and any other
    operation across every connector, without writing a one-off prompt
    function for each.
    """
    tools = await session.list_tools()
    tool = next((t for t in tools.tools if t.name == tool_name), None)
    if tool is None:
        raise ValueError(f"Unknown tool '{tool_name}' — run `list` to see available operations.")

    schema = tool.inputSchema or {}
    properties: dict = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not properties:
        return {}

    print(f"\n{tool_name} — enter each value (leave blank to skip an optional field):")
    arguments: dict = {}
    for name, prop in properties.items():
        prop_type = prop.get("type", "string")
        is_required = name in required
        label = f"  {name}{' (required)' if is_required else ' (optional)'} [{prop_type}]: "

        while True:
            raw = (await asyncio.to_thread(input, label)).strip()
            if not raw:
                if is_required:
                    print("    This field is required.")
                    continue
                break  # left out entirely — server-side default (if any) applies
            try:
                if prop_type == "integer":
                    arguments[name] = int(raw)
                elif prop_type == "number":
                    arguments[name] = float(raw)
                elif prop_type == "boolean":
                    arguments[name] = raw.lower() in ("1", "true", "yes", "y")
                elif prop_type in ("array", "object"):
                    # e.g. csv_write's `rows`, csv_append_row's `row` — enter as JSON
                    arguments[name] = json.loads(raw)
                else:
                    arguments[name] = _clean_quoted_text(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"    Couldn't parse that as {prop_type}: {exc}")
                continue
            break
    return arguments


async def run(session: ClientSession, args):
    await session.initialize()
 
    if args.command == "list":
        tools = await session.list_tools()
        print(f"{len(tools.tools)} available operations:")
        for t in tools.tools:
            print(f"  - {t.name}: {t.description}")
        return True
 
    # args.command == "call"
    if args.args_file:
        raw = Path(args.args_file).read_text(encoding="utf-8")
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Arguments must be valid JSON: {e}")
            return False
    elif args.args_json is not None:
        try:
            arguments = json.loads(args.args_json)
        except json.JSONDecodeError as e:
            print(f"Arguments must be valid JSON: {e}")
            return False
    elif args.tool_name == "docx_read" and sys.stdin.isatty():
        try:
            arguments = await _prompt_docx_read_arguments()
        except ValueError as exc:
            print(str(exc))
            return False
    elif args.tool_name == "pptx_read" and sys.stdin.isatty():
        try:
            arguments = await _prompt_pptx_read_arguments()
        except ValueError as exc:
            print(str(exc))
            return False
    elif args.tool_name == "pptx_modify" and sys.stdin.isatty():
        try:
            arguments = await _prompt_pptx_modify_arguments()
        except ValueError as exc:
            print(str(exc))
            return False
    elif sys.stdin.isatty():
        # Generic fallback for every other tool (csv_write, csv_append_row,
        # docx_append_paragraph, docx_replace_text, pdf_create, xlsx_*, and
        # anything from the non-files connectors too) — prompts field by
        # field from the tool's own schema instead of requiring raw JSON.
        try:
            arguments = await _prompt_arguments_from_schema(session, args.tool_name)
        except ValueError as exc:
            print(str(exc))
            return False
    else:
        print("call requires either an inline JSON argument or --args-file <path>")
        return False
 
    print(f"-> {args.tool_name}({arguments})")
    print(await call_operation(session, args.tool_name, arguments))
    return True
 
 
async def main():
    parser = argparse.ArgumentParser(description="Generic MCP client for this folder's servers")
    conn = parser.add_mutually_exclusive_group()
    conn.add_argument(
        "--script",
        default="server.py",
        help="server script to launch over stdio (default: server.py, the unified gateway). "
        "Or point at an individual connector: github.py / testrail.py / postgresql.py / jira.py.",
    )
    conn.add_argument(
        "--http",
        metavar="URL",
        help="connect to a standalone HTTP server instead, e.g. http://127.0.0.1:8003/mcp",
    )
 
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the server's available operations")
    call_p = sub.add_parser("call", help="call one operation")
    call_p.add_argument("tool_name", help="operation name, e.g. jira_get_issue")
    call_p.add_argument(
        "args_json",
        nargs="?",
        default=None,
        help='JSON object of arguments, e.g. "{\\"issue_key\\": \\"PROJ-1\\"}" '
        "(quoting varies by shell — see the top-of-file examples). "
        "Omit this and use --args-file instead to avoid shell quoting entirely.",
    )
    call_p.add_argument(
        "--args-file",
        metavar="PATH",
        help="read the JSON arguments from a file instead of the command line — "
        "sidesteps shell quoting issues, especially handy for long Windows paths.",
    )
 
    args = parser.parse_args()
 
    print(
        f"Connecting via {'HTTP -> ' + args.http if args.http else f'stdio (spawning {args.script})'} ...",
        flush=True,
    )
    try:
        if args.http:
            async with streamablehttp_client(args.http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    success = await run(session, args)
        else:
            server_params = StdioServerParameters(
                command=sys.executable, args=[args.script, "--serve"], env=None
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    success = await run(session, args)
    except Exception:
        print("Client failed with an exception:", flush=True)
        traceback.print_exc()
        sys.exit(1)
    if not success:
        sys.exit(1)
 
 
if __name__ == "__main__":
    asyncio.run(main())
 