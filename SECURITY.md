# Security policy

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository (Security tab, "Report a
vulnerability"). Please do not open a public issue for anything exploitable. You'll get an
acknowledgment within a few days; fixes ship as a patch release with credit if you want it.

## Threat model (read this before mounting skim)

skim is a local tool. It makes **no network requests** and sends no data anywhere. The two
surfaces that matter:

### `skim_run` executes shell commands — by design

`skim_run(command)` runs the command on your machine with the privileges of the server process,
exactly like an agent's built-in Bash tool. That is its job: run something verbose, keep the
output compact. The consequence is the same one every command-execution tool carries: a
prompt-injected model could ask it to run something destructive.

- Mount skim only where you would also give the agent a shell.
- Your MCP client's normal tool-permission prompts apply to `skim_run` like any other tool.
- To mount skim with the shell surface removed, set `SKIM_RUN_DISABLED=1` in the server's
  environment; `skim_run` then refuses every command with a clear error while the read-only
  tools keep working.

### `skim_patch` writes files — by design

`skim_patch(handle, anchor, new_text)` replaces one previously-expanded span of a file. It is the
same capability class as an agent's Edit tool, with three guards: it refuses when the file on disk
no longer matches the handle's snapshot (drift), it only ever writes real files it skimmed (never
`skim_run` output), and `SKIM_PATCH_DISABLED=1` removes the tool entirely. Your MCP client's
tool-permission prompts apply to it like any other tool. Run skim fully read-only by setting both
`SKIM_RUN_DISABLED=1` and `SKIM_PATCH_DISABLED=1`.

### The meter dashboard binds to localhost

`skim-meter` serves a dashboard on `127.0.0.1` (pure stdlib, no external requests). Hardening
in place:

- All data-derived strings (file paths, commands, session labels) are HTML-escaped before
  rendering, so a hostile string logged by a tool call renders as text, never as markup.
- Requests whose `Host` header is not a loopback name are rejected with 403 while the server is
  bound to loopback, which blocks DNS-rebinding pages from reading `/data`.
- Binding to a non-loopback interface requires an explicit `--host`; that choice is yours.

### The call log stays on disk

`skim_calls.jsonl` records tool calls: file paths, commands, anchor ids, and token counts —
never file contents. It exists so you can measure savings and audit the expand-loop. Treat it
like any local log: it names your files and the commands you ran. Delete it anytime, or point
`SKIM_LOG_FILE` somewhere else.

## Supported versions

| Version | Supported |
|---|---|
| latest release | yes |
| older | upgrade first, then report |

## Dependency policy

Runtime dependency surface is deliberately tiny (`mcp`; optionally `tiktoken`,
`tree-sitter` + `tree-sitter-language-pack`). CI runs a strict `pip-audit` against the locked
dependency set on every push and fails on any advisory.
