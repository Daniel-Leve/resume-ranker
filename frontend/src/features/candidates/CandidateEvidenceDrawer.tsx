import React, { useState } from 'react';
import { X, Award, Layers, ChevronDown, ChevronRight, FileText, CheckCircle2 } from 'lucide-react';
import { CandidateRanking } from '../../types';
import { formatCandidateName, formatCandidateId, formatS3Key } from '../../utils/formatters';

interface CandidateEvidenceDrawerProps {
  candidate: CandidateRanking | null;
  onClose: () => void;
}

export function CandidateEvidenceDrawer({ candidate, onClose }: CandidateEvidenceDrawerProps) {
  const [showTechDetails, setShowTechDetails] = useState(false);

  if (!candidate) return null;

  const name = formatCandidateName(candidate.candidate_name, candidate.candidate_id);
  const displayId = formatCandidateId(candidate.candidate_id);
  const scorePct = (candidate.rerank_score * 100).toFixed(1);
  const p2 = candidate.phase2 || { hybrid_score: 0, matched_chunks: [] };
  const matchedChunks = p2.matched_chunks || [];
  const docChunks = candidate.document_chunks || [];

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
        {/* Drawer Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-color)' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
              <span className="status-badge badge-emerald">#{candidate.rerank_rank} Candidate Rank</span>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Semantic Fit: <strong>{scorePct}%</strong></span>
            </div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>{name}</h2>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }} title={candidate.candidate_id}>
              Candidate ID: {displayId}
            </div>
          </div>

          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Section 1: Final Score Overview */}
        <div className="card" style={{ marginBottom: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div className="card-label">Final Semantic Match Score</div>
              <div className="card-value" style={{ color: 'var(--accent-emerald)' }}>{scorePct}%</div>
            </div>
            <div>
              <div className="card-label">Rank Shift</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: candidate.rank_change > 0 ? 'var(--accent-emerald)' : 'var(--text-muted)' }}>
                {candidate.rank_change > 0 ? `+${candidate.rank_change} positions` : `${candidate.rank_change} positions`}
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: Resume Evidence & Matched Sections */}
        <div style={{ marginBottom: '1.25rem' }}>
          <h4 style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Layers size={16} style={{ color: 'var(--accent-primary)' }} />
            Matched Section Evidence ({matchedChunks.length})
          </h4>

          {matchedChunks.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '1rem' }}>
              {matchedChunks.map((mc, idx) => (
                <span key={idx} className="status-badge badge-indigo">
                  <CheckCircle2 size={12} /> Section: {mc.section}
                </span>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
              Candidate matched across entire reconstructed resume profile.
            </div>
          )}

          {/* Reconstructed Document Chunks */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {docChunks.map((chunk, idx) => (
              <div key={idx} style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '0.85rem' }}>
                <pre style={{ fontSize: '0.8rem', color: 'var(--text-muted)', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-sans)' }}>
                  {chunk}
                </pre>
              </div>
            ))}
          </div>
        </div>

        {/* Section 3: Expandable Technical Ranking Details */}
        <div className="card" style={{ marginTop: 'auto' }}>
          <div
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
            onClick={() => setShowTechDetails(!showTechDetails)}
          >
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-muted)' }}>
              Technical Ranking Provenance Details
            </span>
            {showTechDetails ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </div>

          {showTechDetails && (
            <div style={{ marginTop: '0.85rem', paddingTop: '0.85rem', borderTop: '1px solid var(--border-color)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.8rem' }}>
              <div>
                <span style={{ color: 'var(--text-dim)' }}>Semantic Rerank Score:</span>
                <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{candidate.rerank_score.toFixed(6)}</div>
              </div>

              <div>
                <span style={{ color: 'var(--text-dim)' }}>Hybrid RRF Score:</span>
                <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{(p2.hybrid_score || 0).toFixed(6)}</div>
              </div>

              <div>
                <span style={{ color: 'var(--text-dim)' }}>Phase 2 Lexical BM25 Rank:</span>
                <div style={{ fontWeight: 600 }}>{p2.lexical_rank ? `#${p2.lexical_rank}` : 'Unmatched'}</div>
              </div>

              <div>
                <span style={{ color: 'var(--text-dim)' }}>Phase 2 Vector Rank:</span>
                <div style={{ fontWeight: 600 }}>{p2.vector_rank ? `#${p2.vector_rank}` : 'Unmatched'}</div>
              </div>

              <div style={{ gridColumn: 'span 2' }}>
                <span style={{ color: 'var(--text-dim)' }}>S3 Extraction Key:</span>
                <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: '0.75rem', wordBreak: 'break-all' }} title={candidate.source_key}>
                  {formatS3Key(candidate.source_key)}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
