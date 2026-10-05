import { Job, CandidateRanking, ScreeningRun, Application } from '../types';

export const MOCK_TENANT = {
  tenant_id: "tenant-acme-corp",
  name: "Acme Enterprise Corp",
  status: "ACTIVE"
};

export const MOCK_JOBS: Job[] = [
  {
    job_id: "d4fd3816-f2c3-450a-a8dc-788231b667e3",
    tenant_id: "tenant-acme-corp",
    title: "Senior AI & Backend Software Engineer",
    department: "AI Research & Platform",
    location: "Remote / Hybrid",
    description: "Seeking a Senior Backend Engineer to build serverless Python microservices, Amazon Textract OCR document processing, Voyage AI vector search and reranking models on MongoDB Atlas.",
    status: "OPEN",
    application_count: 3,
    created_at: new Date(Date.now() - 86400000).toISOString(),
    recruiter_email: "recruiter@acme.com"
  },
  {
    job_id: "619b93c8-5eac-42b7-aa9d-417a95a9f550",
    tenant_id: "tenant-acme-corp",
    title: "Senior Backend Engineer (Python / AWS)",
    department: "Engineering",
    location: "Remote / Hybrid",
    description: "We are seeking a Senior Backend Engineer with 4+ years of experience building scalable RESTful APIs in Python, AWS Lambda, DynamoDB, S3, and MongoDB. Deep understanding of microservices, event-driven architectures, and AI vector search integrations (Voyage AI, Atlas Vector Search) is required.",
    status: "OPEN",
    application_count: 3,
    created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
    recruiter_email: "recruiter@acme.com"
  },
  {
    job_id: "python-data-engineer-001",
    tenant_id: "tenant-acme-corp",
    title: "Lead Data & AI Pipeline Engineer",
    department: "Data Platform",
    location: "San Francisco, CA",
    description: "Looking for a Data Engineer to design high-throughput ETL pipelines, PySpark data processing, and automated ingestion workflows for unstructured PDF data and embedding generation.",
    status: "OPEN",
    application_count: 2,
    created_at: new Date(Date.now() - 86400000 * 5).toISOString(),
    recruiter_email: "recruiter@acme.com"
  },
  {
    job_id: "frontend-react-engineer-002",
    tenant_id: "tenant-acme-corp",
    title: "Senior Full-Stack React Engineer",
    department: "Product Development",
    location: "New York, NY",
    description: "Join our core product team to build high-performance React web applications with modern state management, real-time web sockets, and responsive design systems.",
    status: "OPEN",
    application_count: 1,
    created_at: new Date(Date.now() - 86400000 * 7).toISOString(),
    recruiter_email: "recruiter@acme.com"
  }
];

export const MOCK_APPLICATIONS: Application[] = [
  {
    application_id: "app-daniel-leve",
    job_id: "619b93c8-5eac-42b7-aa9d-417a95a9f550",
    tenant_id: "tenant-acme-corp",
    candidate_name: "Daniel Leve",
    s3_resume_key: "incoming/daniel-leve.pdf",
    status: "INDEXED",
    created_at: new Date(Date.now() - 86400000 * 1).toISOString()
  },
  {
    application_id: "app-alex-chen",
    job_id: "619b93c8-5eac-42b7-aa9d-417a95a9f550",
    tenant_id: "tenant-acme-corp",
    candidate_name: "Alex Chen",
    s3_resume_key: "incoming/alex-chen.pdf",
    status: "INDEXED",
    created_at: new Date(Date.now() - 86400000 * 2).toISOString()
  },
  {
    application_id: "app-sara-smith",
    job_id: "619b93c8-5eac-42b7-aa9d-417a95a9f550",
    tenant_id: "tenant-acme-corp",
    candidate_name: "Sara Smith",
    s3_resume_key: "incoming/sara-smith.pdf",
    status: "INDEXED",
    created_at: new Date(Date.now() - 86400000 * 3).toISOString()
  }
];

export const MOCK_CANDIDATE_RANKINGS: CandidateRanking[] = [
  {
    candidate_id: "daniel-leve",
    candidate_name: "Daniel Leve",
    rerank_rank: 1,
    rerank_score: 0.96524,
    rank_change: 2,
    phase2: {
      hybrid_score: 0.032258,
      lexical_rank: 1,
      vector_rank: 3,
      matched_chunks: [
        { chunk_id: "daniel-leve_experience_00", section: "experience" },
        { chunk_id: "daniel-leve_skills_00", section: "skills" },
        { chunk_id: "daniel-leve_education_00", section: "education" }
      ]
    },
    source_key: "extracted/daniel-leve.json",
    document_chunks: [
      "[SUMMARY]\nSenior Backend Engineer with extensive experience building cloud-native microservices on AWS, REST APIs, and MongoDB Atlas Vector Search.",
      "[EXPERIENCE]\nSenior Software Engineer - Acme Systems\n• Designed serverless pipelines handling 50k requests/sec using AWS Lambda & DynamoDB.\n• Built Voyage AI & MongoDB Atlas hybrid search retrieval system.",
      "[SKILLS]\nPython, Java, AWS (Lambda, S3, SQS, SAM), MongoDB, Docker, REST APIs, Voyage AI Rerank.",
      "[EDUCATION]\nB.S. in Computer Science & Cloud Systems Engineering."
    ]
  },
  {
    candidate_id: "alex-chen",
    candidate_name: "Alex Chen",
    rerank_rank: 2,
    rerank_score: 0.88412,
    rank_change: -1,
    phase2: {
      hybrid_score: 0.031746,
      lexical_rank: 2,
      vector_rank: 1,
      matched_chunks: [
        { chunk_id: "alex-chen_skills_00", section: "skills" },
        { chunk_id: "alex-chen_education_00", section: "education" }
      ]
    },
    source_key: "extracted/alex-chen.json",
    document_chunks: [
      "[SUMMARY]\nData Platform & API Engineer with strong Python background.",
      "[EXPERIENCE]\nBackend Developer - DataTech Inc.\n• Implemented FastAPI microservices with PostgreSQL and MongoDB Atlas Vector Search.",
      "[SKILLS]\nPython, FastAPI, AWS, Docker, Vector Embeddings, PostgreSQL."
    ]
  },
  {
    candidate_id: "sara-smith",
    candidate_name: "Sara Smith",
    rerank_rank: 3,
    rerank_score: 0.74109,
    rank_change: -1,
    phase2: {
      hybrid_score: 0.028571,
      lexical_rank: 4,
      vector_rank: 2,
      matched_chunks: [
        { chunk_id: "sara-smith_experience_00", section: "experience" }
      ]
    },
    source_key: "extracted/sara-smith.json",
    document_chunks: [
      "[SUMMARY]\nFull Stack Engineer proficient in Python, React, and AWS Cloud architecture.",
      "[EXPERIENCE]\nSoftware Engineer - CloudScale Solutions\n• Developed web dashboards connected to AWS serverless backend.",
      "[SKILLS]\nPython, React.js, AWS S3, Node.js, SQL."
    ]
  }
];

export const MOCK_SCREENING_RUN: ScreeningRun = {
  screening_run_id: "run-98421",
  tenant_id: "tenant-acme-corp",
  job_id: "619b93c8-5eac-42b7-aa9d-417a95a9f550",
  status: "COMPLETED",
  phase2_status: "COMPLETED",
  phase3_status: "COMPLETED",
  candidates: MOCK_CANDIDATE_RANKINGS,
  candidate_count: 3,
  processing_time_sec: 2.14,
  created_at: new Date(Date.now() - 3600000).toISOString(),
  completed_at: new Date(Date.now() - 3590000).toISOString()
};
