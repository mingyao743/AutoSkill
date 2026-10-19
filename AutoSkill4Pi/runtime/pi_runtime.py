"""
Pi runtime orchestrator.

Driven by the Pi extension (AutoSkill4Pi/extension/autoskill-pi.ts) as a
subprocess. Responsibilities:

  1. Build an AutoSkill SDK from environment config
     - LLM: reuse Pi's current model via a localhost OpenAI-compatible bridge
       (provider=generic -> AUTOSKILL_PI_LLM_BASE_URL), with fallbacks.
     - Embeddings: default local `hashing` (no external call / no key).
  2. Convert Pi session file(s) -> trajectory records (pi_session_adapter).
  3. De-dup with a processing ledger so the same session branch is not
     re-extracted on every run.
  4. Run offline trajectory extraction (add/merge/version) into the SkillBank.
  5. Mirror active skills into the Pi user-level skills directory.

CLI:
  python -m AutoSkill4Pi.runtime.pi_runtime process --session <file.jsonl>
  python -m AutoSkill4Pi.runtime.pi_runtime process-dir --dir <sessionsDir>
  python -m AutoSkill4Pi.runtime.pi_runtime mirror
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from .pi_session_adapter import file_to_records, load_pi_session, resolve_active_branch
from .pi_skill_mirror import mirror_user_skills


# --------------------------- env helpers ---------------------------


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None and v.strip() else default


def _default_home() -> str:
    return os.path.expanduser("~/.pi/autoskill")


def store_dir() -> str:
    return os.path.abspath(os.path.expanduser(_env("AUTOSKILL_PI_STORE_DIR", os.path.join(_default_home(), "SkillBank"))))


def pi_skills_dir() -> str:
    return os.path.abspath(os.path.expanduser(_env("AUTOSKILL_PI_SKILLS_DIR", os.path.join(os.path.expanduser("~"), ".pi/agent/skills"))))


def user_id() -> str:
    return _env("AUTOSKILL_PI_USER_ID", "pi").strip() or "pi"


def ledger_path() -> str:
    return os.path.abspath(os.path.expanduser(_env("AUTOSKILL_PI_LEDGER", os.path.join(_default_home(), "processed_ledger.jsonl"))))


# --------------------------- sdk build ---------------------------


def build_llm_config() -> Dict[str, Any]:
    provider = _env("AUTOSKILL_PI_LLM_PROVIDER", "generic").strip().lower() or "generic"

    if provider == "mock":
        return {"provider": "mock"}

    if provider == "generic":
        base_url = _env("AUTOSKILL_PI_LLM_BASE_URL", "").strip()
        if not base_url:
            # No bridge configured -> degrade to mock so we never crash the Pi main flow.
            return {"provider": "mock"}
        return {
            "provider": "generic",
            "model": _env("AUTOSKILL_PI_LLM_MODEL", "pi-bridge").strip() or "pi-bridge",
            "api_key": _env("AUTOSKILL_PI_LLM_API_KEY", "").strip(),
            "base_url": base_url,
            "url": base_url,
            "timeout_s": int(_env("AUTOSKILL_PI_TIMEOUT_S", "120") or 120),
        }

    # Named fallback providers reuse the offline builders.
    from autoskill.offline.provider_config import build_llm_config as _named

    return _named(provider, model=(_env("AUTOSKILL_PI_LLM_MODEL", "").strip() or None))


def build_embeddings_config(llm_provider: str) -> Dict[str, Any]:
    provider = _env("AUTOSKILL_PI_EMBEDDINGS_PROVIDER", "hashing").strip().lower() or "hashing"
    if provider in {"hashing"}:
        return {"provider": "hashing", "dims": int(_env("AUTOSKILL_PI_EMBED_DIMS", "256") or 256)}
    if provider in {"none", "off", "disabled"}:
        return {"provider": "none"}
    from autoskill.offline.provider_config import build_embeddings_config as _named

    return _named(provider, model=(_env("AUTOSKILL_PI_EMBEDDINGS_MODEL", "").strip() or None), llm_provider=llm_provider)


def build_sdk():
    from autoskill import AutoSkill, AutoSkillConfig

    llm = build_llm_config()
    emb = build_embeddings_config(str(llm.get("provider") or "mock"))
    store = {"provider": "local", "path": store_dir()}
    return AutoSkill(
        AutoSkillConfig(
            llm=llm,
            embeddings=emb,
            store=store,
            bm25_weight=float(_env("AUTOSKILL_PI_BM25_WEIGHT", "0.7") or 0.7),
        )
    )


# --------------------------- ledger ---------------------------


def _branch_fingerprint(session_path: str) -> str:
    """Stable fingerprint of the active branch (session_id + leaf entry id)."""

    parsed = load_pi_session(session_path)
    sid = str((parsed.get("header") or {}).get("id") or os.path.basename(session_path))
    branch = resolve_active_branch(parsed.get("entries") or [])
    leaf_id = str(branch[-1].get("id")) if branch else ""
    return hashlib.sha1(f"{sid}::{leaf_id}".encode("utf-8")).hexdigest()


def _load_ledger() -> set:
    path = ledger_path()
    seen = set()
    if not os.path.isfile(path):
        return seen
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            fp = str(obj.get("fingerprint") or "")
            if fp:
                seen.add(fp)
    return seen


def _append_ledger(fingerprints: List[str], *, session_paths: List[str]) -> None:
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for fp, sp in zip(fingerprints, session_paths):
            f.write(json.dumps({"fingerprint": fp, "session_file": sp}, ensure_ascii=False) + "\n")


# --------------------------- processing ---------------------------


def _collect_session_files(target_dir: str) -> List[str]:
    target_dir = os.path.abspath(os.path.expanduser(str(target_dir or "")))
    out: List[str] = []
    for root, _dirs, files in os.walk(target_dir):
        for fn in files:
            if fn.endswith(".jsonl"):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


def process_sessions(session_files: List[str], *, dry_run: bool = False) -> Dict[str, Any]:
    """
    Extract skills from the given Pi session files (deduped) and mirror.

    Returns a summary dict.
    """

    seen = _load_ledger()
    new_files: List[str] = []
    fingerprints: List[str] = []
    for sf in session_files:
        fp = _branch_fingerprint(sf)
        if fp in seen:
            continue
        new_files.append(sf)
        fingerprints.append(fp)

    if not new_files:
        return {"processed_files": 0, "skipped_files": len(session_files), "upserted": 0, "mirrored": 0, "dry_run": dry_run}

    records: List[Dict[str, Any]] = []
    diags: List[Dict[str, Any]] = []
    for sf in new_files:
        recs, ds = file_to_records(sf)
        records.extend(recs)
        diags.extend(ds)

    result = {"processed_files": len(new_files), "skipped_files": len(session_files) - len(new_files), "records": len(records), "dry_run": dry_run}

    if dry_run or not records:
        return result

    sdk = build_sdk()
    from autoskill.offline.trajectory.extract import extract_from_agentic_trajectory

    extraction = extract_from_agentic_trajectory(
        sdk=sdk,
        user_id=user_id(),
        data={"records": records},
        include_tool_events=_env("AUTOSKILL_PI_INCLUDE_TOOL_EVENTS", "1") in {"1", "true", "yes"},
        success_only=_env("AUTOSKILL_PI_SUCCESS_ONLY", "0") in {"1", "true", "yes"},
        continue_on_error=True,
        metadata={"channel": "autoskill_pi", "source": "pi_session"},
    )
    result["upserted"] = int(extraction.get("upserted_count", 0) or 0)
    result["extraction_errors"] = extraction.get("errors", [])
    result["upserted_skills"] = [str(s.get("id", "")) for s in extraction.get("skills", []) if s.get("id")]

    mirror = mirror_user_skills(sdk, user_id=user_id(), pi_skills_dir=pi_skills_dir())
    result["mirrored"] = int(mirror.get("count", 0) or 0)
    result["mirror_dir"] = mirror.get("pi_skills_dir")

    _append_ledger(fingerprints, session_paths=new_files)

    evolution_needed = _check_evolution_needed(sdk, updated_skills=result.get("upserted_skills", []))
    if evolution_needed:
        result["evolution_needed"] = evolution_needed
    return result


def _check_evolution_needed(sdk: Any, *, updated_skills: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Check which skills have accumulated enough provenance to warrant evolution.

    Returns a list of {"skill_id": ..., "skill_name": ..., "provenance_count": ...}
    for skills that meet the evolution threshold.
    """
    threshold = int(_env("AUTOSKILL_EVOLUTION_THRESHOLD", "5") or 5)
    if threshold <= 0:
        return []

    provenance_file = os.path.join(store_dir(), "index", f"online_skill_provenance_{user_id()}.json")
    if not os.path.isfile(provenance_file):
        return []

    try:
        with open(provenance_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    skills_map = data.get("skills", {})
    candidates: List[Dict[str, Any]] = []

    skill_ids_to_check = updated_skills if updated_skills else list(skills_map.keys())
    for sid in skill_ids_to_check:
        record = skills_map.get(sid)
        if not record:
            continue
        history_count = len(record.get("history", []))
        sources_count = len(record.get("sources", []))
        total = history_count + sources_count
        if total >= threshold:
            candidates.append({
                "skill_id": sid,
                "skill_name": record.get("name", sid),
                "provenance_count": total,
            })
    return candidates


# --------------------------- CLI ---------------------------


def _cmd_process(args: argparse.Namespace) -> int:
    files = [args.session] if args.session else []
    summary = process_sessions(files)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_process_dir(args: argparse.Namespace) -> int:
    target = (
        args.dir
        or _env("AUTOSKILL_PI_SESSIONS_DIR", "")
        or os.path.join(os.path.expanduser("~"), ".pi", "agent", "sessions")
    )
    files = _collect_session_files(target)
    summary = process_sessions(files)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_mirror(args: argparse.Namespace) -> int:
    sdk = build_sdk()
    mirror = mirror_user_skills(sdk, user_id=user_id(), pi_skills_dir=pi_skills_dir())
    print(json.dumps(mirror, ensure_ascii=False, indent=2))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    sdk = build_sdk()
    hits = sdk.search(
        args.query,
        user_id=user_id(),
        limit=int(_env("AUTOSKILL_PI_SEARCH_TOP_K", "5") or 5),
        scope=_env("AUTOSKILL_PI_SEARCH_SCOPE", "all"),
    )
    lines: List[str] = []
    for h in hits:
        sk = h.skill
        ver = str(getattr(sk, "version", "") or "0.1.0")
        score = float(getattr(h, "score", 0.0) or 0.0)
        lines.append("- {} (v{}, score={:.2f})\n  {}".format(sk.name, ver, score, sk.description))
    print("\n".join(lines) if lines else "(no matching skills)")
    return 0


def _cmd_evolution_check(args: argparse.Namespace) -> int:
    sdk = build_sdk()
    candidates = _check_evolution_needed(sdk)
    print(json.dumps({"evolution_candidates": candidates, "count": len(candidates)}, ensure_ascii=False, indent=2))
    return 0


def _cmd_create_skill(args: argparse.Namespace) -> int:
    """Create a new skill from agent-provided JSON payload."""
    payload = json.loads(args.payload)
    sdk = build_sdk()
    uid = user_id()

    from autoskill.management.extraction import SkillCandidate

    candidate = SkillCandidate(
        name=payload["name"],
        description=payload.get("description", ""),
        instructions=payload.get("prompt", ""),
        triggers=payload.get("triggers", []),
        tags=payload.get("tags", []),
        examples=[],
        confidence=0.8,
    )

    updated_skills = sdk.maintainer.apply([candidate], user_id=uid, metadata={
        "channel": "agent_create_skill",
    })

    skill = updated_skills[0] if updated_skills else None
    skill_id = str(getattr(skill, "id", "") or "")
    version = str(getattr(skill, "version", "") or "0.1.0")

    # Mirror to Pi skills dir
    mirror = mirror_user_skills(sdk, user_id=uid, pi_skills_dir=pi_skills_dir())

    # Darwin-skill evolution is available as a skill (autoskill/evolution/SKILL.md)
    # and can be triggered by the agent or via /autoskill_evolve command.
    # For now, creation itself is the primary action; evolution is a follow-up step.
    evolution_applied = False

    result = {
        "skill_id": skill_id,
        "name": payload["name"],
        "version": version,
        "evolution_applied": evolution_applied,
        "mirrored": int(mirror.get("count", 0) or 0),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_update_skill(args: argparse.Namespace) -> int:
    """Update an existing skill from agent-provided JSON payload."""
    payload = json.loads(args.payload)
    sdk = build_sdk()
    uid = user_id()
    skill_id = payload.get("skill_id", "")

    existing = sdk.store.get(skill_id)
    if not existing:
        print(json.dumps({"error": f"Skill not found: {skill_id}"}, ensure_ascii=False))
        return 1

    # Build updated fields
    updates = {}
    for field in ("name", "description", "prompt", "triggers", "tags"):
        if field in payload and payload[field] is not None:
            if field == "prompt":
                updates["instructions"] = payload[field]
            else:
                updates[field] = payload[field]

    if not updates:
        print(json.dumps({"error": "No fields to update"}, ensure_ascii=False))
        return 1

    # Update via maintainer (handles versioning)
    from autoskill.management.extraction import SkillCandidate

    candidate = SkillCandidate(
        name=updates.get("name", existing.name),
        description=updates.get("description", existing.description),
        instructions=updates.get("instructions", existing.instructions),
        triggers=updates.get("triggers", existing.triggers),
        tags=updates.get("tags", existing.tags),
        examples=[],
        confidence=0.8,
    )

    updated_skills = sdk.maintainer.apply([candidate], user_id=uid, metadata={
        "channel": "agent_update_skill",
        "previous_skill_id": skill_id,
    })

    # Mirror
    mirror = mirror_user_skills(sdk, user_id=uid, pi_skills_dir=pi_skills_dir())

    result_skill = updated_skills[0] if updated_skills else existing
    result = {
        "skill_id": str(getattr(result_skill, "id", "") or skill_id),
        "name": getattr(result_skill, "name", ""),
        "version": str(getattr(result_skill, "version", "") or "0.1.0"),
        "mirrored": int(mirror.get("count", 0) or 0),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_list_skills(args: argparse.Namespace) -> int:
    """List all skills for the current user."""
    sdk = build_sdk()
    uid = user_id()
    skills = sdk.list(user_id=uid)

    fmt = getattr(args, "format", "text") or "text"

    if fmt == "json":
        items = []
        for s in skills:
            items.append({
                "id": str(getattr(s, "id", "") or ""),
                "name": str(getattr(s, "name", "") or ""),
                "description": str(getattr(s, "description", "") or ""),
                "version": str(getattr(s, "version", "") or "0.1.0"),
            })
        print(json.dumps(items, ensure_ascii=False))
    else:
        if not skills:
            print("(no skills)")
        else:
            for s in skills:
                sid = str(getattr(s, "id", "") or "")
                name = str(getattr(s, "name", "") or "")
                ver = str(getattr(s, "version", "") or "0.1.0")
                desc = str(getattr(s, "description", "") or "")
                print(f"- [{sid}] {name} (v{ver}): {desc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AutoSkill4Pi runtime")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("process", help="Process one session file")
    pp.add_argument("--session", required=True)
    pp.set_defaults(func=_cmd_process)

    pd = sub.add_parser("process-dir", help="Process a sessions directory")
    pd.add_argument("--dir", default="")
    pd.set_defaults(func=_cmd_process_dir)

    pm = sub.add_parser("mirror", help="Re-mirror SkillBank to Pi skills dir")
    pm.set_defaults(func=_cmd_mirror)

    ps = sub.add_parser("search", help="Search skills for a query (for the Pi tool)")
    ps.add_argument("--query", required=True)
    ps.set_defaults(func=_cmd_search)

    pe = sub.add_parser("evolution-check", help="Check which skills need evolution")
    pe.set_defaults(func=_cmd_evolution_check)

    pc = sub.add_parser("create-skill", help="Create a new skill from JSON payload")
    pc.add_argument("--payload", required=True, help="JSON with name/description/prompt/triggers/tags")
    pc.set_defaults(func=_cmd_create_skill)

    pu = sub.add_parser("update-skill", help="Update an existing skill from JSON payload")
    pu.add_argument("--payload", required=True, help="JSON with skill_id + fields to update")
    pu.set_defaults(func=_cmd_update_skill)

    pl = sub.add_parser("list-skills", help="List all skills")
    pl.add_argument("--format", choices=["text", "json"], default="text")
    pl.set_defaults(func=_cmd_list_skills)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as e:  # never crash Pi; report and exit non-zero
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
