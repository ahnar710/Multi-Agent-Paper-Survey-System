"""Code-owned acceptance rules applied after agent verification."""

from __future__ import annotations

from paper_agents.schemas import (
    DocumentAccess,
    QualityGateResult,
    ResearchCard,
    VerificationReport,
    VerificationStatus,
)


class QualityGate:
    def __init__(self, *, minimum_quality_score: int = 3) -> None:
        if not 0 <= minimum_quality_score <= 5:
            raise ValueError("minimum_quality_score 必须在 0 到 5 之间")
        self.minimum_quality_score = minimum_quality_score

    def evaluate(
        self, card: ResearchCard, report: VerificationReport
    ) -> QualityGateResult:
        reasons: list[str] = []
        if card.paper.paper_id != report.paper_id:
            reasons.append("研究卡片与核验报告 paper_id 不一致")
        if card.verification_status != VerificationStatus.PASSED:
            reasons.append("研究卡片未通过 Verifier")
        if report.status != VerificationStatus.PASSED:
            reasons.append("核验报告状态不是 passed")
        if card.quality_score < self.minimum_quality_score:
            reasons.append(
                f"质量评分 {card.quality_score} 低于阈值 {self.minimum_quality_score}"
            )
        if not card.evidence:
            reasons.append("研究卡片没有证据")
        if len(report.items) != len(card.evidence):
            reasons.append("核验项数与证据数不一致")

        accepted = not reasons
        full_text = card.paper.document_access == DocumentAccess.FULL_TEXT
        if accepted and not full_text:
            reasons.append("仅摘要级验证，不计入全文研读产量")
        return QualityGateResult(
            accepted=accepted,
            counts_toward_full_text_target=accepted and full_text,
            reasons=reasons,
        )
