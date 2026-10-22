import React from "react";
import { Sparkles, CheckCircle2, ShieldCheck, Scale, Loader2 } from "lucide-react";
import { Rubric } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { useGenerateRubric, useApproveRubric } from "@/hooks/useJobs";
import { useToast } from "@/components/ui/use-toast";

interface RubricViewerProps {
  jobId: string;
  rubric?: Rubric;
  rubricStatus?: string;
}

export const RubricViewer: React.FC<RubricViewerProps> = ({
  jobId,
  rubric,
  rubricStatus = "NONE",
}) => {
  const { toast } = useToast();
  const generateRubricMutation = useGenerateRubric(jobId);
  const approveRubricMutation = useApproveRubric(jobId);

  const handleGenerate = async () => {
    try {
      await generateRubricMutation.mutateAsync();
      toast({
        title: "Rubric Generated",
        description: "AI calibrated candidate criteria based on the job description.",
        variant: "success",
      });
    } catch (err: any) {
      toast({
        title: "Generation Failed",
        description: err.message || "Failed to generate rubric.",
        variant: "destructive",
      });
    }
  };

  const handleApprove = async () => {
    try {
      await approveRubricMutation.mutateAsync();
      toast({
        title: "Rubric Approved",
        description: "Rubric is now locked for AI screening evaluations.",
        variant: "success",
      });
    } catch (err: any) {
      toast({
        title: "Approval Failed",
        description: err.message || "Failed to approve rubric.",
        variant: "destructive",
      });
    }
  };

  const hasRubric = rubric && rubric.criteria && rubric.criteria.length > 0;
  const isDraft = rubricStatus === "DRAFT" || rubric?.status === "DRAFT";
  const isApproved = rubricStatus === "APPROVED" || rubric?.status === "APPROVED";

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b">
        <div>
          <div className="flex items-center gap-2">
            <CardTitle className="text-lg">Calibrated Screening Rubric</CardTitle>
            <Badge
              variant={isApproved ? "success" : isDraft ? "warning" : "outline"}
            >
              {isApproved ? "Approved" : isDraft ? "Draft" : "Not Configured"}
            </Badge>
          </div>
          <CardDescription>
            Weighted dimensions used to evaluate applicants during Phase 3 & 4
          </CardDescription>
        </div>

        <div className="flex items-center gap-2">
          {!hasRubric ? (
            <Button
              onClick={handleGenerate}
              disabled={generateRubricMutation.isPending}
              className="gap-2"
            >
              {generateRubricMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Generating Rubric...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Generate Rubric
                </>
              )}
            </Button>
          ) : isDraft ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleGenerate}
                disabled={generateRubricMutation.isPending}
              >
                Regenerate
              </Button>
              <Button
                size="sm"
                variant="success"
                onClick={handleApprove}
                disabled={approveRubricMutation.isPending}
                className="gap-1.5"
              >
                {approveRubricMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Approve Rubric
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
              <ShieldCheck className="h-4 w-4" />
              Approved for Automated Screening
            </div>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-6">
        {!hasRubric ? (
          <div className="text-center py-8">
            <Scale className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
            <h4 className="font-semibold text-sm">No Rubric Generated Yet</h4>
            <p className="text-xs text-muted-foreground max-w-sm mx-auto mt-1 mb-4">
              Generate an objective evaluation framework tailored to this role's description before running screening.
            </p>
            <Button
              onClick={handleGenerate}
              disabled={generateRubricMutation.isPending}
              size="sm"
              className="gap-2"
            >
              <Sparkles className="h-4 w-4" />
              Generate Rubric with AI
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {rubric.criteria.map((criterion, idx) => (
              <div
                key={criterion.id || idx}
                className="p-4 rounded-lg border bg-card hover:border-slate-300 dark:hover:border-slate-700 transition-colors space-y-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-semibold text-sm text-foreground">{criterion.name}</h4>
                  <div className="flex items-center gap-1.5">
                    <Badge
                      variant={
                        criterion.type === "MUST_HAVE" ? "destructive" : "secondary"
                      }
                      className="text-[10px] px-1.5"
                    >
                      {criterion.type === "MUST_HAVE" ? "Must-Have" : "Nice-to-Have"}
                    </Badge>
                    <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                      Weight: {criterion.weight}x
                    </span>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {criterion.description}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
