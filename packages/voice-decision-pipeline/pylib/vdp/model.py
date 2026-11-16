"""Model calls for the voice build (PLAN §2.3, §3.4, §3.7).

Every call goes through `claude -p` on the logged-in Claude Code account;
no API key is used (PLAN §6). One call per batch, the batch's
result written straight to the state by the caller, so each item is sent
once per pass. Nothing else in the pipeline sends anything, and no subagent
or Workflow ever carries corpus text.

Each call turns off what a session would add: tools, settings files, MCP
servers, slash commands and session files (`--tools ""`, `--setting-sources
""`, `--strict-mcp-config`, `--disable-slash-commands`,
`--no-session-persistence`), and gives its own short system prompt. That
leaves about 1,100 tokens of Claude Code's own overhead per call (against
a full session's context). The answer comes back as
structured output against the caller's JSON schema (`--json-schema`), and
is checked against the same schema here before it is used.

A usage limit stops the pass cleanly: UsageLimit is raised, the caller has
already saved every finished batch, and the next run resumes after them.
A refusal or a cut-off answer is retried, then given up as CallFailed.

VDP_CLAUDE names another executable to call in place of `claude` (the
tests' stand-in).
"""

import json
import os
import subprocess
import time

MODELS = {
    # PLAN §3.4, §3.7
    "labeller": "claude-sonnet-5-5",
    "second": "claude-opus-5-5",
    "drafter": "claude-opus-5-5",
    "judge": "claude-fable-5-2",
    # The guide is written by the drafting model: the one
    # the owner's sessions draft with, so its rules are read by the model that
    # wrote them.
    "guide": "claude-opus-5-5",
}

RETRIES = 3
TIMEOUT = 900
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "limit will reset",
               "out of extra usage", "credit balance")


class UsageLimit(Exception):
    pass


class CallFailed(Exception):
    pass


def executable():
    return os.environ.get("VDP_CLAUDE") or "claude"


def _check(schema, v, where="answer"):
    """A small JSON-schema check: type, required, properties, items, enum,
    additionalProperties false, minimum/maximum. Enough for the schemas the
    pipeline writes; anything else in a schema is not checked."""
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "number": (int, float), "boolean": bool}
    if t and not isinstance(v, types[t]) or (t in ("integer", "number") and isinstance(v, bool)):
        raise ValueError(f"{where}: expected {t}")
    if "enum" in schema and v not in schema["enum"]:
        raise ValueError(f"{where}: {v!r} not one of {schema['enum']}")
    if t in ("integer", "number"):
        if "minimum" in schema and v < schema["minimum"]:
            raise ValueError(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and v > schema["maximum"]:
            raise ValueError(f"{where}: above {schema['maximum']}")
    if t == "object":
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in v:
                raise ValueError(f"{where}: no {k}")
        if schema.get("additionalProperties") is False:
            extra = set(v) - set(props)
            if extra:
                raise ValueError(f"{where}: unexpected {sorted(extra)}")
        for k, s in props.items():
            if k in v:
                _check(s, v[k], f"{where}.{k}")
    if t == "array":
        for i, x in enumerate(v):
            _check(schema.get("items", {}), x, f"{where}[{i}]")
        if "minItems" in schema and len(v) < schema["minItems"]:
            raise ValueError(f"{where}: fewer than {schema['minItems']} items")
    return v


def call(role, system, prompt, schema, log=print):
    """The structured answer of one `claude -p` call by the model for role."""
    model = MODELS[role]
    cmd = [executable(), "-p", "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(schema), "--no-session-persistence",
           "--tools", "", "--setting-sources", "", "--strict-mcp-config",
           "--disable-slash-commands", "--system-prompt", system]
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               timeout=TIMEOUT, cwd=os.environ.get("TMPDIR") or "/tmp")
        except subprocess.TimeoutExpired:
            last = f"no answer in {TIMEOUT}s"
            continue
        out = (p.stdout or "").strip()
        try:
            d = json.loads(out)
        except ValueError:
            d = {"is_error": True, "result": (out or p.stderr or "")[-400:]}
        msg = str(d.get("result") or p.stderr or "")
        if any(w in msg.lower() for w in LIMIT_WORDS):
            raise UsageLimit(msg.strip()[:300])
        if not d.get("is_error") and d.get("structured_output") is not None:
            try:
                return _check(schema, d["structured_output"])
            except ValueError as e:
                last = f"answer didn't match the schema: {e}"
        else:
            last = (d.get("terminal_reason") or "error") + ": " + msg.strip()[:300]
        log(f"  retry {role} call {attempt}/{RETRIES}: {last}")
        time.sleep(min(30, 2 ** attempt))
    raise CallFailed(f"{role} call failed {RETRIES} times: {last}")
