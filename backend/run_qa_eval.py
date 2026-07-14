"""Run the 25-question test set against /ask and grade with LLM-as-judge.

Loads a test-questions JSON file from the job dir, fires each question at
/ask, and writes (a) the raw answer log + (b) a Markdown report next to it.

Run from backend/:
  .venv/bin/python run_qa_eval.py                    # uses test_questions.json
  .venv/bin/python run_qa_eval.py test_questions_v2.json
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

JOB_ID   = "bd5c00c4-4765-48b4-833e-c3b5e82e1acf"
HOST     = "http://localhost:8000"
JOB_DIR  = Path(__file__).parent / "data" / "jobs" / JOB_ID
QFILE    = sys.argv[1] if len(sys.argv) > 1 else "test_questions.json"
STEM     = Path(QFILE).stem
OUT_JSON = JOB_DIR / f"qa_eval_results{('_' + STEM.replace('test_questions', '').lstrip('_')) if STEM != 'test_questions' else ''}.json"
OUT_MD   = JOB_DIR / f"qa_eval_report{('_' + STEM.replace('test_questions', '').lstrip('_')) if STEM != 'test_questions' else ''}.md"


def ask(question: str) -> dict:
    body = json.dumps({"question": question}).encode()
    req = urllib.request.Request(
        f"{HOST}/api/jobs/{JOB_ID}/ask",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            d = json.loads(resp.read())
            d["_wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return d
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}",
                "_wall_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}",
                "_wall_ms": round((time.perf_counter() - t0) * 1000, 1)}


_WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12",
}


def _norm_for_keyword(s: str) -> str:
    """Normalize text for synonym-tolerant keyword matching.

    Lowercases, then for any number-word ("three") inserts the digit ("3")
    nearby in the normalized string. This lets the keyword check accept
    "3 projects" against an expected keyword of "three" and vice-versa.
    Also strips trailing punctuation from each token so 'M,' matches 'M'.
    """
    import re
    s = (s or "").lower()
    # Map number-words → digits (additively, so original still matches too)
    for word, digit in _WORD_TO_DIGIT.items():
        if word in s:
            s = s.replace(word, f"{word} {digit}")
    return s


def keyword_grade(answer: str, expected_keywords: list[str]) -> tuple[bool, list[str]]:
    """Synonym-tolerant deterministic grade. Each expected_keyword must
    appear (case-insensitive) in the normalized answer. Numbers like '3'
    and 'three' are treated as equivalent."""
    ans = _norm_for_keyword(answer)
    missing: list[str] = []
    for kw in expected_keywords:
        kw_lower = kw.lower()
        kw_norm = _WORD_TO_DIGIT.get(kw_lower, kw_lower)
        if kw_lower in ans or kw_norm in ans:
            continue
        missing.append(kw)
    return (len(missing) == 0, missing)


def main() -> int:
    test_file = JOB_DIR / QFILE
    with open(test_file) as f:
        suite = json.load(f)

    qs = suite["questions"]
    print(f"Loaded {len(qs)} questions. Running against {HOST}/api/jobs/{JOB_ID}/ask\n")

    results = []
    for i, q in enumerate(qs, 1):
        print(f"[{i:>2}/{len(qs)}] {q['id']} ({q['route']:<8}) → ", end="", flush=True)
        r = ask(q["q"])
        if r.get("error"):
            print(f"ERROR — {r['error']}")
            results.append({**q, "answer": "", "judge_verdict": "error",
                            "judge_score": 0.0, "judge_rationale": r["error"],
                            "keyword_pass": False, "missing_keywords": q["expected_keywords"],
                            "wall_ms": r["_wall_ms"]})
            continue

        ans   = r.get("answer", "")
        kw_pass, missing = keyword_grade(ans, q["expected_keywords"])
        results.append({
            "id": q["id"],
            "category": q["category"],
            "route": q["route"],
            "q": q["q"],
            "expected_answer": q["expected_answer"],
            "expected_keywords": q["expected_keywords"],
            "answer": ans,
            "judge_verdict": r.get("judge_verdict"),
            "judge_score": r.get("judge_score"),
            "judge_rationale": r.get("judge_rationale"),
            "keyword_pass": kw_pass,
            "missing_keywords": missing,
            "confidence": r.get("confidence"),
            "confidence_label": r.get("confidence_label"),
            "context_chunks": r.get("context_chunks"),
            "retrieved_count": len(r.get("retrieved", [])),
            "wall_ms": r["_wall_ms"],
            "answer_input_tokens": r.get("input_tokens", 0),
            "answer_output_tokens": r.get("output_tokens", 0),
            "answer_cost_usd": r.get("cost_usd", 0.0),
            # Route trace — which storage shapes contributed to this answer
            "fact_used":         r.get("fact_used", False),
            "fact_match_key":    (r.get("fact_match") or {}).get("key"),
            "fact_match_score":  (r.get("fact_match") or {}).get("match_score"),
            "sql_used":          r.get("sql_used", False),
            "sql_query":         r.get("sql_query"),
            "sql_router_reason": r.get("sql_router_reason"),
            "rerank_used":       r.get("rerank_used", False),
            "rerank_kept":       r.get("rerank_kept"),
        })
        score_val = r.get('judge_score')
        score_str = f"{score_val:.2f}" if isinstance(score_val, (int, float)) else "?.??"
        print(f"{r.get('judge_verdict') or '?':<11} score={score_str} kw_pass={kw_pass} ({r['_wall_ms']:.0f}ms)")

    # Persist raw results
    out_json = OUT_JSON
    with open(out_json, "w") as f:
        json.dump({"job_id": JOB_ID, "results": results, "source_file": QFILE}, f, indent=2)
    print(f"\nWrote raw results → {out_json}")

    # ── Aggregate ────────────────────────────────────────────────────────
    n = len(results)
    verdicts: dict[str, int] = {}
    by_route: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    total_cost = 0.0
    total_input = total_output = 0
    total_wall_ms = 0.0

    for r in results:
        v = r.get("judge_verdict") or "unknown"
        verdicts[v] = verdicts.get(v, 0) + 1
        route = r.get("route", "?")
        by_route.setdefault(route, {"n": 0, "correct": 0, "kw_pass": 0, "score_sum": 0.0})
        by_route[route]["n"] += 1
        if v == "correct":   by_route[route]["correct"] += 1
        if r.get("keyword_pass"): by_route[route]["kw_pass"] += 1
        by_route[route]["score_sum"] += r.get("judge_score") or 0.0

        cat = r.get("category", "?")
        by_category.setdefault(cat, {"n": 0, "correct": 0, "kw_pass": 0})
        by_category[cat]["n"] += 1
        if v == "correct":   by_category[cat]["correct"] += 1
        if r.get("keyword_pass"): by_category[cat]["kw_pass"] += 1

        total_cost += r.get("answer_cost_usd") or 0.0
        total_input += r.get("answer_input_tokens") or 0
        total_output += r.get("answer_output_tokens") or 0
        total_wall_ms += r.get("wall_ms") or 0.0

    # ── Build the Markdown report ────────────────────────────────────────
    lines: list[str] = []
    L = lines.append
    L(f"# RAG Evaluation Report\n")
    L(f"**Job:** `{JOB_ID}`  ")
    L(f"**Questions:** {n}  ")
    L(f"**Total cost (answer LLM only, excludes judge & embedding):** ${total_cost:.4f}  ")
    L(f"**Total tokens:** {total_input:,} in / {total_output:,} out  ")
    L(f"**Total wall time:** {total_wall_ms/1000:.1f}s ({total_wall_ms/n:.0f}ms avg per Q)  \n")

    L("## Headline\n")
    correct = verdicts.get("correct", 0)
    partial = verdicts.get("partial", 0)
    kw_pass = sum(1 for r in results if r.get("keyword_pass"))
    L(f"| Metric | Count | % |")
    L(f"|---|---:|---:|")
    L(f"| Judge: **correct** | {correct} | {100*correct/n:.0f}% |")
    L(f"| Judge: **partial** | {partial} | {100*partial/n:.0f}% |")
    L(f"| Judge: **unsupported** | {verdicts.get('unsupported', 0)} | {100*verdicts.get('unsupported', 0)/n:.0f}% |")
    L(f"| Judge: **incorrect** | {verdicts.get('incorrect', 0)} | {100*verdicts.get('incorrect', 0)/n:.0f}% |")
    L(f"| Judge: error/other | {n - correct - partial - verdicts.get('unsupported',0) - verdicts.get('incorrect',0)} | — |")
    L(f"| **Keyword check pass** | {kw_pass} | {100*kw_pass/n:.0f}% |")
    L("")

    L("## By Retrieval Route\n")
    L("Routes test whether the system uses the right backend for the question type.\n")
    L("| Route | n | correct | kw_pass | avg judge_score |")
    L("|---|---:|---:|---:|---:|")
    for route in ["semantic", "sql", "kg", "hybrid"]:
        s = by_route.get(route)
        if not s: continue
        L(f"| {route} | {s['n']} | {s['correct']}/{s['n']} ({100*s['correct']/s['n']:.0f}%) | "
          f"{s['kw_pass']}/{s['n']} ({100*s['kw_pass']/s['n']:.0f}%) | {s['score_sum']/s['n']:.2f} |")
    L("")

    L("## By Question Category\n")
    L("| Category | n | correct | kw_pass |")
    L("|---|---:|---:|---:|")
    for cat in sorted(by_category.keys()):
        s = by_category[cat]
        L(f"| {cat} | {s['n']} | {s['correct']}/{s['n']} | {s['kw_pass']}/{s['n']} |")
    L("")

    L("## Failures and Gaps\n")
    fails = [r for r in results if r.get("judge_verdict") not in ("correct",)]
    if not fails:
        L("_(no failures — every question scored `correct`.)_\n")
    else:
        L(f"{len(fails)} question(s) did not get a `correct` verdict:\n")
        for r in fails:
            jscore = r.get('judge_score')
            jscore_str = f"{jscore:.2f}" if isinstance(jscore, (int, float)) else "?.??"
            L(f"### ❌ {r['id']} ({r['route']}) — `{r.get('judge_verdict')}` (score {jscore_str})\n")
            L(f"**Q:** {r['q']}\n")
            L(f"**Expected:** {r['expected_answer']}\n")
            L(f"**Got:** {(r.get('answer') or '')[:500]}{'…' if len(r.get('answer') or '') > 500 else ''}\n")
            if r.get("missing_keywords"):
                L(f"**Missing keywords:** `{r['missing_keywords']}`\n")
            if r.get("judge_rationale"):
                L(f"**Judge rationale:** {r['judge_rationale'][:400]}\n")
            L("")

    L("## All Results (Detail)\n")
    L("| ID | Route | Verdict | Score | KW | Latency (ms) | Confidence |")
    L("|---|---|---|---:|:---:|---:|:---:|")
    for r in results:
        v = r.get("judge_verdict") or "?"
        emoji = {"correct": "✅", "partial": "🟡", "unsupported": "⚠️",
                 "incorrect": "❌", "error": "💥"}.get(v, "·")
        jscore = r.get('judge_score')
        jscore_str = f"{jscore:.2f}" if isinstance(jscore, (int, float)) else "—"
        L(f"| {r['id']} | {r.get('route')} | {emoji} {v} | "
          f"{jscore_str} | "
          f"{'✓' if r.get('keyword_pass') else '✗'} | "
          f"{r.get('wall_ms', 0):.0f} | "
          f"{r.get('confidence_label') or '—'} |")

    out_md = OUT_MD
    with open(out_md, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote Markdown report → {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
