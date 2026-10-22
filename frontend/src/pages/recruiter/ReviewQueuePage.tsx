import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  UserCheck,
  CheckCircle,
  Loader2,
} from "lucide-react";
import { useReviewQueue, usePromoteCandidate, useRejectCandidate } from "@/hooks/useCandidates";
import { useJob } from "@/hooks/useJobs";
import { ReviewQueueItem } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { useToast } from "@/components/ui/use-toast";

export const ReviewQueuePage: React.FC = () => {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const { data: job } = useJob(jobId);
  const { data: queue = [], isLoading, error } = useReviewQueue(jobId);

  const promoteMutation = usePromoteCandidate(jobId);
  const rejectMutation = useRejectCandidate(jobId);

  // Dialog state
  const [selectedCandidate, setSelectedCandidate] = useState<ReviewQueueItem | null>(null);
  const [actionType, setActionType] = useState<"PROMOTE" | "REJECT" | null>(null);
  const [notes, setNotes] = useState("");

  const handleOpenDialog = (candidate: ReviewQueueItem, action: "PROMOTE" | "REJECT") => {
    setSelectedCandidate(candidate);
    setActionType(action);
    setNotes("");
  };

  const handleConfirmAction = async () => {
    if (!selectedCandidate || !actionType) return;

    try {
      if (actionType === "PROMOTE") {
        await promoteMutation.mutateAsync({
          candidateId: selectedCandidate.candidate_id,
          notes: notes.trim(),
        });
        toast({
          title: "Candidate Shortlisted",
          description: `${selectedCandidate.candidate_name} has been added to the shortlist.`,
          variant: "success",
        });
      } else {
        await rejectMutation.mutateAsync({
          candidateId: selectedCandidate.candidate_id,
          notes: notes.trim(),
        });
        toast({
          title: "Rejection Confirmed",
          description: `${selectedCandidate.candidate_name} has been moved to rejected.`,
          variant: "default",
        });
      }
      setSelectedCandidate(null);
      setActionType(null);
    } catch (err: any) {
      toast({
        title: "Action Failed",
        description: err.message || "Failed to update candidate review decision.",
        variant: "destructive",
      });
    }
  };

  const getRiskBadge = (level: string) => {
    switch (level?.toUpperCase()) {
      case "HIGH":
        return <Badge variant="danger">High Risk</Badge>;
      case "MEDIUM":
        return <Badge variant="warning">Medium Risk</Badge>;
      default:
        return <Badge variant="secondary">Low Risk</Badge>;
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
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
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
              Review Queue
            </h1>
            <p className="text-sm text-muted-foreground">
              {job?.title} • Resolve edge cases and borderline AI recommendations
            </p>
          </div>
          <Badge variant="outline" className="w-fit">
            {queue.length} Pending Resolution
          </Badge>
        </div>
      </div>

      {isLoading ? (
        <LoadingSpinner text="Loading review queue..." />
      ) : error ? (
        <Card className="p-6 text-center text-destructive border-destructive/30">
          <p className="text-sm font-medium">Failed to load review queue: {error.message}</p>
        </Card>
      ) : queue.length === 0 ? (
        <EmptyState
          icon={<CheckCircle className="h-8 w-8 text-emerald-500" />}
          title="Review Queue is Clean!"
          description="There are no flagged or undecided candidates pending human review."
          actionLabel="View Candidate Leaderboard"
          onAction={() => navigate(`/jobs/${jobId}/candidates`)}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {queue.map((item) => (
            <Card key={item.candidate_id} className="shadow-sm hover:shadow transition-shadow border">
              <CardContent className="p-5">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  {/* Candidate Info */}
                  <div className="space-y-2 flex-1">
                    <div className="flex items-center gap-3">
                      <h3 className="text-base font-semibold text-foreground">
                        {item.candidate_name}
                      </h3>
                      {getRiskBadge(item.risk_level)}
                      <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded">
                        Score: {Math.round(item.weighted_score || 0)}%
                      </span>
                    </div>

                    <p className="text-xs text-muted-foreground font-mono">
                      ID: {item.candidate_id}
                    </p>

                    {/* Flags */}
                    <div className="space-y-1 pt-1">
                      <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                        Flag Reasons:
                      </p>
                      <ul className="text-xs text-foreground space-y-1 pl-5 list-disc">
                        {item.flag_reasons?.map((flag, idx) => (
                          <li key={idx} className="text-muted-foreground">
                            {flag}
                          </li>
                        )) || <li>Borderline match confidence</li>}
                      </ul>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex sm:flex-row md:flex-col gap-2 shrink-0 justify-end">
                    <Button
                      size="sm"
                      variant="success"
                      onClick={() => handleOpenDialog(item, "PROMOTE")}
                      className="gap-1.5"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Promote to Shortlist
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => handleOpenDialog(item, "REJECT")}
                      className="gap-1.5"
                    >
                      <XCircle className="h-4 w-4" />
                      Confirm Rejection
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate(`/jobs/${jobId}/candidates/${item.candidate_id}`)}
                      className="text-xs"
                    >
                      Inspect Report →
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Confirmation Dialog */}
      <Dialog open={!!selectedCandidate} onOpenChange={(open) => !open && setSelectedCandidate(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {actionType === "PROMOTE" ? "Promote Candidate to Shortlist" : "Confirm Candidate Rejection"}
            </DialogTitle>
            <DialogDescription>
              {actionType === "PROMOTE"
                ? `Move ${selectedCandidate?.candidate_name} into the approved shortlisted pool.`
                : `Confirm rejection for ${selectedCandidate?.candidate_name}. They will receive standard feedback.`}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <label className="text-xs font-medium text-foreground">
              Reviewer Notes (Optional)
            </label>
            <Textarea
              placeholder="Add justification or specific observations..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
            />
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSelectedCandidate(null)}
              disabled={promoteMutation.isPending || rejectMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant={actionType === "PROMOTE" ? "success" : "destructive"}
              onClick={handleConfirmAction}
              disabled={promoteMutation.isPending || rejectMutation.isPending}
            >
              {(promoteMutation.isPending || rejectMutation.isPending) ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Saving...
                </>
              ) : actionType === "PROMOTE" ? (
                "Confirm Shortlist"
              ) : (
                "Confirm Rejection"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
