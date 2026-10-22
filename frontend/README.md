# RecruitAI — AI Resume Screening & Candidate Matching Frontend

A modern, production-grade React SaaS frontend for autonomous AI resume screening, rubric calibration, candidate leaderboard scoring, and transparent applicant feedback.

Built with **Vite**, **React 19**, **TypeScript**, **Tailwind CSS**, and custom **shadcn/ui** components.

---

## Features

### Recruiter Workspace (Protected)
- **Dashboard (`/dashboard`)**: Key hiring metrics (Total Jobs, Applications, Review Queue, LLM Usage), recent positions table, and rapid workflow actions.
- **Jobs Directory (`/jobs`)**: Filterable overview of all requisition pipelines, rubric approval badges, and live candidate count.
- **New Requisition (`/jobs/new`)**: Markdown-enabled job posting creator connected to backend rubric extraction.
- **Job Overview & Rubric (`/jobs/:jobId`)**: Detailed job information with 1-click candidate application portal link generator and full AI rubric calibration & approval controls.
- **Candidate Leaderboard (`/jobs/:jobId/candidates`)**: Real-time ranked candidate list with match scores, Phase 3 & 4 AI screening execution trigger, and automated 5s status polling.
- **Deep-Dive Assessment (`/jobs/:jobId/candidates/:candidateId`)**: Comprehensive HR evaluation report including criteria breakdown with extracted evidence quotes, key strengths, gaps, risk factors, and custom interview questions.
- **Review Queue (`/jobs/:jobId/review-queue`)**: Focus-mode triage cards for borderline candidate edge cases with one-click "Promote to Shortlist" or "Confirm Rejection" and reviewer justification notes.
- **Settings (`/settings`)**: Recruiter account info, tenant partition details, and team member invitation module.

### Candidate Portal (Public)
- **Application Portal (`/apply/:jobId`)**: Clean job specification with drag-and-drop PDF resume uploader. Automatically provisions encrypted S3 uploads and generates unique candidate access tokens.
- **Pipeline Stepper (`/track`)**: 4-phase tracking stepper (S3 Upload → Phase 1 Extraction → Phase 2 Indexing → Phase 3/4 Screening) with 5-second automatic polling.
- **Transparent Feedback Portal (`/feedback`)**: Real-time evaluation results:
  - **Pending (409)**: Animated verification state while queued for reviewer sign-off.
  - **Shortlisted**: Next-steps celebration banner and key highlighted qualifications.
  - **Not Moving Forward**: Empathetic, actionable breakdown displaying resume highlights, areas for enhancement, and constructive suggestions.

---

## Environment Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Ensure the following variables are defined in `.env`:
```env
VITE_API_URL=https://vxbiq8rt27.execute-api.ap-south-1.amazonaws.com/dev
VITE_COGNITO_REGION=ap-south-1
VITE_COGNITO_USER_POOL_ID=ap-south-1_0jQ33OKwk
VITE_COGNITO_CLIENT_ID=7cu49634tijn7m70lhekvhuknj
```

---

## Getting Started

### 1. Install Dependencies
Run the following in `d:/ResumeProjCodex/frontend`:
```bash
npm install
```

### 2. Start Development Server
```bash
npm run dev
```

The application will be accessible at:
```
http://localhost:5173
```

### 3. Build for Production
```bash
npm run build
```

This compiles TypeScript and builds an optimized production distribution in `dist/`.
