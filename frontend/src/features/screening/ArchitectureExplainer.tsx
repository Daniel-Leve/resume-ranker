import React from 'react';
import { Layers, Database, Cpu, ArrowRight } from 'lucide-react';

export function ArchitectureExplainer() {
  return (
    <div className="card" style={{ marginTop: '1.5rem', backgroundColor: 'var(--bg-app)' }}>
      <div className="card-label" style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Layers size={14} style={{ color: 'var(--accent-primary)' }} />
        Two-Stage Retrieval & Reranking Architecture
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '1rem', alignItems: 'center' }}>
        {/* Stage 1 */}
        <div style={{ background: 'var(--bg-card)', padding: '0.85rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#a5b4fc', marginBottom: '0.25rem' }}>
            Stage 1: Hybrid Candidate Retrieval
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            BM25 Lexical (MongoDB Atlas Search) + Voyage AI Vector Search (1024-dim) combined via <strong>Reciprocal Rank Fusion (k=60)</strong> to extract candidate pool.
          </div>
        </div>

        <ArrowRight size={18} style={{ color: 'var(--text-dim)' }} />

        {/* Stage 2 */}
        <div style={{ background: 'var(--bg-card)', padding: '0.85rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#34d399', marginBottom: '0.25rem' }}>
            Stage 2: Cross-Encoder Semantic Reranking
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Candidate documents reconstructed from MongoDB chunks and evaluated jointly with Job Description using <strong>Voyage rerank-2.5</strong> for final relevance scoring.
          </div>
        </div>
      </div>
    </div>
  );
}
