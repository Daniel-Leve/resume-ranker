import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Users, Search, ChevronRight, Trophy, Filter } from "lucide-react";
import { useJob } from "@/hooks/useJobs";
import { useCandidates } from "@/hooks/useCandidates";
import { useScreeningStatus, useRunScreening } from "@/hooks/useScreening";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { ScreeningControls } from "@/components/recruiter/ScreeningControls";
import { useToast } from "@/components/ui/use-toast";

export const CandidatesPage: React.FC = () => {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const { data: job } = useJob(jobId);
  const { data: candidates = [], isLoading, refetch } = useCandidates(jobId);
  const [shortlistCount, setShortlistCount] = useState<number>(5);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterDecision, setFilterDecision] = useState<string>("ALL");

  const runScreeningMutation = useRunScreening(jobId);
  const { data: screeningStatus } = useScreeningStatus(jobId, runScreeningMutation.isPending);

  const isScreeningInProgress =
    runScreeningMutation.isPending ||
    screeningStatus?.status === "IN_PROGRESS" ||
    screeningStatus?.phase3_status === "RUNNING" ||
    screeningStatus?.phase4_status === "RUNNING";

  const handleRunScreening = async () => {
    try {
      await runScreeningMutation.mutateAsync(shortlistCount);
      toast({
        title: "Screening Initiated",
        description: `Running AI screening for top ${shortlistCount} candidate(s).`,
        variant: "success",
      });
      refetch();
    } catch (err: any) {
      toast({
        title: "Screening Failed",
        description: err.message || "Failed to trigger screening execution.",
        variant: "destructive",
      });
    }
  };

  const filteredCandidates = candidates.filter((c) => {
    const matchesSearch =
      c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.candidate_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.email?.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesFilter = filterDecision === "ALL" || c.decision === filterDecision;
    return matchesSearch && matchesFilter;
  });

  const getDecisionBadge = (decision: string) => {
    switch (decision) {
      case "SHORTLISTED":
        return <Badge variant="success">SHORTLISTED</Badge>;
      case "NEEDS_REVIEW":
        return <Badge variant="warning">NEEDS REVIEW</Badge>;
      case "REJECTED":
        return <Badge variant="danger">REJECTED</Badge>;
      default:
        return <Badge variant="outline">UNDECIDED</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/jobs/${jobId}`)}
          className="gap-1.5 -ml-2 text-muted-foreground hover:text-foreground h-8 mb-1"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Job Overview
        </Button>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
          Candidates Leaderboard
        </h1>
        <p className="text-sm text-muted-foreground">
          {job?.title || "Role Requisition"} • AI ranked and scored applicants
        </p>
      </div>

      <ScreeningControls
        shortlistCount={shortlistCount}
        setShortlistCount={setShortlistCount}
        onRunScreening={handleRunScreening}
        isScreeningInProgress={isScreeningInProgress}
        screeningStatus={screeningStatus}
      />

      <Card className="shadow-sm">
        <CardHeader className="p-4 sm:p-6 pb-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="relative w-full sm:w-72">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search candidates..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 h-9"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <select
                aria-label="Filter candidates by decision status"
                value={filterDecision}
                onChange={(e) => setFilterDecision(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 py-1 text-xs"
              >
                <option value="ALL">All Decisions</option>
                <option value="SHORTLISTED">Shortlisted</option>
                <option value="NEEDS_REVIEW">Needs Review</option>
                <option value="REJECTED">Rejected</option>
                <option value="UNDECIDED">Undecided</option>
              </select>
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0 sm:p-6 sm:pt-0">
          {isLoading ? (
            <LoadingSpinner text="Fetching applicant leaderboard..." />
          ) : filteredCandidates.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<Users className="h-6 w-6" />}
                title={searchQuery ? "No matching applicants" : "No candidates found"}
                description={
                  searchQuery
                    ? "Try adjusting search or status filters"
                    : "No applicants have submitted resumes for this job yet. Share the candidate portal link to begin."
                }
              />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16 text-center">Rank</TableHead>
                  <TableHead>Candidate</TableHead>
                  <TableHead className="w-48">AI Match Score</TableHead>
                  <TableHead>Decision</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredCandidates.map((candidate, idx) => {
                  const rank = candidate.rank || idx + 1;
                  const score = Math.round(candidate.score || 0);

                  return (
                    <TableRow
                      key={candidate.candidate_id}
                      onClick={() => navigate(`/jobs/${jobId}/candidates/${candidate.candidate_id}`)}
                      className="cursor-pointer hover:bg-muted/60 transition-colors"
                    >
                      <TableCell className="text-center font-bold">
                        {rank <= 3 ? (
                          <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-amber-100 text-amber-800 text-xs">
                            <Trophy className="h-3.5 w-3.5 text-amber-600" />
                          </span>
                        ) : (
                          <span className="text-muted-foreground text-xs">#{rank}</span>
                        )}
                      </TableCell>

                      <TableCell>
                        <div className="font-semibold text-foreground hover:text-blue-600 transition-colors">
                          {candidate.name}
                        </div>
                        <div className="text-xs text-muted-foreground font-mono">
                          ID: {candidate.candidate_id.substring(0, 8)}...
                        </div>
                      </TableCell>

                      <TableCell>
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-xs font-semibold">
                            <span>{score}%</span>
                          </div>
                          <Progress
                            value={score}
                            indicatorClassName={
                              score >= 80 ? "bg-emerald-600" : score >= 60 ? "bg-amber-500" : "bg-rose-500"
                            }
                          />
                        </div>
                      </TableCell>

                      <TableCell>{getDecisionBadge(candidate.decision)}</TableCell>

                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="gap-1 text-xs hover:text-blue-600"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/jobs/${jobId}/candidates/${candidate.candidate_id}`);
                          }}
                        >
                          View Report
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
