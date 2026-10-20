"""The paragraph shown to Sarra.

1. A TEMPLATE summary is always built: deterministic, every number from the checks.
2. If an LLM is available, it rewrites it for a non-technical manager. The prompt is
   prompts/comparison_summary.yaml (edit it there, never here).
3. The LLM text is CHECKED before use:
   - fidelity: every number it contains must exist in the evidence (no invented figure);
   - completeness: every proposed adjustment must appear with its values (no hidden option).
   If either fails, the template is kept. Known limit: a wrong claim made in WORDS,
   without a number, is not detected; the app therefore always offers the template too.
Both outcomes are written to the audit journal.
"""
import json

from pydantic import BaseModel, Field

from contracts.factcheck import NUMBER as _NUMBER, allowed_numbers, unsupported_numbers  # noqa: F401
from contracts.comparisons import CheckStatus, ComparisonCheck, ProposedFix
from contracts.llm import LLMConfig, LLMUnavailable, chat_json
from contracts.prompts import load_prompt
from contracts.semantic import AnalysisRequest

PROMPT_NAME = "comparison_summary"


def _money(v: float | None, unit: str | None) -> str:
    return "n/a" if v is None else f"{v:,.2f} {unit or ''}".strip()


def _chg(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def template_summary(req: AnalysisRequest, checks: list[ComparisonCheck], as_asked: tuple[float, float],
                     unit: str, rec: ProposedFix | None, alts: list[ProposedFix]) -> str:
    v_cur, v_prev = as_asked
    change = _chg(v_cur / v_prev - 1 if v_prev else None)
    asked = (f"{req.metric} {req.period.start}..{req.period.end} = {_money(v_cur, unit)} against "
             f"{req.compare_to.start}..{req.compare_to.end} = {_money(v_prev, unit)} ({change})")
    problems = [c for c in checks if c.status != CheckStatus.OK]
    if not problems:
        return f"The comparison is valid: {asked}. " + " ".join(c.message for c in checks)

    blocking = any(c.status == CheckStatus.BLOCKING for c in checks)
    lines = [f"{'Careful: this comparison is misleading as asked' if blocking else 'Note'}: {asked}."]
    lines += [c.message for c in problems]
    if rec:
        lines.append(f"Recommended: {rec.description} Result: {_money(rec.value_current, rec.unit)} "
                     f"against {_money(rec.value_previous, rec.unit)} ({_chg(rec.change_pct)}). "
                     f"Why: {rec.justification}")
    for a in alts:
        lines.append(f"Alternative: {a.description} Result: {_money(a.value_current, a.unit)} "
                     f"against {_money(a.value_previous, a.unit)} ({_chg(a.change_pct)}). "
                     f"Why: {a.justification}")
    if blocking and not rec:
        lines.append("No honest adjustment exists with this data: the comparison should not be shown.")
    if rec or alts:
        lines.append("Nothing is changed until you choose.")
    return " ".join(lines)


# ---- LLM rewrite + fact check -------------------------------------------------------
class SummaryOut(BaseModel):
    summary: str = Field(description="The rewritten paragraph for the manager.")


def missing_required(text: str, fixes: list[ProposedFix]) -> list[float]:
    """Completeness: every value of every proposed adjustment must be in the text."""
    found = {float(n.replace(",", "")) for n in _NUMBER.findall(text)}
    required = [v for f in fixes for v in (f.value_current, f.value_previous) if v is not None]
    return [v for v in required if not any(abs(v - x) < 0.005 for x in found)]


def llm_facts(template: str, checks: list[ComparisonCheck], fixes: list[ProposedFix]) -> str:
    """What the LLM sees: only the problems, and values ALREADY FORMATTED for a reader
    (the model copies them; it never formats or computes a number itself)."""
    problems = [{"issue": c.kind.value, "severity": c.status.value, "message": c.message}
                for c in checks if c.status != CheckStatus.OK]
    adjustments = [{"role": "recommended" if i == 0 else "alternative",
                    "what": f.description, "why": f.justification,
                    "current": _money(f.value_current, f.unit),
                    "previous": _money(f.value_previous, f.unit),
                    "change": _chg(f.change_pct)} for i, f in enumerate(fixes)]
    return json.dumps({"template_summary": template, "problems": problems,
                       "adjustments": adjustments}, ensure_ascii=False, indent=1)


def summarize(template: str, checks: list[ComparisonCheck], fixes: list[ProposedFix], *,
              ctx=None, use_llm: bool = True, language: str = "French",
              config: LLMConfig | None = None, llm=chat_json) -> tuple[str, str]:
    """Returns (summary, source). source = "template" or "llm:<model>"."""
    if not use_llm:
        return template, "template"
    config = config or LLMConfig()
    prompt = load_prompt(PROMPT_NAME)
    facts = llm_facts(template, checks, fixes)
    try:
        out = llm(prompt.render(language=language), f"FACTS:\n{facts}", SummaryOut,
                  prompt_version=prompt.ref, ctx=ctx, step="comparison_summary", config=config)
    except LLMUnavailable as e:
        if ctx is not None:
            ctx.log("summary_source", "template (LLM unavailable)", evidence={"reason": str(e)})
        return template, "template"
    except Exception as e:            # malformed answer
        if ctx is not None:
            ctx.log("summary_source", "template (LLM answer invalid)", evidence={"reason": str(e)[:300]})
        return template, "template"

    bad = unsupported_numbers(out.summary, allowed_numbers(facts))
    missing = missing_required(out.summary, fixes)
    if bad or missing:
        if ctx is not None:
            ctx.log("summary_fact_check", "REJECTED: template kept", rule_version=prompt.ref,
                    evidence={"unsupported_numbers": bad, "missing_fix_values": missing,
                              "llm_text": out.summary})
        return template, "template"
    if ctx is not None:
        ctx.log("summary_fact_check", "ACCEPTED", rule_version=prompt.ref,
                evidence={"numbers_checked": len(_NUMBER.findall(out.summary))})
    return out.summary, f"llm:{config.model}"
