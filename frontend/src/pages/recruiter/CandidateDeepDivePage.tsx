import React from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  FileText,
  Download,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Award,
} from "lucide-react";
import { useCandidate } from "@/hooks/useCandidates";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { InterviewQuestionsAccordion } from "@/components/recruiter/InterviewQuestionsAccordion";

export const CandidateDeepDivePage: React.FC = () => {
  const { jobId = "", candidateId = "" } = useParams<{ jobId: string; candidateId: string }>();
  const navigate = useNavigate();
  const { data: candidate, isLoading, error } = useCandidate(jobId, candidateId);

  if (isLoading) {
    return <LoadingSpinner text="Generating candidate deep-dive assessment..." />;
  }

  if (error || !candidate) {
    return (
      <div className="text-center py-12">
        <h2 className="text-lg font-bold text-destructive">Failed to load candidate evaluation</h2>
        <p className="text-sm text-muted-foreground mt-1 mb-4">{error?.message || "Candidate record not found"}</p>
        <Button variant="outline" onClick={() => navigate(`/jobs/${jobId}/candidates`)}>
          Back to Candidates
        </Button>
      </div>
    );
  }

  const score = Math.round(candidate.score || 0);

  const getDecisionVariant = (decision: string) => {
    switch (decision) {
      case "SHORTLISTED":
        return { variant: "success" as const, label: "SHORTLISTED", bg: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30" };
      case "NEEDS_REVIEW":
        return { variant: "warning" as const, label: "NEEDS REVIEW", bg: "bg-amber-500/10 text-amber-600 border-amber-500/30" };
      case "REJECTED":
        return { variant: "danger" as const, label: "REJECTED", bg: "bg-rose-500/10 text-rose-600 border-rose-500/30" };
      default:
        return { variant: "outline" as const, label: "UNDECIDED", bg: "bg-muted text-muted-foreground border-border" };
    }
  };

  const decisionInfo = getDecisionVariant(candidate.decision);

  return (
    <div className="space-y-6">
      <div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/jobs/${jobId}/candidates`)}
          className="gap-1.5 -ml-2 text-muted-foreground hover:text-foreground h-8"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Candidate Leaderboard
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Resume & Meta Card (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <Card className="shadow-sm">
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="h-4 w-4 text-blue-600" />
                Resume Document
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="p-4 bg-muted/40 rounded-lg border border-dashed text-center space-y-3">
                <FileText className="h-12 w-12 text-muted-foreground/50 mx-auto" />
                <div>
                  <p className="font-semibold text-sm">{candidate.name}</p>
                  <p className="text-xs text-muted-foreground font-mono mt-0.5 break-all">
                    {candidate.s3_resume_key || `resumes/${candidate.candidate_id}.pdf`}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full gap-2 text-xs"
                  onClick={() => alert(`Download S3 Object: ${candidate.s3_resume_key || 'Resume not found in S3 bucket'}`)}
                >
                  <Download className="h-3.5 w-3.5" />
                  Download Resume
                </Button>
              </div>

              <div className="space-y-2 text-xs text-muted-foreground pt-2">
                <div className="flex justify-between">
                  <span>Candidate ID:</span>
                  <span className="font-mono text-foreground font-medium">{candidate.candidate_id.substring(0, 12)}...</span>
                </div>
                <div className="flex justify-between">
                  <span>Contact:</span>
                  <span className="text-foreground font-medium">{candidate.email || "Confidential"}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right Column: HR Assessment Report (8 cols) */}
        <div className="lg:col-span-8 space-y-6">
          <Card className="shadow-sm border">
            <CardContent className="p-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b">
                <div>
                  <h2 className="text-xl font-bold text-foreground">{candidate.name}</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">Automated Multi-Phase Evaluation</p>
                </div>
                <div className={`px-4 py-2 rounded-lg border font-bold text-sm tracking-wide ${decisionInfo.bg}`}>
                  {decisionInfo.label}
                </div>
              </div>

              <div className="pt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold flex items-center gap-1.5">
                    <Award className="h-4 w-4 text-primary" />
                    Overall Calibrated Score
                  </span>
                  <span className="text-base font-bold text-foreground">{score} / 100</span>
                </div>
                <Progress
                  value={score}
                  indicatorClassName={score >= 80 ? "bg-emerald-600" : score >= 60 ? "bg-amber-500" : "bg-rose-500"}
                  className="h-2.5"
                />
              </div>
            </CardContent>
          </Card>

          {candidate.criteria_breakdown && candidate.criteria_breakdown.length > 0 && (
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Criteria Breakdown</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-1/3">Criterion</TableHead>
                      <TableHead className="w-20 text-center">Score</TableHead>
                      <TableHead>Extracted Evidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {candidate.criteria_breakdown.map((item, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-semibold text-xs text-foreground align-top">
                          {item.criterion}
                        </TableCell>
                        <TableCell className="text-center font-mono font-bold text-xs align-top">
                          <span className={item.score >= 70 ? "text-emerald-600" : "text-amber-600"}>
                            {item.score}%
                          </span>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground italic leading-relaxed align-top">
                          "{item.evidence}"
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="shadow-sm border-emerald-200 dark:border-emerald-900 bg-emerald-50/20 dark:bg-emerald-950/10">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-emerald-800 dark:text-emerald-300 flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-600" />
                  Key Strengths
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-2">
                {(candidate.strengths && candidate.strengths.length > 0) ? (
                  candidate.strengths.map((str, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-foreground">
                      <span className="text-emerald-600 font-bold">•</span>
                      <span>{str}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground">No prominent strengths recorded.</p>
                )}
              </CardContent>
            </Card>

            <Card className="shadow-sm border-rose-200 dark:border-rose-900 bg-rose-50/20 dark:bg-rose-950/10">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-rose-800 dark:text-rose-300 flex items-center gap-2">
                  <XCircle className="h-4 w-4 text-rose-600" />
                  Identified Gaps
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-2">
                {(candidate.gaps && candidate.gaps.length > 0) ? (
                  candidate.gaps.map((gap, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-foreground">
                      <span className="text-rose-600 font-bold">•</span>
                      <span>{gap}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground">No significant gaps detected.</p>
                )}
              </CardContent>
            </Card>
          </div>

          {candidate.risks && candidate.risks.length > 0 && (
            <Card className="border-amber-200 dark:border-amber-900 bg-amber-50/30 dark:bg-amber-950/20 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-amber-800 dark:text-amber-300 flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                  Potential Risks & Flagged Nuances
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-1.5 text-amber-900 dark:text-amber-200">
                {candidate.risks.map((risk, idx) => (
                  <div key={idx} className="flex items-start gap-2">
                    <span className="text-amber-600 font-bold">•</span>
                    <span>{risk}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {candidate.interview_questions && (
            <InterviewQuestionsAccordion questions={candidate.interview_questions} />
          )}
        </div>
      </div>
    </div>
  );
};
