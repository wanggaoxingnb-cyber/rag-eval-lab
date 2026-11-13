#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rag import BASELINE, IMPROVED, answer_query  # noqa: E402


def load_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def failure_layer(case: dict, result: dict) -> str | None:
    expected = case["expected"]
    if expected == "answer" and result["type"] != "answer":
        return "retrieval_threshold"
    if expected == "answer":
        missing = set(case["expected_docs"]) - set(result["citations"])
        if missing:
            return "evidence_coverage" if case["category"] == "multi_doc" else "retrieval_relevance"
    if expected == "refuse_injection" and result["type"] != "refuse_injection":
        return "injection_guard"
    if expected == "refuse_no_evidence" and result["type"] != "refuse_no_evidence":
        return "refusal_policy"
    return None


def passes(case: dict, result: dict) -> bool:
    if case["expected"] == "answer":
        return result["type"] == "answer" and set(case["expected_docs"]) <= set(result["citations"])
    return result["type"] == case["expected"]


def execute(documents: list[dict], cases: list[dict], config) -> dict:
    details = []
    for case in cases:
        result = answer_query(case["question"], documents, config)
        failure = failure_layer(case, result)
        details.append({
            **case, "actual": result["type"], "passed": passes(case, result),
            "citations": result["citations"], "top_score": result["top_score"],
            "answer": result["answer"], "failure_layer": failure,
            "evidence": result["evidence"],
        })
    by_category = defaultdict(lambda: {"total": 0, "passed": 0})
    failures = Counter()
    for row in details:
        group = by_category[row["category"]]
        group["total"] += 1
        group["passed"] += int(row["passed"])
        if row["failure_layer"]:
            failures[row["failure_layer"]] += 1
    return {
        "config": config.__dict__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(details), "passed": sum(row["passed"] for row in details),
            "pass_rate": round(sum(row["passed"] for row in details) / len(details), 4),
            "by_category": dict(by_category), "failure_layers": dict(failures),
        },
        "cases": details,
    }


def markdown_report(baseline: dict, improved: dict) -> str:
    lines = [
        "# RAG 评测回归报告", "",
        "> 数据为公开虚构示例；答案由确定性模板组装，不伪称 LLM 生成。结果由 `python3 src/evaluate.py` 产生。", "",
        "## 指标对比", "",
        "| 配置 | 通过/总数 | 通过率 | 主要失败层 |",
        "|---|---:|---:|---|",
    ]
    for result in (baseline, improved):
        summary = result["summary"]
        lines.append(
            f"| {result['config']['name']} | {summary['passed']}/{summary['total']} | "
            f"{summary['pass_rate']:.1%} | {summary['failure_layers']} |"
        )
    lines += ["", "## 分类通过率", "", "| 类别 | 基线 | 改进 |", "|---|---:|---:|"]
    for category in ("direct", "multi_doc", "refusal", "injection"):
        b = baseline["summary"]["by_category"][category]
        i = improved["summary"]["by_category"][category]
        lines.append(f"| {category} | {b['passed']}/{b['total']} | {i['passed']}/{i['total']} |")
    lines += ["", "## 仍未通过或退化案例", ""]
    improved_ids = {row["id"]: row["passed"] for row in improved["cases"]}
    regressions = [row["id"] for row in baseline["cases"] if row["passed"] and not improved_ids[row["id"]]]
    remaining = [row["id"] for row in improved["cases"] if not row["passed"]]
    lines.append(f"- 改进后仍未通过：{remaining or '无'}")
    lines.append(f"- 相对基线退化：{regressions or '无'}")
    lines += ["", "## 逐题结果（改进配置）", "", "| ID | 类别 | 通过 | 引用 | 失败层 |", "|---|---|---|---|---|"]
    for row in improved["cases"]:
        lines.append(
            f"| {row['id']} | {row['category']} | {'是' if row['passed'] else '否'} | "
            f"{', '.join(row['citations']) or '—'} | {row['failure_layer'] or '—'} |"
        )
    lines += [
        "", "## 结论边界", "",
        "- 本报告证明检索、证据覆盖、无依据拒答和注入防护可以被重复评测，不证明真实 LLM 的语义生成质量。",
        "- 通过率只对应本项目的 16 条公开虚构案例，不能外推为任何企业系统的整体准确率。",
        "- 接入真实模型时，需要重新固定模型、Prompt、参数和数据版本，并保留原始输出。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    documents = load_json("documents.json")
    cases = load_json("eval_cases.json")
    if len(cases) < 16 or {c["category"] for c in cases} != {"direct", "multi_doc", "refusal", "injection"}:
        raise SystemExit("case coverage requirement failed")
    baseline = execute(documents, cases, BASELINE)
    improved = execute(documents, cases, IMPROVED)
    payload = {"dataset_version": "public-synthetic-v1", "baseline": baseline, "improved": improved}
    (ROOT / "web").mkdir(parents=True, exist_ok=True)
    (ROOT / "web" / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "REPORT.md").write_text(markdown_report(baseline, improved), encoding="utf-8")
    print(json.dumps({
        "baseline": baseline["summary"], "improved": improved["summary"],
        "results": str(ROOT / "web" / "results.json"), "report": str(ROOT / "REPORT.md"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
