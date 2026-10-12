"""
Python-side tests for AutoSkill4Pi.

Run from the AutoSkill repo root:
    python3 -m pytest AutoSkill4Pi/tests -q
or without pytest:
    python3 AutoSkill4Pi/tests/test_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from AutoSkill4Pi.runtime.pi_session_adapter import file_to_records, load_pi_session  # noqa: E402
from AutoSkill4Pi.runtime.pi_skill_mirror import MANAGED_MARKER, mirror_user_skills  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sample_session.jsonl")


class TestPiSessionAdapter(unittest.TestCase):
    def test_active_branch_extraction(self):
        records, diags = file_to_records(FIXTURE)
        self.assertEqual(len(records), 1)
        rec = records[0]
        diag = diags[0]

        # Messages: user + 2 assistant texts. Abandoned branch excluded.
        roles = [m["role"] for m in rec["messages"]]
        self.assertEqual(roles, ["user", "assistant", "assistant"])
        self.assertIn("Never invent citations", rec["messages"][0]["content"])
        joined = json.dumps(rec, ensure_ascii=False)
        self.assertNotIn("abandoned alternative", joined)

        # Events: one tool_call + one tool_result.
        kinds = [e["event_type"] for e in rec["events"]]
        self.assertEqual(kinds, ["tool_call", "tool_result"])
        self.assertEqual(rec["events"][0]["tool"], "bash")

        # Recursion guard: autoskill-owned entry on the branch was filtered.
        self.assertEqual(diag["skipped_autoskill"], 1)
        self.assertEqual(diag["skipped_system"], 1)
        self.assertTrue(rec["success"])

    def test_fingerprint_changes_with_new_leaf(self):
        from AutoSkill4Pi.runtime.pi_runtime import _branch_fingerprint

        fp1 = _branch_fingerprint(FIXTURE)
        # Append a new entry -> leaf changes -> fingerprint changes.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "s.jsonl")
            with open(FIXTURE, "r", encoding="utf-8") as src, open(path, "w", encoding="utf-8") as dst:
                dst.write(src.read())
                dst.write(
                    json.dumps(
                        {
                            "type": "message",
                            "id": "asst9999",
                            "parentId": "asst0002",
                            "timestamp": "2026-10-12T09:01:00.000Z",
                            "message": {"role": "assistant", "content": [{"type": "text", "text":"more"}], "timestamp": 1760000060000},
                        }
                    )
                    + "\n"
                )
            fp2 = _branch_fingerprint(path)
        self.assertNotEqual(fp1, fp2)

    def test_terminal_error_marks_unsuccessful(self):
        parsed = load_pi_session(FIXTURE)
        parsed["entries"].append(
            {
                "type": "message",
                "id": "tool9999",
                "parentId": "asst0002",
                "timestamp": "2026-10-12T09:02:00.000Z",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "call_9",
                    "toolName": "bash",
                    "content": [{"type": "text", "text": "boom"}],
                    "isError": True,
                    "timestamp": 1760000120000,
                },
            }
        )
        from AutoSkill4Pi.runtime.pi_session_adapter import session_to_record

        rec, diag = session_to_record(parsed)
        self.assertIsNotNone(rec)
        self.assertFalse(rec["success"])
        self.assertTrue(diag["terminal_is_error"])


class TestMirror(unittest.TestCase):
    def _sdk(self, store_dir: str):
        from autoskill import AutoSkill, AutoSkillConfig

        return AutoSkill(
            AutoSkillConfig(
                llm={"provider": "mock"},
                embeddings={"provider": "hashing", "dims": 256},
                store={"provider": "local", "path": store_dir},
            )
        )

    def test_mirror_writes_pi_compatible_skill(self):
        with tempfile.TemporaryDirectory() as td:
            sdk = self._sdk(os.path.join(td, "SkillBank"))
            sdk.upsert(
                user_id="pi",
                name="No Fabricated Metrics",
                description="When writing reports or release notes, never invent citations, benchmarks, or metrics.",
                instructions="1. Only cite measured numbers.\n2. Link every claim to a source.",
                tags=["writing", "integrity"],
            )
            skills_dir = os.path.join(td, "pi-skills")
            result = mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            self.assertEqual(result["count"], 1)

            skill_root = os.path.join(skills_dir, result["skills"][0]["dir"])
            md_path = os.path.join(skill_root, "SKILL.md")
            self.assertTrue(os.path.isfile(md_path))
            with open(md_path, "r", encoding="utf-8") as f:
                md = f.read()
            # Pi (Agent Skills spec) requires name + description frontmatter.
            self.assertTrue(md.startswith("---"))
            fm = md.split("---", 2)[1]
            self.assertIn("name:", fm)
            self.assertIn("description:", fm)

            # Management marker written; prune removes stale managed skills.
            self.assertTrue(os.path.isfile(os.path.join(skill_root, MANAGED_MARKER)))
            deleted = sdk.list(user_id="pi")[0]
            sdk.delete(deleted.id)
            mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            self.assertFalse(os.path.isdir(skill_root))

    def test_mirror_does_not_clobber_foreign_skill(self):
        with tempfile.TemporaryDirectory() as td:
            sdk = self._sdk(os.path.join(td, "SkillBank"))
            sdk.upsert(
                user_id="pi",
                name="Safety",
                description="Project safety conventions.",
                instructions="Always run tests before commit.",
            )
            skills_dir = os.path.join(td, "pi-skills")
            foreign = os.path.join(skills_dir, "safety")
            os.makedirs(foreign, exist_ok=True)
            with open(os.path.join(foreign, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: safety\ndescription: human written\n---\n\nhand written\n")

            result = mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            mirrored_dir = result["skills"][0]["dir"]
            self.assertEqual(mirrored_dir, "safety-autoskill")
            with open(os.path.join(foreign, "SKILL.md"), "r", encoding="utf-8") as f:
                self.assertIn("hand written", f.read())

    def test_mirror_is_stable_on_repeat(self):
        # Regression: re-mirroring an active skill must update its dir in place,
        # not spawn `<slug>-autoskill-2`, `<slug>-autoskill-3` clones.
        with tempfile.TemporaryDirectory() as td:
            sdk = self._sdk(os.path.join(td, "SkillBank"))
            sdk.upsert(
                user_id="pi",
                name="No Fabricated Metrics",
                description="never invent metrics",
                instructions="only cite measured numbers",
            )
            skills_dir = os.path.join(td, "pi-skills")
            first = mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            dir1 = first["skills"][0]["dir"]
            second = mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            third = mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            self.assertEqual(second["skills"][0]["dir"], dir1)
            self.assertEqual(third["skills"][0]["dir"], dir1)
            self.assertEqual(sorted(os.listdir(skills_dir)), sorted([dir1]))

    def test_mirror_prunes_legacy_duplicate_dirs(self):
        # Regression: leftover `<slug>-autoskill-2` clones from the old bug are
        # cleaned up on the next mirror pass.
        with tempfile.TemporaryDirectory() as td:
            sdk = self._sdk(os.path.join(td, "SkillBank"))
            sdk.upsert(
                user_id="pi",
                name="Stable Skill",
                description="a stable skill",
                instructions="do the thing",
            )
            skills_dir = os.path.join(td, "pi-skills")
            base = mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)["skills"][0]["dir"]
            dup = os.path.join(skills_dir, base + "-2")
            os.makedirs(dup, exist_ok=True)
            with open(os.path.join(dup, MANAGED_MARKER), "w", encoding="utf-8") as f:
                json.dump({"managedBy": "autoskill", "skill_id": sdk.list(user_id="pi")[0].id}, f)
            mirror_user_skills(sdk, user_id="pi", pi_skills_dir=skills_dir)
            self.assertFalse(os.path.isdir(dup))
            self.assertTrue(os.path.isdir(os.path.join(skills_dir, base)))


class TestRuntimeDedup(unittest.TestCase):
    def test_ledger_skips_already_processed(self):
        import AutoSkill4Pi.runtime.pi_runtime as rt

        with tempfile.TemporaryDirectory() as td:
            os.environ["AUTOSKILL_PI_LEDGER"] = os.path.join(td, "ledger.jsonl")
            os.environ["AUTOSKILL_PI_STORE_DIR"] = os.path.join(td, "SkillBank")
            os.environ["AUTOSKILL_PI_SKILLS_DIR"] = os.path.join(td, "pi-skills")
            os.environ["AUTOSKILL_PI_LLM_PROVIDER"] = "mock"

            # dry-run path is internal; exercise fingerprint dedupe directly.
            fp = rt._branch_fingerprint(FIXTURE)
            rt._append_ledger([fp], session_paths=[FIXTURE])
            seen = rt._load_ledger()
            self.assertIn(fp, seen)

            summary = rt.process_sessions([FIXTURE], dry_run=True)
            self.assertEqual(summary["processed_files"], 0)
            self.assertEqual(summary["skipped_files"], 1)


class TestRuntimeExtraction(unittest.TestCase):
    def _sdk(self, store_dir: str):
        from autoskill import AutoSkill, AutoSkillConfig

        return AutoSkill(
            AutoSkillConfig(
                llm={"provider": "mock"},
                embeddings={"provider": "hashing", "dims": 256},
                store={"provider": "local", "path": store_dir},
            )
        )

    def test_structured_records_are_not_flattened(self):
        # Regression: passing several trajectory records via data= must keep them
        # as separate records (with events + per-record success), not collapse
        # them into one flattened text blob.
        from autoskill.offline.trajectory.extract import extract_from_agentic_trajectory

        records = [
            {
                "success": True,
                "messages": [{"role": "user", "content": "draft release notes"}],
                "events": [{"event_type": "tool_call", "tool": "bash", "text": "git log"}],
            },
            {
                "success": False,
                "messages": [{"role": "user", "content": "a failed attempt"}],
                "events": [],
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            sdk = self._sdk(os.path.join(td, "SkillBank"))
            result = extract_from_agentic_trajectory(
                sdk=sdk,
                user_id="pi",
                data={"records": records},
                include_tool_events=True,
                success_only=True,
                continue_on_error=True,
            )
            self.assertEqual(result["total_records"], 2)
            self.assertEqual(result["skipped"], 1)  # the success=False record

    def test_collect_session_files_expands_tilde(self):
        # Regression: the extension passes a literal `~` path (spawn does not
        # expand it), so the runtime must expanduser the sessions dir itself.
        import AutoSkill4Pi.runtime.pi_runtime as rt

        with tempfile.TemporaryDirectory() as td:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = td
            try:
                sess_dir = os.path.join(td, ".pi", "agent", "sessions", "--cwd--")
                os.makedirs(sess_dir, exist_ok=True)
                import shutil

                shutil.copy(FIXTURE, os.path.join(sess_dir, "s.jsonl"))
                files = rt._collect_session_files("~/.pi/agent/sessions")
                self.assertEqual(len(files), 1)
                self.assertTrue(os.path.isabs(files[0]))
            finally:
                if old_home is not None:
                    os.environ["HOME"] = old_home


if __name__ == "__main__":
    unittest.main(verbosity=2)
