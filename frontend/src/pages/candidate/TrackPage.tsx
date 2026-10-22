import React, { useState, useEffect } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Search,
  CheckCircle2,
  Clock,
  Loader2,
  AlertCircle,
  ArrowRight,
  Compass,
  FileCheck,
  Cpu,
  Database,
  Sparkles,
} from "lucide-react";
import { api, ApplicationTrackStatus } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

export const TrackPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialJobId = searchParams.get("jobId") || "";
  const initialAppId = searchParams.get("appId") || "";

  const [jobId, setJobId] = useState(initialJobId);
  const [appId, setAppId] = useState(initialAppId);
  const [activeQuery, setActiveQuery] = useState<{ jobId: string; appId: string } | null>(
    initialJobId && initialAppId ? { jobId: initialJobId, appId: initialAppId } : null
  );

  const {
    data: trackStatus,
    isLoading,
    error,
  } = useQuery<ApplicationTrackStatus, Error>({
    queryKey: ["application-track", activeQuery?.jobId, activeQuery?.appId],
    queryFn: () => {
      if (!activeQuery?.jobId || !activeQuery?.appId) {
        throw new Error("Both Job ID and Application ID are required");
      }
      return api.getApplicationTrack(activeQuery.jobId, activeQuery.appId);
    },
    enabled: !!activeQuery?.jobId && !!activeQuery?.appId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const isComplete =
        data.overall_status === "COMPLETED" ||
        data.overall_status === "FAILED" ||
        data.steps?.phase3_4_screening === "done";
      return isComplete ? false : 5000;
    },
  });

  const handleTrack = (e: React.FormEvent) => {
    e.preventDefault();
    if (jobId.trim() && appId.trim()) {
      setActiveQuery({ jobId: jobId.trim(), appId: appId.trim() });
      setSearchParams({ jobId: jobId.trim(), appId: appId.trim() });
    }
  };

  const stepsConfig = [
    {
      key: "s3_upload" as const,
      label: "S3 Secure Upload",
      desc: "Resume received and encrypted in cloud storage",
      icon: FileCheck,
    },
    {
      key: "phase1_extraction" as const,
      label: "Phase 1: Resume Extraction",
      desc: "Deep document parsing into structured candidate profiles",
      icon: Cpu,
    },
    {
      key: "phase2_indexing" as const,
      label: "Phase 2: Semantic Indexing",
      desc: "Generating vector embeddings and skills taxonomy",
      icon: Database,
    },
    {
      key: "phase3_4_screening" as const,
      label: "Phase 3 & 4: Rubric Evaluation",
      desc: "Calibrated LLM criteria evaluation and consistency checking",
      icon: Sparkles,
    },
  ];

  const getStepStatus = (stepKey: "s3_upload" | "phase1_extraction" | "phase2_indexing" | "phase3_4_screening") => {
    if (!trackStatus) return "pending";
    return trackStatus.steps?.[stepKey] || "pending";
  };

  const renderStatusIcon = (status: string) => {
    switch (status) {
      case "done":
        return <CheckCircle2 className="h-5 w-5 text-emerald-600" />;
      case "running":
        return <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />;
      case "error":
        return <AlertCircle className="h-5 w-5 text-rose-600" />;
      default:
        return <Clock className="h-5 w-5 text-muted-foreground/50" />;
    }
  };

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div className="text-center space-y-2">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-300 mx-auto mb-2">
          <Compass className="h-6 w-6" />
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
          Track Candidate Pipeline
        </h1>
        <p className="text-sm text-muted-foreground">
          Real-time visibility into AI extraction, indexing, and rubric evaluation
        </p>
      </div>

      {/* Query Form */}
      <Card className="shadow-sm">
        <CardContent className="pt-6">
          <form onSubmit={handleTrack} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label htmlFor="job-id">Job ID</Label>
                <Input
                  id="job-id"
                  placeholder="e.g. job_12345"
                  value={jobId}
                  onChange={(e) => setJobId(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="app-id">Application ID</Label>
                <Input
                  id="app-id"
                  placeholder="e.g. app_67890"
                  value={appId}
                  onChange={(e) => setAppId(e.target.value)}
                  required
                />
              </div>
            </div>
            <Button type="submit" className="w-full gap-2">
              <Search className="h-4 w-4" />
              Check Pipeline Status
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Pipeline Status Results */}
      {activeQuery && (
        <Card className="shadow-md border">
          <CardHeader className="pb-4 border-b">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <CardTitle className="text-base">Processing Stepper</CardTitle>
                <CardDescription className="text-xs font-mono">
                  Application: {activeQuery.appId}
                </CardDescription>
              </div>
              <div>
                {isLoading ? (
                  <Badge variant="outline" className="gap-1 text-xs">
                    <Loader2 className="h-3 w-3 animate-spin" /> Querying status
                  </Badge>
                ) : trackStatus ? (
                  <Badge
                    variant={
                      trackStatus.overall_status === "COMPLETED"
                        ? "success"
                        : trackStatus.overall_status === "FAILED"
                        ? "danger"
                        : "warning"
                    }
                  >
                    {trackStatus.overall_status || "IN PROGRESS"}
                  </Badge>
                ) : null}
              </div>
            </div>
          </CardHeader>

          <CardContent className="pt-6">
            {isLoading ? (
              <div className="py-8 text-center">
                <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-2" />
                <p className="text-xs text-muted-foreground">Checking backend pipeline steps...</p>
              </div>
            ) : error ? (
              <div className="text-center py-6 space-y-2">
                <AlertCircle className="h-8 w-8 text-destructive mx-auto" />
                <p className="text-sm font-semibold text-destructive">Could not locate application</p>
                <p className="text-xs text-muted-foreground">{error.message}</p>
              </div>
            ) : (
              <div className="space-y-6">
                <div className="relative pl-6 space-y-8 before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-border">
                  {stepsConfig.map((step) => {
                    const status = getStepStatus(step.key);
                    return (
                      <div key={step.key} className="relative flex items-start gap-4">
                        <div className="absolute -left-6 bg-background rounded-full p-0.5 ring-4 ring-background">
                          {renderStatusIcon(status)}
                        </div>
                        <div className="space-y-0.5 min-w-0">
                          <p className="text-sm font-semibold text-foreground flex items-center gap-2">
                            {step.label}
                            {status === "running" && (
                              <span className="text-[10px] font-mono font-normal text-blue-600 bg-blue-50 dark:bg-blue-950 px-1.5 py-0.2 rounded">
                                Processing
                              </span>
                            )}
                          </p>
                          <p className="text-xs text-muted-foreground">{step.desc}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {trackStatus?.overall_status === "COMPLETED" && (
                  <div className="pt-4 border-t">
                    <Link
                      to={`/feedback?jobId=${activeQuery.jobId}&appId=${activeQuery.appId}`}
                    >
                      <Button className="w-full gap-2">
                        View Detailed Evaluation Feedback
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};
