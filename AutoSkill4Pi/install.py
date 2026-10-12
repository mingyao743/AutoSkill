"""
AutoSkill4Pi installer.

Copies the Pi extension into the Pi user extensions directory and prepares the
local AutoSkill working dirs (SkillBank, sessions pointer, user skills mirror).

Usage (from the AutoSkill repo root):
    python3 -m pip install -e .
    python3 AutoSkill4Pi/install.py --repo-dir "$(pwd)"

After install, export the runtime env (Pi loads extensions with your shell env):
    export AUTOSKILL_PI_REPO_DIR=/abs/path/to/AutoSkill
    # optional; if unset the extension falls back to config-resolve bridge you set:
    # export AUTOSKILL_PI_LLM_BASE_URL=...   (see README for model reuse notes)
Then start `pi` normally.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _expand(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Install AutoSkill4Pi Pi extension")
    ap.add_argument("--repo-dir", default=os.getcwd(), help="AutoSkill repo checkout root (contains AutoSkill4Pi/).")
    ap.add_argument("--pi-ext-dir", default="~/.pi/agent/extensions", help="Pi user extensions directory.")
    ap.add_argument("--pi-home", default="~/.pi/autoskill", help="AutoSkill local home (SkillBank, ledger).")
    ap.add_argument("--pi-skills-dir", default="~/.pi/agent/skills", help="Pi user-level skills mirror dir.")
    args = ap.parse_args(argv)

    repo_dir = _expand(args.repo_dir)
    if not os.path.isdir(os.path.join(repo_dir, "AutoSkill4Pi")):
        print(f"[AutoSkill4Pi] repo-dir 下未找到 AutoSkill4Pi/: {repo_dir}", file=sys.stderr)
        return 2

    ext_src = os.path.join(HERE, "extension")
    ext_dst = os.path.join(_expand(args.pi_ext_dir), "autoskill")
    os.makedirs(ext_dst, exist_ok=True)
    for fn in ("autoskill-pi.ts", "package.json"):
        shutil.copy2(os.path.join(ext_src, fn), os.path.join(ext_dst, fn))

    os.makedirs(_expand(args.pi_home), exist_ok=True)
    os.makedirs(os.path.join(_expand(args.pi_home), "SkillBank"), exist_ok=True)
    os.makedirs(_expand(args.pi_skills_dir), exist_ok=True)

    print("[AutoSkill4Pi] 安装完成。")
    print(f"  extension -> {ext_dst}")
    print(f"  SkillBank -> {os.path.join(_expand(args.pi_home), 'SkillBank')}")
    print(f"  技能镜像   -> {_expand(args.pi_skills_dir)}")
    print()
    print("请在启动 pi 前设置环境变量:")
    print(f"  export AUTOSKILL_PI_REPO_DIR={repo_dir}")
    print("  export AUTOSKILL_PI_PYTHON=python3        # 需为安装了 autoskill 的解释器")
    print("  # 复用 Pi 模型由 extension 内置 bridge 自动接管,无需手填 LLM key")
    print()
    print("验证:")
    print("  python3 AutoSkill4Pi/tests/test_pipeline.py")
    print("  pi   # 正常对话,收口后自动抽取;或 /autoskill_extract_now 主动触发")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
