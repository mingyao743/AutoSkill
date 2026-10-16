"""
Interactive chat application.

This module owns the orchestration logic:
- generate assistant response (optional LLM)
- optionally extract/maintain skills (AutoSkill ingest)
"""

from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..client import AutoSkill
from ..llm.base import LLM
from .commands import Command, parse_command
from .config import InteractiveConfig
from .io import ConsoleIO, IO


@dataclass
class _PendingExtraction:
    # Snapshot of the latest assistant turn waiting for user feedback.
    latest_user: str
    latest_assistant: str
    messages: List[Dict[str, Any]]

@dataclass
class _BgExtractJob:
    # One asynchronous extraction task. `epoch` guards against stale jobs after /clear.
    window: List[Dict[str, Any]]
    trigger: str
    hint: Optional[str]
    epoch: int


class InteractiveChatApp:
    def __init__(
        self,
        *,
        sdk: AutoSkill,
        config: InteractiveConfig,
        io: Optional[IO] = None,
        chat_llm: Optional[LLM] = None,
    ) -> None:
        """Creates a console chat app that orchestrates response + async extraction."""

        self.sdk = sdk
        self.config = config.normalize()
        self.io: IO = io or ConsoleIO()
        self.chat_llm = chat_llm

        self.messages: List[Dict[str, Any]] = []
        self._pending: Optional[_PendingExtraction] = None
        self._turns_at_last_extract_check: int = 0
        self._epoch: int = 0
        self._bg_extract_sema = threading.BoundedSemaphore(1)
        self._bg_lock = threading.Lock()
        # FIFO queue for extraction jobs that arrive while a worker is running.
        self._queued_extract: List[_BgExtractJob] = []
        self._events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.session_id = str(uuid.uuid4())

    def run(self) -> None:
        """Starts the blocking REPL loop."""

        self._print_banner()
        self._print_help()
        while True:
            self._drain_background_events()
            try:
                line = self.io.input("\nYou> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.io.print("\nBye.")
                return

            if not line:
                continue

            cmd = parse_command(line)
            if cmd is not None:
                should_exit = self._handle_command(cmd)
                if should_exit:
                    return
                continue

            self._handle_user_message(line)

    def _print_banner(self) -> None:
        """Prints startup diagnostics."""

        online = "online" if self.chat_llm is not None else "offline"
        self.io.print("AutoSkill interactive chat")
        self.io.print("Store dir:", self.config.store_dir)
        self.io.print("User id:", self.config.user_id)
        self.io.print("Extraction mode:", self.config.extract_mode)
        self.io.print("Extraction interval (turns):", self.config.extract_turn_limit)
        self.io.print("Mode:", online)
        self.io.print("Existing skills:", len(self.sdk.list(user_id=self.config.user_id)))

    def _print_help(self) -> None:
        """Prints command list and extraction behavior notes."""

        self.io.print(
            "\nCommands:\n"
            "  /help\n"
            "  /exit\n"
            "  /skills\n"
            "  /export <skill_id>\n"
            "  /write <dir>\n"
            "  /extract auto|always|never\n"
            "  /extract_every <n>\n"
            "  /extract_now [hint]  (alias: extract_now [hint])\n"
            "  /paste               (multi-line input; end with /end)\n"
            "  /file <path>         (send file content as a message)\n"
            "  /clip                (send clipboard content as a message)\n"
            "  /scope user|common|all\n"
            "  /clear\n"
            "\nNotes:\n"
            "  - In /extract auto mode, extraction is attempted once every N turns (N=extract_turn_limit).\n"
            "    Set N=1 to attempt extraction every turn.\n"
            "  - /extract_now [hint] schedules extraction in background (non-blocking).\n"
        )

    def _handle_command(self, cmd: Command) -> bool:
        """Handles slash commands; returns True only when the app should exit."""

        name = cmd.name
        arg = cmd.arg

        if name in {"/exit", "/quit"}:
            self.io.print("Bye.")
            return True

        if name == "/help":
            self._print_help()
            return False

        if name == "/clear":
            self.messages = []
            self._pending = None
            self._turns_at_last_extract_check = 0
            self._epoch += 1
            self._events = queue.Queue()
            with self._bg_lock:
                self._queued_extract = []
            self.io.print("Conversation cleared.")
            return False

        if name == "/paste":
            text = self._read_multiline_message()
            if text is None:
                return False
            if not text.strip():
                self.io.print("(empty)")
                return False
            self._handle_user_message(text)
            return False

        if name == "/file":
            if not arg:
                self.io.print("Usage: /file <path>")
                return False
            text = self._read_file_message(arg)
            if text is None:
                return False
            if not text.strip():
                self.io.print("(empty)")
                return False
            self._handle_user_message(text)
            return False

        if name == "/clip":
            text = self._read_clipboard_message()
            if text is None:
                return False
            if not text.strip():
                self.io.print("(empty)")
                return False
            self._handle_user_message(text)
            return False

        if name == "/extract":
            mode = (arg or "").strip().lower()
            if mode in {"auto", "always", "never"}:
                self.config.extract_mode = mode
                self.io.print("Extraction mode:", self.config.extract_mode)
            else:
                self.io.print("Usage: /extract auto|always|never")
            return False

        if name == "/extract_every":
            raw = (arg or "").strip()
            try:
                n = int(raw)
            except Exception:
                self.io.print("Usage: /extract_every <n>")
                return False
            n = max(1, n)
            self.config.extract_turn_limit = n
            self.io.print("Extraction interval (turns):", self.config.extract_turn_limit)
            return False

        if name == "/extract_now":
            window = None
            if self._pending is not None and self._pending.messages:
                window = list(self._pending.messages)
            elif self.messages:
                window = list(self.messages[-self.config.ingest_window :])

            if not window:
                self.io.print("(no conversation context to extract from)")
                return False

            hint = (arg or "").strip() or None
            self._pending = None
            self._start_background_extraction(window, trigger="extract_now", hint=hint)
            self.io.print("\n[extract_now] scheduled in background")
            if hint:
                self.io.print("[extract_now] hint:", hint)
            return False

        if name == "/scope":
            self.io.print("Skill scope is no longer configurable.")
            return False

        if name == "/skills":
            skills = self.sdk.list(user_id=self.config.user_id)
            if not skills:
                self.io.print("(no skills)")
                return False
            for s in skills[:200]:
                self.io.print(f"- {s.id} | v{s.version} | {s.name}")
            return False

        if name == "/export":
            if not arg:
                self.io.print("Usage: /export <skill_id>")
                return False
            md = self.sdk.export_skill_md(arg)
            if not md:
                self.io.print("(not found)")
                return False
            self.io.print(md)
            return False

        if name == "/write":
            if not arg:
                self.io.print("Usage: /write <dir>")
                return False
            out_dirs = self.sdk.write_skill_dirs(user_id=self.config.user_id, root_dir=arg)
            self.io.print("Wrote:", len(out_dirs), "skill directories")
            return False

        self.io.print("Unknown command. Use /help.")
        return False

    def _read_multiline_message(self) -> Optional[str]:
        """
        Reads a multi-line user message from the console.

        Termination:
        - end: /end
        - cancel: /cancel (or Ctrl-C)
        """

        self.io.print("\n[paste] Enter multi-line input. End with a single line: /end (cancel: /cancel)")
        lines: List[str] = []
        while True:
            try:
                line = self.io.input("... ").rstrip("\n")
            except (EOFError, KeyboardInterrupt):
                self.io.print("\n[paste] canceled")
                return None

            marker = line.strip()
            if marker in {"/end", "／end"}:
                break
            if marker in {"/cancel", "／cancel"}:
                self.io.print("[paste] canceled")
                return None
            lines.append(line)
        return "\n".join(lines)

    def _read_file_message(self, raw_path: str) -> Optional[str]:
        """Loads file content as message text, with size cap and UTF-8 replacement decode."""

        import os

        path = str(raw_path or "").strip()
        if (path.startswith('"') and path.endswith('"')) or (path.startswith("'") and path.endswith("'")):
            path = path[1:-1].strip()
        if not path:
            self.io.print("Usage: /file <path>")
            return None

        abs_path = os.path.abspath(os.path.expanduser(os.path.expandvars(path)))
        if not os.path.isfile(abs_path):
            self.io.print("[file] not found:", abs_path)
            return None

        max_bytes = 2_000_000
        try:
            with open(abs_path, "rb") as f:
                data = f.read(max_bytes + 1)
        except Exception as e:
            self.io.print("[file] failed:", str(e))
            return None

        truncated = len(data) > max_bytes
        text = data[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text = text.rstrip() + "\n\n...[truncated]...\n"
        self.io.print(
            f"[file] loaded: {abs_path} ({len(data[:max_bytes])} bytes{' truncated' if truncated else ''})"
        )
        return text

    def _read_clipboard_message(self) -> Optional[str]:
        """Loads clipboard text using platform-specific commands."""

        import subprocess

        def _try(cmd: list[str]) -> Optional[bytes]:
            """Run try."""
            try:
                return subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            except Exception:
                return None

        data = _try(["pbpaste"])
        if data is None:
            data = _try(["wl-paste", "--no-newline"])
        if data is None:
            data = _try(["xclip", "-o", "-selection", "clipboard"])
        if data is None:
            data = _try(["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"])
        if data is None:
            data = _try(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"])

        if data is None:
            self.io.print("[clip] clipboard read not supported here (try /file <path>)")
            return None

        max_bytes = 2_000_000
        truncated = len(data) > max_bytes
        text = data[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text = text.rstrip() + "\n\n...[truncated]...\n"
        self.io.print(f"[clip] loaded ({len(data[:max_bytes])} bytes{' truncated' if truncated else ''})")
        return text

    def _handle_user_message(self, text: str) -> None:
        """
        Main console turn pipeline.

        Stages:
        1) drain background extraction result
        2) schedule extraction (parallel with chat generation)
        3) stream assistant response
        4) stage latest window for next-turn feedback
        """

        latest_user = text.strip()

        # Drain any completed extraction results from background jobs.
        self._drain_background_events()

        # Treat the current user message as feedback for the previous turn, but run extraction
        # asynchronously so chat latency is not impacted.
        extract_window = self._pop_pending_extraction_window(user_feedback=latest_user)

        self.messages.append({"role": "user", "content": latest_user})

        # Build extraction window and schedule if needed.
        early_window = (
            list(extract_window)
            if extract_window is not None
            else list(self.messages[-self.config.ingest_window :])
        )
        has_assistant_in_window = any(
            str(m.get("role") or "").strip().lower() == "assistant" for m in (early_window or [])
        )
        if self._should_trigger_auto_extraction() and has_assistant_in_window and early_window:
            total_turns_abs = sum(
                1
                for m in (self.messages or [])
                if str(m.get("role") or "").strip().lower() == "assistant"
            )
            self._turns_at_last_extract_check = int(total_turns_abs)
            self._start_background_extraction(
                early_window,
                trigger="auto",
            )

        # Generate assistant response.
        self.io.print("\nAssistant> ", end="")
        assistant_parts: List[str] = []
        for chunk in self._generate_assistant_response_stream():
            s = str(chunk or "")
            if not s:
                continue
            assistant_parts.append(s)
            self.io.print(s, end="", flush=True)
        latest_assistant = "".join(assistant_parts).strip() or "(empty response)"
        self.io.print("")
        self.messages.append({"role": "assistant", "content": latest_assistant})

        # Stage the latest window for potential extraction on the next turn, when we may have
        # explicit user feedback about whether this response helped.
        window = self.messages[-self.config.ingest_window :]
        self._pending = _PendingExtraction(
            latest_user=latest_user,
            latest_assistant=latest_assistant,
            messages=list(window),
        )

    def _build_assistant_inputs(self) -> Tuple[str, str]:
        """Assembles prompts for chat generation."""

        system = "You are a helpful assistant.\n"
        history = self._format_history(max_turns=self.config.history_turns)
        user = f"Conversation:\n{history}\n\nRespond to the latest user message."
        return system, user

    def _generate_assistant_response(self) -> str:
        """Blocking response generation with defensive error formatting."""

        if self.chat_llm is None:
            return "Offline mode: no chat LLM configured."

        system, user = self._build_assistant_inputs()
        try:
            out = self.chat_llm.complete(
                system=system,
                user=user,
                temperature=float(self.config.assistant_temperature),
            )
        except Exception as e:
            msg = str(e)
            msg = msg.replace("\n", " ").strip()
            msg = (msg[:500] + "...") if len(msg) > 500 else msg
            return f"(LLM error: {msg})"
        return (out or "").strip() or "(empty response)"

    def _generate_assistant_response_stream(
        self,
    ) -> Iterator[str]:
        """Streaming response generation that yields chunks as they arrive."""

        if self.chat_llm is None:
            yield "Offline mode: no chat LLM configured."
            return

        system, user = self._build_assistant_inputs()
        try:
            for chunk in self.chat_llm.stream_complete(
                system=system,
                user=user,
                temperature=float(self.config.assistant_temperature),
            ):
                s = str(chunk or "")
                if s:
                    yield s
        except Exception as e:
            msg = str(e)
            msg = msg.replace("\n", " ").strip()
            msg = (msg[:500] + "...") if len(msg) > 500 else msg
            yield f"(LLM error: {msg})"

    def _format_history(self, *, max_turns: int) -> str:
        """Formats recent turns into plain text conversation history."""

        if not self.messages:
            return ""
        max_msgs = max(0, int(max_turns)) * 2
        window = self.messages[-max_msgs:] if max_msgs else self.messages
        lines: List[str] = []
        for m in window:
            role = str(m.get("role") or "").strip().lower()
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
            else:
                lines.append(f"{role.title()}: {content}")
        return "\n".join(lines).strip()

    def _pop_pending_extraction_window(self, *, user_feedback: str) -> Optional[List[Dict[str, Any]]]:
        """
        Converts pending turn snapshot into an extraction window.

        The current user message is appended as feedback so extractor/maintainer can decide whether
        the previous response should become or update a reusable skill.
        """

        pending = self._pending
        if pending is None:
            return None

        self._pending = None
        feedback = str(user_feedback or "").strip()
        window = list(pending.messages or [])
        if feedback:
            window.append({"role": "user", "content": feedback})
        return window

    def _should_trigger_auto_extraction(self) -> bool:
        """
        Returns whether this turn should schedule extraction in auto mode.

        Policy:
        - never: disabled
        - always: every turn
        - auto: once every `extract_turn_limit` assistant turns
        """

        mode = (self.config.extract_mode or "auto").lower()
        if mode == "never":
            return False
        if mode == "always":
            return True
        total_turns_abs = sum(
            1
            for m in (self.messages or [])
            if str(m.get("role") or "").strip().lower() == "assistant"
        )
        interval = max(1, int(getattr(self.config, "extract_turn_limit", 1) or 1))
        turns_since_check = max(0, int(total_turns_abs) - int(self._turns_at_last_extract_check or 0))
        return turns_since_check >= interval

    def _start_background_extraction(
        self,
        window: List[Dict[str, Any]],
        *,
        trigger: str,
        hint: Optional[str] = None,
    ) -> None:
        """
        Schedules asynchronous extraction work.

        Concurrency strategy:
        - at most one running extraction worker
        - while busy, enqueue jobs and process them in FIFO order
        """

        if not window:
            return
        job = _BgExtractJob(
            window=list(window),
            trigger=str(trigger or "auto"),
            hint=(str(hint).strip() if hint and str(hint).strip() else None),
            epoch=int(self._epoch),
        )

        with self._bg_lock:
            if self._bg_extract_sema.acquire(blocking=False):
                thread = threading.Thread(
                    target=self._background_extraction_worker,
                    args=(job,),
                    daemon=True,
                )
                thread.start()
                return
            # A background extraction is already running: queue this job for FIFO processing.
            self._queued_extract.append(job)

    def _background_extraction_worker(self, job: _BgExtractJob) -> None:
        """
        Worker loop for extraction tasks.

        Processes the current job and then queued jobs in FIFO order; stale epochs are
        discarded so `/clear` can safely reset session state.
        """

        try:
            current = job
            while True:
                epoch = int(getattr(current, "epoch", 0) or 0)
                if epoch != int(self._epoch):
                    break

                try:
                    updated = self.sdk.ingest(
                        user_id=self.config.user_id,
                        messages=list(current.window or []),
                        metadata={
                            "channel": "chat",
                            "trigger": str(current.trigger),
                            "session_id": str(self.session_id),
                        },
                        hint=current.hint,
                    )
                    if epoch == int(self._epoch):
                        self._events.put(
                            {"trigger": str(current.trigger), "updated": list(updated or []), "error": ""}
                        )
                except Exception as e:
                    if epoch == int(self._epoch):
                        self._events.put(
                            {"trigger": str(current.trigger), "updated": [], "error": str(e)}
                        )

                with self._bg_lock:
                    next_job = self._queued_extract.pop(0) if self._queued_extract else None
                if next_job is None:
                    break
                current = next_job
        finally:
            try:
                self._bg_extract_sema.release()
            except Exception:
                pass
            self._maybe_restart_queued_extraction_worker()

    def _maybe_restart_queued_extraction_worker(self) -> None:
        """
        Best-effort restart path for queued extraction jobs.

        Keeps FIFO queue progress when a worker exits before draining the queue.
        """

        restart_job: Optional[_BgExtractJob] = None
        with self._bg_lock:
            if self._queued_extract and self._bg_extract_sema.acquire(blocking=False):
                restart_job = self._queued_extract.pop(0)
        if restart_job is not None:
            threading.Thread(
                target=self._background_extraction_worker,
                args=(restart_job,),
                daemon=True,
            ).start()

    def _drain_background_events(self) -> None:
        """
        Prints completed background extraction results, if any.

        Note: Console input is blocking, so events that complete while the user is typing will be
        printed before the next prompt.
        """

        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                break

            trigger = str(ev.get("trigger") or "auto")
            err = str(ev.get("error") or "").strip()
            if err:
                self.io.print(f"\n[extract:{trigger}] failed:", err)
                continue

            updated = ev.get("updated") or []
            if not updated:
                self.io.print(f"\n[extract:{trigger}] attempted: no skills extracted")
                continue

            self.io.print(f"\n[extract:{trigger}] upserted:", len(updated))
            for s in updated[:20]:
                sid = getattr(s, "id", "")
                name = getattr(s, "name", "")
                ver = getattr(s, "version", "")
                self.io.print(f"- {sid} | v{ver} | {name}")
            # Keep auto mode lightweight for UX: only print full SKILL.md previews for explicit extract_now.
            if trigger == "extract_now":
                for s in updated[:3]:
                    sid = getattr(s, "id", "")
                    if sid:
                        self._print_skill_md(str(sid), label=f"extract:{trigger}")

    def _print_skill_md(self, skill_id: str, *, label: str) -> None:
        """Prints a capped SKILL.md preview for explicit extraction actions."""

        md = self.sdk.export_skill_md(str(skill_id))
        if not md:
            return
        md_s = str(md).strip()
        if not md_s:
            return
        max_chars = 8000
        if len(md_s) > max_chars:
            md_s = md_s[:max_chars].rstrip() + "\n\n...(truncated; use /export <skill_id> to view full SKILL.md)"
        self.io.print(f"\n[{label}] SKILL.md for {skill_id}:\n{md_s}")
