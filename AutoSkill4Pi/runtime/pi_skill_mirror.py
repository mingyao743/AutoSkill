"""
Pi skill mirror.

Mirrors AutoSkill's SkillBank (source of truth) into the Pi user-level skills
directory so Pi's native progressive skill loader can discover and use them.

Key safety rules (mirroring AutoSkill4OpenClaw's `openclaw_mirror` mode):
- The mirror directory is a *projection*, never the source of truth.
- Only directories carrying a `.autoskill-managed.json` marker are owned and
  overwritten by AutoSkill. Foreign same-name skills are never clobbered:
  AutoSkill falls back to a `<slug>-autoskill` directory instead.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

MANAGED_MARKER = ".autoskill-managed.json"


def _read_marker(dir_path: str) -> Optional[Dict[str, Any]]:
    marker = os.path.join(dir_path, MANAGED_MARKER)
    if not os.path.isfile(marker):
        return None
    try:
        with open(marker, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_marker(dir_path: str, *, skill_id: str, name: str, version: str, user_id: str) -> None:
    payload = {
        "managedBy": "autoskill",
        "skill_id": skill_id,
        "name": name,
        "version": version,
        "user_id": user_id,
    }
    with open(os.path.join(dir_path, MANAGED_MARKER), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def mirror_user_skills(
    sdk,
    *,
    user_id: str,
    pi_skills_dir: str,
) -> Dict[str, Any]:
    """
    Writes every active skill of `user_id` into `pi_skills_dir` as Agent Skill
    directories, then marks ownership so future runs can update in place.

    Uses the SDK's `write_skill_dir`/store listing to obtain the artifact files,
    then adds the management marker.
    """

    pi_skills_dir = os.path.abspath(os.path.expanduser(pi_skills_dir))
    os.makedirs(pi_skills_dir, exist_ok=True)

    skills = sdk.list(user_id=user_id)  # active user-owned skills
    written: List[Dict[str, str]] = []

    # Map existing managed dirs to their skill ids so re-mirroring updates the
    # same directory in place instead of spawning `<slug>-autoskill-2` clones.
    managed_by_dir: Dict[str, str] = {}
    for existing in sorted(os.listdir(pi_skills_dir)):
        full = os.path.join(pi_skills_dir, existing)
        if not os.path.isdir(full):
            continue
        marker = _read_marker(full)
        if marker is not None:
            managed_by_dir[existing] = str(marker.get("skill_id") or "")
    dir_by_skill_id: Dict[str, str] = {}
    for d, sid in managed_by_dir.items():
        if sid:
            dir_by_skill_id.setdefault(sid, d)

    claimed = set()  # dirs assigned during this pass

    from autoskill.management.formats.agent_skill import skill_dir_name

    for skill in skills:
        sid = str(skill.id)
        base = skill_dir_name(skill)
        if sid in dir_by_skill_id:
            # This skill already has a managed dir -> update it in place.
            dir_name = dir_by_skill_id[sid]
        else:
            dir_name = base
            # If the base name is taken by a foreign (non-managed) skill dir,
            # prefer the `-autoskill` suffix and never overwrite the foreign dir.
            foreign = os.path.join(pi_skills_dir, base)
            if os.path.isdir(foreign) and _read_marker(foreign) is None:
                dir_name = f"{base}-autoskill"
            # De-dup within this projection against dirs claimed this pass or
            # already owned by a *different* skill.
            taken = claimed | {d for d, s in managed_by_dir.items() if s != sid}
            if dir_name in taken:
                i = 2
                while f"{dir_name}-{i}" in taken:
                    i += 1
                dir_name = f"{dir_name}-{i}"
        claimed.add(dir_name)

        target_root = os.path.join(pi_skills_dir, dir_name)
        files = sdk.export_skill_dir(skill.id) or {}
        for rel_path, content in files.items():
            rel_path = str(rel_path).lstrip("/").replace("..", "_")
            abs_path = os.path.join(target_root, rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        _write_marker(
            target_root,
            skill_id=sid,
            name=str(skill.name),
            version=str(getattr(skill, "version", "") or ""),
            user_id=user_id,
        )
        written.append({"dir": dir_name, "skill_id": sid, "name": str(skill.name)})

    _prune_stale(pi_skills_dir, keep_dirs={w["dir"] for w in written})
    return {"pi_skills_dir": pi_skills_dir, "count": len(written), "skills": written}


def _prune_stale(pi_skills_dir: str, *, keep_dirs: set) -> None:
    """
    Removes AutoSkill-managed dirs that were not (re)written this pass, i.e.
    skills that were deleted/merged away plus any legacy duplicate mirrors.
    Foreign dirs are never touched.
    """

    for entry in os.listdir(pi_skills_dir):
        full = os.path.join(pi_skills_dir, entry)
        if not os.path.isdir(full):
            continue
        if _read_marker(full) is None:
            continue  # not ours
        if entry in keep_dirs:
            continue
        _remove_tree(full)


def _remove_tree(dir_path: str) -> None:
    import shutil

    try:
        shutil.rmtree(dir_path)
    except Exception:
        pass
