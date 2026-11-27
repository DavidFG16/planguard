"""CLI: python -m planguard <plan.json> [--out comment.md] [--pr-title TITLE] [--offline]

Exit codes: 0 = low/medium/high or no changes (check passes), 2 = critical
(check fails, merge blocked), 1 = PlanGuard itself failed (fails closed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .context import build_context
from .explain import ExplainResult, explain
from .plan import Plan
from .render import render
from .rules import evaluate, exit_code, overall_level


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planguard", description="Review a Terraform plan (terraform show -json).")
    parser.add_argument("plan_json", help="output of: terraform show -json tfplan")
    parser.add_argument("--out", help="write the Markdown comment to this file (default: stdout)")
    parser.add_argument("--pr-title", default=os.environ.get("PR_TITLE", ""), help="the author's stated intent")
    parser.add_argument("--commit", default=os.environ.get("PR_HEAD_SHA", ""), help="commit shown in the footer")
    parser.add_argument("--offline", action="store_true", help="never call Claude (rules only)")
    args = parser.parse_args(argv)
    account_ids = tuple(filter(None, [os.environ.get("SANDBOX_ACCOUNT_ID", "")]))

    try:
        plan = Plan.load(args.plan_json)
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f"planguard: cannot read the plan: {error}", file=sys.stderr)
        return 1

    findings = evaluate(plan)
    level = overall_level(plan, findings)
    result: ExplainResult | None = None
    if level is not None:
        if args.offline:
            result = ExplainResult(None, "offline mode")
        else:
            result = explain(build_context(plan, findings, level), args.pr_title, account_ids=account_ids)

    comment = render(plan, findings, level, result, commit=args.commit, account_ids=account_ids)
    if args.out:
        Path(args.out).write_text(comment)
    else:
        sys.stdout.write(comment)

    code = exit_code(level)
    tokens = ""
    if result and result.usage:
        tokens = f" (Claude tokens: {result.usage['input_tokens']} in, {result.usage['output_tokens']} out)"
    print(f"planguard: risk {level.label if level else 'NONE'}, exit {code}{tokens}", file=sys.stderr)
    if result and result.note:
        print(f"planguard: no AI explanation: {result.note}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
