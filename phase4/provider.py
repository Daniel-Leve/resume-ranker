"""
Explanation Providers: Abstract Base Interface and Deterministic Implementation.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set

from phase4.config import (
    AUDIT_LIMITATIONS,
    EXPLANATION_VERSION,
    MAX_EVIDENCE_PER_REQ,
    MAX_EXCERPT_CHARS,
)
from phase4.models import (
    CandidateExplanation,
    JobRequirement,
    RequirementAlignment,
    SupportingEvidence,
)


class BaseExplanationProvider(ABC):
    """Abstract interface for Phase 4 explanation generation."""

    @abstractmethod
    def generate_candidate_explanation(
        self,
        candidate_data: Dict[str, Any],
        candidate_chunks: List[Dict[str, Any]],
        requirements: List[JobRequirement],
    ) -> CandidateExplanation:
        """
        Generate an evidence-grounded explanation for a candidate.

        Args:
            candidate_data: Candidate metadata from Phase 3 (including rerank_rank, rerank_score, phase2).
            candidate_chunks: Chunks belonging to this candidate retrieved from MongoDB or payload.
            requirements: Structured job requirements from Phase 4 parser.

        Returns:
            CandidateExplanation model.
        """
        pass


class DeterministicExplanationProvider(BaseExplanationProvider):
    """
    Deterministic evidence-grounded explanation generator.
    Maps job requirements strictly to retrieved resume chunks without hallucination.
    """

    def __init__(
        self,
        max_excerpt_chars: int = MAX_EXCERPT_CHARS,
        max_evidence_per_req: int = MAX_EVIDENCE_PER_REQ,
    ) -> None:
        self.max_excerpt_chars = max_excerpt_chars
        self.max_evidence_per_req = max_evidence_per_req

    def _extract_excerpt(self, text: str, match_keyword: str) -> str:
        """Extract a clean, readable excerpt around the matched keyword."""
        clean_text = " ".join(text.split())
        if not match_keyword:
            return clean_text[:self.max_excerpt_chars] + ("..." if len(clean_text) > self.max_excerpt_chars else "")

        # Find position of keyword
        pattern = re.compile(re.escape(match_keyword), re.IGNORECASE)
        match = pattern.search(clean_text)
        if not match:
            return clean_text[:self.max_excerpt_chars] + ("..." if len(clean_text) > self.max_excerpt_chars else "")

        start_pos = match.start()
        half_window = self.max_excerpt_chars // 2

        excerpt_start = max(0, start_pos - half_window)
        excerpt_end = min(len(clean_text), start_pos + half_window)

        # Snap to word boundaries if possible
        if excerpt_start > 0:
            space_idx = clean_text.find(" ", excerpt_start)
            if space_idx != -1 and space_idx < start_pos:
                excerpt_start = space_idx + 1

        if excerpt_end < len(clean_text):
            space_idx = clean_text.rfind(" ", start_pos, excerpt_end)
            if space_idx != -1:
                excerpt_end = space_idx

        snippet = clean_text[excerpt_start:excerpt_end].strip()
        prefix = "..." if excerpt_start > 0 else ""
        suffix = "..." if excerpt_end < len(clean_text) else ""
        return f"{prefix}{snippet}{suffix}"

    def generate_candidate_explanation(
        self,
        candidate_data: Dict[str, Any],
        candidate_chunks: List[Dict[str, Any]],
        requirements: List[JobRequirement],
    ) -> CandidateExplanation:
        candidate_id = candidate_data.get("candidate_id", "unknown")
        rerank_rank = candidate_data.get("rerank_rank", 0)
        rerank_score = candidate_data.get("rerank_score")
        application_id = candidate_data.get("application_id")
        candidate_name = candidate_data.get("candidate_name")

        # Extract sections from candidate chunks and Phase 2 provenance
        sections_found: Set[str] = set()
        for ch in candidate_chunks:
            sec = ch.get("section")
            if sec:
                sections_found.add(str(sec).lower())

        phase2_provenance = candidate_data.get("phase2") or {}
        for mc in phase2_provenance.get("matched_chunks", []):
            if isinstance(mc, dict) and mc.get("section"):
                sections_found.add(str(mc["section"]).lower())

        sorted_sections = sorted(sections_found)
        title_cased_sections = [s.title() for s in sorted_sections]

        # In case no chunks were provided
        if not candidate_chunks:
            limitations = list(AUDIT_LIMITATIONS) + [
                "No chunk texts were available for this candidate; requirement alignment could not be verified."
            ]
            summary = (
                f"Ranked #{rerank_rank} by semantic reranking. No retrieved resume chunks "
                f"were available to evaluate requirement alignment."
            )
            gaps = [
                f"Requirement '{req.text}' was not established (no retrieved chunk content available)."
                for req in requirements
            ]
            req_alignments = [
                RequirementAlignment(
                    requirement=req.text,
                    category=req.category,
                    status="not_established",
                    rationale="No candidate resume chunks were found to verify this requirement.",
                )
                for req in requirements
            ]
            return CandidateExplanation(
                candidate_id=candidate_id,
                application_id=application_id,
                candidate_name=candidate_name,
                rerank_rank=rerank_rank,
                rerank_score=rerank_score,
                summary=summary,
                matched_sections=sorted_sections,
                supporting_evidence=[],
                requirement_alignment=req_alignments,
                evidence_gaps=gaps,
                limitations=limitations,
                explanation_version=EXPLANATION_VERSION,
            )

        # Match requirements against chunks
        supporting_evidence_list: List[SupportingEvidence] = []
        requirement_alignments: List[RequirementAlignment] = []
        evidence_gaps: List[str] = []
        seen_evidence_hashes: Set[str] = set()

        for req in requirements:
            matched_chunks_for_req: List[str] = []
            excerpts_for_req: List[str] = []
            matched_kws_for_req: List[str] = []

            for chunk in candidate_chunks:
                chunk_id = chunk.get("chunk_id", "unknown")
                chunk_text = chunk.get("text", "")
                section = chunk.get("section", "general")

                if not chunk_text:
                    continue

                # Test keywords
                for kw in req.keywords:
                    # Boundary check for keywords
                    kw_clean = kw.strip()
                    if not kw_clean:
                        continue
                    pattern = re.compile(r"\b" + re.escape(kw_clean) + r"\b", re.IGNORECASE)
                    if pattern.search(chunk_text):
                        if chunk_id not in matched_chunks_for_req:
                            matched_chunks_for_req.append(chunk_id)
                            matched_kws_for_req.append(kw_clean)

                            excerpt = self._extract_excerpt(chunk_text, kw_clean)
                            excerpts_for_req.append(excerpt)

                            evidence_item = SupportingEvidence(
                                chunk_id=chunk_id,
                                section=section,
                                excerpt=excerpt,
                                relevance_keyword=kw_clean,
                            )
                            if evidence_item.content_hash not in seen_evidence_hashes:
                                seen_evidence_hashes.add(evidence_item.content_hash)
                                supporting_evidence_list.append(evidence_item)

                        if len(matched_chunks_for_req) >= self.max_evidence_per_req:
                            break

                if len(matched_chunks_for_req) >= self.max_evidence_per_req:
                    break

            if matched_chunks_for_req:
                kw_summary = ", ".join(dict.fromkeys(matched_kws_for_req))
                rationale = (
                    f"Supported by candidate's resume content with relevant evidence "
                    f"for ({kw_summary}) in chunk(s) {', '.join(matched_chunks_for_req)}."
                )
                requirement_alignments.append(
                    RequirementAlignment(
                        requirement=req.text,
                        category=req.category,
                        status="supported",
                        supporting_chunks=matched_chunks_for_req,
                        evidence_excerpts=excerpts_for_req,
                        rationale=rationale,
                    )
                )
            else:
                rationale = (
                    "Direct evidence for this requirement was not established in the candidate's "
                    "retrieved resume chunks."
                )
                requirement_alignments.append(
                    RequirementAlignment(
                        requirement=req.text,
                        category=req.category,
                        status="not_established",
                        rationale=rationale,
                    )
                )
                evidence_gaps.append(
                    f"Requirement '{req.text}' was not established by the retrieved resume evidence "
                    f"(indicates absence of evidence in retrieved chunks, not necessarily absence of qualification)."
                )

        # Generate human-friendly summary
        sections_str = ", ".join(title_cased_sections) if title_cased_sections else "relevant"
        supported_count = sum(1 for r in requirement_alignments if r.status == "supported")

        if supported_count > 0:
            summary = (
                f"Ranked #{rerank_rank} by semantic reranking. The retrieved resume evidence includes "
                f"relevant experience and skills aligned with the job requirements, with supporting content "
                f"found in the {sections_str} section(s)."
            )
        else:
            summary = (
                f"Ranked #{rerank_rank} by semantic reranking. The candidate's resume was retrieved in "
                f"the {sections_str} section(s), but direct keyword evidence for specific listed requirements "
                f"was not established in the evaluated chunks."
            )

        limitations = list(AUDIT_LIMITATIONS)

        return CandidateExplanation(
            candidate_id=candidate_id,
            application_id=application_id,
            candidate_name=candidate_name,
            rerank_rank=rerank_rank,
            rerank_score=rerank_score,
            summary=summary,
            matched_sections=sorted_sections,
            supporting_evidence=supporting_evidence_list,
            requirement_alignment=requirement_alignments,
            evidence_gaps=evidence_gaps,
            limitations=limitations,
            explanation_version=EXPLANATION_VERSION,
        )
