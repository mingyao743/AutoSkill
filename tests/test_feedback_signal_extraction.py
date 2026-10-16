"""
Test: feedback signal → extraction prompt → skill candidate flow.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

# Ensure project root is on sys.path for AutoSkill4Pi imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# ── 1. classify_feedback_signal ──────────────────────────────────────────
print("\n=== 1. classify_feedback_signal ===")
from AutoSkill4Pi.runtime.pi_session_adapter import classify_feedback_signal

# 1a. correction → feedback, confidence 0.8
r = classify_feedback_signal([
    {"role": "assistant", "content": "Here is the report..."},
    {"role": "user", "content": "不对，应该是中文的"},
])
check("correction → feedback", r["signal"] == "feedback" and "correction" in r["types"], str(r))
check("correction confidence=0.8", r["confidence"] == 0.8, str(r))

# 1b. revision → feedback, confidence 0.8
r = classify_feedback_signal([
    {"role": "user", "content": "写一篇关于AI的文章"},
    {"role": "assistant", "content": "..." * 100},
    {"role": "user", "content": "重新写，语气要更正式"},
])
check("revision → feedback", r["signal"] == "feedback" and "revision" in r["types"], str(r))

# 1c. negative → feedback
r = classify_feedback_signal([
    {"role": "user", "content": "don't use markdown formatting"},
])
check("negative → feedback", r["signal"] == "feedback" and "negative" in r["types"], str(r))

# 1d. positive → feedback (weaker)
r = classify_feedback_signal([
    {"role": "user", "content": "很好，就这样"},
])
check("positive → feedback", r["signal"] == "feedback" and "positive" in r["types"], str(r))
check("positive confidence=0.6", r["confidence"] == 0.6, str(r))

# 1e. new request → request
r = classify_feedback_signal([
    {"role": "user", "content": "帮我写一个Python爬虫程序来抓取网页数据"},
])
check("new request → request", r["signal"] == "request", str(r))

# 1f. no user messages → unknown
r = classify_feedback_signal([
    {"role": "assistant", "content": "Hello"},
])
check("no user → unknown", r["signal"] == "unknown", str(r))

# 1g. mixed correction + positive
r = classify_feedback_signal([
    {"role": "user", "content": "错了，应该改成这样，很好"},
])
check("mixed correction+positive", "correction" in r["types"] and "positive" in r["types"], str(r))
check("mixed signal=feedback (correction dominates)", r["signal"] == "feedback", str(r))


# ── 2. LLMSkillExtractor with feedback_signal ────────────────────────────
print("\n=== 2. LLMSkillExtractor with feedback_signal ===")
from autoskill.config import AutoSkillConfig
from autoskill.llm.mock import MockLLM
from autoskill.management.extraction import LLMSkillExtractor, HeuristicSkillExtractor

# 2a. MockLLM returns a skill; verify feedback_signal reaches the payload
captured_payload = {}

def mock_capture(system, user, temperature=0.0, mode="default"):
    """Capture the user payload and return a valid skill JSON."""
    # Extract the DATA from the user prompt
    try:
        data_str = user.split("DATA:", 1)[-1] if "DATA:" in user else user
        # For the extract prompt, the entire user message is the JSON payload
        parsed = json.loads(user)
        captured_payload.update(parsed)
    except Exception:
        pass
    return json.dumps({
        "skills": [{
            "name": "chinese-report-writer",
            "description": "Writes reports in Chinese with formal tone.",
            "prompt": "# Goal\nWrite reports.\n# Constraints & Style\nMust be in Chinese.",
            "triggers": ["write a report", "撰写报告"],
            "tags": ["report", "chinese"],
            "confidence": 0.8,
        }]
    })

cfg = AutoSkillConfig(llm={"provider": "mock"})
llm = MockLLM(response=mock_capture)
ext = LLMSkillExtractor(cfg, llm=llm)

feedback = {"signal": "feedback", "types": ["correction"], "confidence": 0.8}
results = ext.extract(
    user_id="u1",
    messages=[
        {"role": "user", "content": "Write a report about AI"},
        {"role": "assistant", "content": "Here is the English report..."},
        {"role": "user", "content": "不对，应该是中文的"},
    ],
    events=[],
    max_candidates=1,
    feedback_signal=feedback,
)

check("extract returns 1 candidate", len(results) == 1, f"got {len(results)}")
if results:
    check("candidate name", results[0].name == "chinese-report-writer", results[0].name)
    check("candidate confidence", results[0].confidence == 0.8, str(results[0].confidence))

check("payload has feedback_signal", "feedback_signal" in captured_payload, str(list(captured_payload.keys())))
if "feedback_signal" in captured_payload:
    check("payload feedback_signal.signal", captured_payload["feedback_signal"].get("signal") == "feedback")
    check("payload feedback_signal.types", captured_payload["feedback_signal"].get("types") == ["correction"])

# 2b. Without feedback_signal → payload has None
captured_payload.clear()
results2 = ext.extract(
    user_id="u1",
    messages=[{"role": "user", "content": "Write a report"}],
    events=[],
    max_candidates=1,
)
check("no feedback_signal → payload has key", "feedback_signal" in captured_payload, str(list(captured_payload.keys())))
check("no feedback_signal → value is None", captured_payload.get("feedback_signal") is None,
      str(captured_payload.get("feedback_signal")))


# ── 3. HeuristicSkillExtractor accepts feedback_signal ───────────────────
print("\n=== 3. HeuristicSkillExtractor accepts feedback_signal ===")
hext = HeuristicSkillExtractor(cfg)
try:
    h_results = hext.extract(
        user_id="u1",
        messages=[{"role": "user", "content": "Step 1: deploy\nStep 2: verify\nStep 3: rollback"}],
        events=[],
        max_candidates=1,
        feedback_signal={"signal": "feedback", "types": ["correction"], "confidence": 0.8},
    )
    check("heuristic accepts feedback_signal", True)
    check("heuristic returns candidates", len(h_results) >= 1, f"got {len(h_results)}")
except TypeError as e:
    check("heuristic accepts feedback_signal", False, str(e))


# ── 4. Full sdk.ingest() flow with feedback_signal in metadata ───────────
print("\n=== 4. sdk.ingest() with feedback_signal in metadata ===")
from autoskill import AutoSkill, AutoSkillConfig

mock_responses = {
    "default": json.dumps({
        "skills": [{
            "name": "formal-chinese-report",
            "description": "Writes formal Chinese reports.",
            "prompt": "# Goal\nWrite formal Chinese reports.\n# Constraints & Style\nChinese only.",
            "triggers": ["撰写报告", "write report in Chinese"],
            "tags": ["report", "chinese"],
            "confidence": 0.85,
        }]
    }),
    "manage_decide": json.dumps({"decision": "add", "reason": "new skill"}),
}

ingest_llm = MockLLM(response=mock_responses)
ingest_ext = LLMSkillExtractor(cfg, llm=ingest_llm)

sdk = AutoSkill(AutoSkillConfig(
    llm={"provider": "mock"},
    store={"provider": "local", "path": "/tmp/autoskill_test_skill"},
))
sdk._extractor = ingest_ext

import shutil, os
store_path = "/tmp/autoskill_test_skill"
if os.path.exists(store_path):
    shutil.rmtree(store_path)
os.makedirs(os.path.join(store_path, "index"), exist_ok=True)

try:
    updated = sdk.ingest(
        user_id="u1",
        messages=[
            {"role": "user", "content": "帮我写一份AI行业报告"},
            {"role": "assistant", "content": "Here is the report in English..."},
            {"role": "user", "content": "不对，应该是中文的，语气要正式"},
        ],
        events=[],
        metadata={
            "feedback_signal": {"signal": "feedback", "types": ["correction", "revision"], "confidence": 0.8},
        },
    )
    check("ingest returns skills", len(updated) >= 1, f"got {len(updated)}")
    if updated:
        check("ingested skill name", "formal-chinese" in updated[0].name.lower() or "report" in updated[0].name.lower(),
              updated[0].name)
        print(f"        ingested: {updated[0].name} v{updated[0].version}")
except Exception as e:
    check("ingest completes", False, f"{e}\n{traceback.format_exc()}")
finally:
    if os.path.exists(store_path):
        shutil.rmtree(store_path)


# ── 5. Prompt content check ─────────────────────────────────────────────
print("\n=== 5. Prompt contains feedback_signal guidance ===")
captured_system = {}

def capture_system(system, user, temperature=0.0, mode="default"):
    captured_system["text"] = system
    return json.dumps({"skills": []})

check_llm = MockLLM(response=capture_system)
check_ext = LLMSkillExtractor(cfg, llm=check_llm)
check_ext.extract(
    user_id="u1",
    messages=[{"role": "user", "content": "test"}],
    events=[],
    max_candidates=1,
    feedback_signal={"signal": "feedback", "types": ["correction"], "confidence": 0.8},
)

prompt_text = captured_system.get("text", "")
check("prompt has FEEDBACK SIGNAL in section 1", "FEEDBACK SIGNAL" in prompt_text, f"len={len(prompt_text)}")
check("prompt has feedback_signal in section 3", "FEEDBACK SIGNAL BOOST" in prompt_text)
check("prompt references DATA.feedback_signal", "DATA.feedback_signal" in prompt_text)


# ── Summary ──────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
if FAIL:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
