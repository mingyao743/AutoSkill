"""
Pi session adapter.

Converts a Pi Coding Agent session file (JSONL tree, see pi docs
`session-format.md`) into AutoSkill offline trajectory records of the shape:

    {
      "success": bool,
      "messages": [{"role": "user"|"assistant", "content": str}, ...],
      "events":   [{"event_type": ..., "text": ..., "tool": ..., "isError": ...}, ...],
    }

Design notes:
- Pi stores entries as a tree via id/parentId. The model only ever sees the
  active branch (leaf -> root). We reconstruct that branch and feed it to
  AutoSkill as ONE trajectory record.
- user turns are the primary extraction evidence; assistant/tool events become
  trajectory events. System prompt / tool-loadout messages are ignored (they
  are platform context, not reusable user experience).
- AutoSkill's own injected traffic (custom_message/custom entries whose
  customType starts with "autoskill") is filtered out to avoid recursion.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

_AUTOSKILL_PREFIX = "autoskill"

_SKIP_META_TYPES = {
    "usage",
    "model_change",
    "thinking_level_change",
    "label",
    "session_info",
    "context_edit",
}

# Feedback signal detection patterns
_FEEDBACK_PATTERNS = {
    # Correction patterns
    "correction": [
        "不对", "错了", "错误", "应该是", "改成", "改为", "修正", "纠正",
        "not right", "wrong", "should be", "change to", "fix", "correct",
        "incorrect", "mistake",
    ],
    # Revision patterns
    "revision": [
        "重新", "再", "重来", "retry", "again", "redo", "restart",
        "rewrite", "regenerate",
    ],
    # Negative feedback
    "negative": [
        "不好", "太差", "不行", "不要", "别", "避免",
        "bad", "poor", "don't", "avoid", "never", "stop",
    ],
    # Positive reinforcement
    "positive": [
        "很好", "对了", "正确", "好的", "可以", "就这样",
        "good", "correct", "right", "perfect", "yes", "like this",
    ],
}


def load_pi_session(path: str) -> Dict[str, Any]:
    """
    Reads a Pi session .jsonl file and returns the parsed header + entries.

    Returns a dict: {"header": {...}, "entries": [ {...}, ... ]}
    """

    header: Dict[str, Any] = {}
    entries: List[Dict[str, Any]] = []
    with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") == "session":
                header = obj
            else:
                entries.append(obj)
    return {"header": header, "entries": entries}


def _content_to_text(content: Any) -> str:
    """Flattens Pi content (string | block array | dict) into plain text."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
                elif "content" in item and not isinstance(item.get("content"), (list, dict)):
                    parts.append(str(item.get("content") or ""))
        return "".join(parts)
    if isinstance(content, dict):
        if content.get("type") == "text" and content.get("text"):
            return str(content.get("text") or "")
        if "text" in content:
            return str(content.get("text") or "")
        if "content" in content and not isinstance(content.get("content"), (list, dict)):
            return str(content.get("content") or "")
    return str(content)


def _extract_tool_calls(content: Any) -> List[Dict[str, Any]]:
    """Pulls assistant toolCall blocks (name/input) out of a content array."""

    out: List[Dict[str, Any]] = []
    if not isinstance(content, list):
        return out
    for item in content:
        if not isinstance(item, dict):
            continue
        t = str(item.get("type") or "").lower()
        if t in {"toolcall", "tool_call", "tooluse", "tool_use"}:
            out.append(
                {
                    "id": str(item.get("id") or item.get("toolCallId") or ""),
                    "tool": str(item.get("name") or item.get("toolName") or item.get("tool") or ""),
                    "input": item.get("input")
                    if item.get("input") is not None
                    else item.get("arguments")
                    if item.get("arguments") is not None
                    else item.get("parameters"),
                }
            )
    return out


def _is_autoskill_owned(entry: Dict[str, Any]) -> bool:
    """True if an entry is AutoSkill's own injected traffic (must not be re-extracted)."""

    ctype = str(entry.get("type") or "").lower()
    if ctype in {"custom", "custom_message"}:
        custom_type = str(entry.get("customType") or "").strip().lower()
        if custom_type.startswith(_AUTOSKILL_PREFIX):
            return True
    return False


def classify_feedback_signal(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Analyzes user messages to detect feedback signals vs new requests.

    Returns a dict with:
    - signal: "feedback" | "request" | "mixed" | "unknown"
    - types: list of detected feedback types (correction/revision/negative/positive)
    - confidence: 0.0-1.0

    Feedback signals indicate the user is correcting/revising previous output,
    which is higher-value extraction evidence than a fresh request.
    """
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        return {"signal": "unknown", "types": [], "confidence": 0.0}

    # Check the last user message primarily (most recent intent)
    last_user_text = (user_messages[-1].get("content") or "").lower()

    detected_types: List[str] = []
    for ftype, patterns in _FEEDBACK_PATTERNS.items():
        for pattern in patterns:
            if pattern in last_user_text:
                if ftype not in detected_types:
                    detected_types.append(ftype)
                break

    if not detected_types:
        # Check if there's any multi-turn context suggesting feedback
        # (e.g., short user message after long assistant response)
        if len(user_messages) >= 2 and len(last_user_text) < 50:
            prev_assistant = [
                m for m in messages
                if m.get("role") == "assistant"
            ]
            if prev_assistant and len(prev_assistant[-1].get("content", "")) > 200:
                # Short user message after long assistant response could be feedback
                return {"signal": "mixed", "types": [], "confidence": 0.3}
        return {"signal": "request", "types": [], "confidence": 0.5}

    # Determine overall signal
    has_negative = "negative" in detected_types or "correction" in detected_types
    has_positive = "positive" in detected_types
    has_revision = "revision" in detected_types

    if has_negative or has_revision:
        signal = "feedback"
        confidence = 0.8
    elif has_positive:
        signal = "feedback"
        confidence = 0.6  # Positive reinforcement is weaker signal
    else:
        signal = "mixed"
        confidence = 0.5

    return {"signal": signal, "types": detected_types, "confidence": confidence}


def resolve_active_branch(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reconstructs the leaf -> root active branch and returns it root-first.

    The "leaf" is the most recently appended entry that no other entry points
    to as its parent. Falls back to source order when parent linkage is missing.
    """

    if not entries:
        return []

    by_id: Dict[str, Dict[str, Any]] = {}
    ordered: List[Dict[str, Any]] = []
    for i, e in enumerate(entries):
        eid = str(e.get("id") or f"__idx_{i}__")
        e2 = dict(e)
        e2["__eid__"] = eid
        by_id[eid] = e2
        ordered.append(e2)

    referenced_parents = set()
    for e in ordered:
        pid = e.get("parentId")
        if pid is not None:
            referenced_parents.add(str(pid))

    leafs = [e for e in ordered if str(e.get("__eid__")) not in referenced_parents]
    leaf = leafs[-1] if leafs else ordered[-1]

    path: List[Dict[str, Any]] = []
    seen = set()
    cur: Optional[Dict[str, Any]] = leaf
    while cur is not None:
        cid = str(cur.get("__eid__"))
        if cid in seen:
            break
        seen.add(cid)
        path.append(cur)
        pid = cur.get("parentId")
        if pid is None:
            break
        cur = by_id.get(str(pid))

    path.reverse()  # root-first
    return path


def session_to_record(parsed: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Converts a parsed Pi session into one trajectory record + diagnostics.

    Returns (record, diag). record is None when there is nothing usable.
    """

    header = parsed.get("header") or {}
    entries = parsed.get("entries") or []
    branch = resolve_active_branch(entries)

    messages: List[Dict[str, str]] = []
    events: List[Dict[str, Any]] = []
    diag = {
        "session_id": str(header.get("id") or ""),
        "cwd": str(header.get("cwd") or ""),
        "branch_len": len(branch),
        "skipped_system": 0,
        "skipped_autoskill": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "terminal_is_error": False,
    }

    last_error_state: Optional[bool] = None
    for e in branch:
        etype = str(e.get("type") or "").lower()
        if etype in _SKIP_META_TYPES:
            continue
        if _is_autoskill_owned(e):
            diag["skipped_autoskill"] += 1
            continue
        if etype in {"compaction", "branch_summary"}:
            summary = _content_to_text(e.get("summary"))
            if summary:
                events.append({"event_type": etype, "text": summary})
            continue

        if etype == "message":
            msg = e.get("message") or {}
            role = str(msg.get("role") or "").strip().lower()
            content = msg.get("content")

            if role == "system":
                diag["skipped_system"] += 1
                continue
            if role == "user":
                text = _content_to_text(content).strip()
                if text:
                    messages.append({"role": "user", "content": text})
                continue
            if role == "assistant":
                text = _content_to_text(content).strip()
                if text:
                    messages.append({"role": "assistant", "content": text})
                for tc in _extract_tool_calls(content):
                    diag["tool_calls"] += 1
                    events.append(
                        {
                            "event_type": "tool_call",
                            "tool": tc.get("tool") or "",
                            "text": _content_to_text(tc.get("input")),
                        }
                    )
                continue
            if role == "toolresult":
                is_err = bool(msg.get("isError"))
                if is_err:
                    diag["tool_errors"] += 1
                last_error_state = is_err
                events.append(
                    {
                        "event_type": "tool_result",
                        "tool": str(msg.get("toolName") or msg.get("tool") or ""),
                        "isError": is_err,
                        "text": _content_to_text(content),
                    }
                )
                continue

    diag["terminal_is_error"] = bool(last_error_state)
    has_user_turn = any(m["role"] == "user" for m in messages)

    # Pi sessions carry no explicit success flag. Treat a session as successful
    # unless it terminates on an errored tool result and never recovers.
    success = has_user_turn and not diag["terminal_is_error"]

    if not has_user_turn:
        return None, diag

    # Detect feedback signal (correction/revision vs new request)
    feedback = classify_feedback_signal(messages)

    record: Dict[str, Any] = {
        "success": success,
        "messages": messages,
        "events": events,
        "feedback_signal": feedback,
    }
    return record, diag


def file_to_records(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Reads one Pi session file and returns (records, diags).

    A single file yields at most one trajectory record (its active branch).
    """

    parsed = load_pi_session(path)
    record, diag = session_to_record(parsed)
    diag["source_file"] = os.path.abspath(os.path.expanduser(path))
    if record is None:
        return [], [diag]
    return [record], [diag]
