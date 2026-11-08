"""Command line for the Refund Desk. Prints exactly one JSON object to stdout."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .desk import DeskConfig, RefundCase, failed_result, process_refund, reconcile_case, uncertain_result

_EXIT = {"executed": 0, "held": 2, "refused": 2, "denied": 2, "uncertain": 3, "failed": 1}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="refund_desk", description="Synthetic Refund Desk (nonproduction, non-authorizing).")
    p.add_argument("command", choices=["process", "reconcile"])
    p.add_argument("--case-id", "--case", dest="case_id", required=True)  # "--case" is kept as an explicit alias: it was a unique abbreviation before --case-reference existed
    p.add_argument("--tenant", required=True)
    p.add_argument("--customer-account", required=True)
    p.add_argument("--amount", required=True, type=float)
    p.add_argument("--currency", default="USD")
    p.add_argument("--reason", required=True)
    p.add_argument("--authority", choices=["valid", "revoked"], default="valid")
    p.add_argument("--profile", default=None,
                   help="approved F1 profile id: refund-routine-v1 (the historical profile, used when this option is omitted) or refund-high-v1; forwarded unvalidated, F1 refuses anything else")
    p.add_argument("--case-reference", default=None,
                   help="case reference forwarded unvalidated to F1 (required by refund-high-v1, forbidden by refund-routine-v1)")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--stack-root", default=None)
    return p


def _emit(result) -> int:
    try:
        text = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        code = _EXIT.get(result.outcome, 1)
    except Exception as exc:
        text = json.dumps(uncertain_result(getattr(result, "case_id", ""), "%s: %s" % (type(exc).__name__, exc)).to_dict(),
                          sort_keys=True, indent=2)
        code = 3
    sys.stdout.write(text + "\n")
    return code


class _Usage(Exception):
    pass


class _ArgParser(argparse.ArgumentParser):
    def error(self, message):  # keep stdout a single JSON object on usage errors
        raise _Usage(message)


def main(argv=None) -> int:
    parser = _parser()
    parser.__class__ = _ArgParser
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(args_list)
    except _Usage as exc:
        return _emit(failed_result("", "usage error: %s" % exc))
    except SystemExit as exc:  # --help exits 0; other argparse exits stay nonzero
        return exc.code if isinstance(exc.code, int) else 1
    stack_root = args.stack_root or os.environ.get("REFUND_DESK_STACK_ROOT")
    if not stack_root:
        return _emit(failed_result(args.case_id, "no stack root: pass --stack-root or set REFUND_DESK_STACK_ROOT", args.profile))
    case = RefundCase(case_id=args.case_id, tenant_id=args.tenant, customer_account=args.customer_account,
                      amount=args.amount, reason=args.reason, currency=args.currency, authority=args.authority,
                      profile=args.profile, case_reference=args.case_reference)
    config = DeskConfig(stack_root=Path(stack_root), state_dir=Path(args.state_dir))
    try:
        result = process_refund(case, config) if args.command == "process" else reconcile_case(case, config)
    except Exception as exc:  # only reachable before the F1 call (request building); never an execution claim
        return _emit(failed_result(args.case_id, "%s: %s" % (type(exc).__name__, exc), args.profile))
    return _emit(result)
