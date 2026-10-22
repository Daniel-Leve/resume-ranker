import React, { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Sparkles,
  Search,
  CheckCircle2,
  XCircle,
  Hourglass,
  ArrowRight,
  ShieldAlert,
  Lightbulb,
  Award,
  Layers,
  ChevronRight,
} from "lucide-react";
import { api, CandidateFeedback, ApiError } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

export const FeedbackPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialJobId = searchParams.get("jobId") || "";
  const initialAppId = searchParams.get("appId") || "";
  const initialToken = searchParams.get("token") || "";

  const [jobId, setJobId] = useState(initialJobId);
  const [appId, setAppId] = useState(initialAppId);
  const [token, setToken] = useState(initialToken);

  const [activeParams, setActiveParams] = useState<{
    jobId: string;
    appId: string;
    token: string;
  } | null>(
    initialJobId && initialAppId && initialToken
      ? { jobId: initialJobId, appId: initialAppId, token: initialToken }
      : null
  );

  const {
    data: feedback,
    isLoading,
    error,
  } = useQuery<CandidateFeedback, ApiError>({
    queryKey: ["candidate-feedback", activeParams?.jobId, activeParams?.appId, activeParams?.token],
    queryFn: () => {
      if (!activeParams?.jobId || !activeParams?.appId || !activeParams?.token) {
        throw new Error("Job ID, Application ID, and Access Token are required.");
      }
      return api.getApplicationFeedback(activeParams.jobId, activeParams.appId, activeParams.token);
    },
    enabled: !!activeParams?.jobId && !!activeParams?.appId && !!activeParams?.token,
    retry: (failureCount, err) => {
      // Don't retry on 409 or 401/403
      if (err.status === 409 || err.status === 401 || err.status === 403) return false;
      return failureCount < 2;
    },
  });

  const handleLookup = (e: React.FormEvent) => {
    e.preventDefault();
    if (jobId.trim() && appId.trim() && token.trim()) {
      const params = { jobId: jobId.trim(), appId: appId.trim(), token: token.trim() };
      setActiveParams(params);
      setSearchParams(params);
    }
  };

  const isPendingReview = error?.status === 409 || feedback?.decision === "PENDING" || feedback?.decision === "NEEDS_REVIEW";

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div className="text-center space-y-2">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 shadow-md text-white mx-auto mb-2">
          <Sparkles className="h-6 w-6" />
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
          Candidate Feedback Portal
        </h1>
        <p className="text-sm text-muted-foreground">
          Transparent, constructive AI evaluation insights for your application
        </p>
      </div>

      {/* Query Inputs Card */}
      <Card className="shadow-sm">
        <CardContent className="pt-6">
          <form onSubmit={handleLookup} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label htmlFor="fb-job">Job ID</Label>
                <Input
                  id="fb-job"
                  placeholder="e.g. job_12345"
                  value={jobId}
                  onChange={(e) => setJobId(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="fb-app">Application ID</Label>
                <Input
                  id="fb-app"
                  placeholder="e.g. app_67890"
                  value={appId}
                  onChange={(e) => setAppId(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="fb-token">Candidate Access Token</Label>
              <Input
                id="fb-token"
                type="password"
                placeholder="Paste the secret token provided during application"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required
              />
            </div>

            <Button type="submit" className="w-full gap-2">
              <Search className="h-4 w-4" />
              Retrieve Feedback Report
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Report Display */}
      {activeParams && (
        <>
          {isLoading ? (
            <LoadingSpinner text="Retrieving verified evaluation results..." />
          ) : isPendingReview ? (
            /* 409 or Pending State with Animated Hourglass */
            <Card className="border-amber-200 dark:border-amber-900 bg-amber-50/40 dark:bg-amber-950/20 shadow-md text-center p-8">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-100 text-amber-600 dark:bg-amber-900 dark:text-amber-300 mx-auto mb-4 animate-bounce">
                <Hourglass className="h-7 w-7 animate-spin" />
              </div>
              <CardTitle className="text-xl font-bold text-amber-900 dark:text-amber-200">
                Evaluation Pending Final Review
              </CardTitle>
              <CardDescription className="text-sm text-amber-800/90 dark:text-amber-300/80 max-w-md mx-auto mt-2">
                Your application has cleared initial AI screening and is currently in the recruiter verification queue. Please check back shortly.
              </CardDescription>
              <div className="mt-6">
                <Link to={`/track?jobId=${activeParams.jobId}&appId=${activeParams.appId}`}>
                  <Button variant="outline" size="sm" className="gap-2">
                    Inspect Pipeline Status
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </Card>
          ) : error ? (
            <Card className="p-6 text-center border-destructive/30 bg-destructive/5">
              <ShieldAlert className="h-8 w-8 text-destructive mx-auto mb-2" />
              <h3 className="font-semibold text-sm text-destructive">Unable to Retrieve Feedback</h3>
              <p className="text-xs text-muted-foreground mt-1">
                {error.status === 401 || error.status === 403
                  ? "Invalid candidate access token provided for this application."
                  : error.message}
              </p>
            </Card>
          ) : feedback?.decision === "SHORTLISTED" ? (
            /* Shortlisted Celebration Banner */
            <Card className="border-emerald-300 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/20 shadow-lg">
              <CardHeader className="text-center pb-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-900 dark:text-emerald-300 mx-auto mb-3 ring-8 ring-emerald-100/50">
                  <Award className="h-8 w-8" />
                </div>
                <CardTitle className="text-2xl font-bold text-emerald-900 dark:text-emerald-200">
                  Congratulations, {feedback.candidate_name}!
                </CardTitle>
                <CardDescription className="text-emerald-800 dark:text-emerald-300">
                  Your profile has been shortlisted for <strong>{feedback.job_title || "this position"}</strong>.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="p-4 rounded-lg bg-background border space-y-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Next Steps
                  </h4>
                  <p className="text-xs text-foreground leading-relaxed">
                    The talent acquisition team has received your verified rubric score. An interview coordinator will reach out directly to schedule next conversational rounds.
                  </p>
                </div>

                {feedback?.strengths && feedback.strengths.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-800 dark:text-emerald-300">
                      Standout Qualifications Identified:
                    </h4>
                    <ul className="text-xs text-foreground space-y-1.5 pl-4 list-disc">
                      {feedback.strengths.map((str, idx) => (
                        <li key={idx}>{str}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            /* Empathetic Rejection / Feedback Card Layout */
            <div className="space-y-4">
              <Card className="shadow-md border">
                <CardHeader>
                  <div className="flex items-center gap-2 text-rose-600 mb-1">
                    <XCircle className="h-5 w-5" />
                    <span className="text-xs font-semibold uppercase tracking-wider">Evaluation Outcome</span>
                  </div>
                  <CardTitle className="text-xl">Application Status: Not Moving Forward</CardTitle>
                  <CardDescription>
                    Thank you for your interest in {feedback?.job_title || "this position"}. While we are not progressing with your candidacy, here is our transparent feedback.
                  </CardDescription>
                </CardHeader>

                <CardContent className="space-y-6">
                  {/* What your resume showed */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                      <Layers className="h-4 w-4 text-primary" />
                      What Your Resume Demonstrated
                    </h4>
                    <div className="p-3 bg-muted/40 rounded-lg border text-xs text-foreground space-y-1">
                      {feedback?.strengths?.map((item, idx) => (
                        <p key={idx} className="flex items-start gap-2">
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0 mt-0.5" />
                          <span>{item}</span>
                        </p>
                      )) || <p>Strong relevant foundational background.</p>}
                    </div>
                  </div>

                  {/* Areas for enhancement */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-rose-700 dark:text-rose-400">
                      Areas for Enhancement
                    </h4>
                    <div className="p-3 bg-rose-50/50 dark:bg-rose-950/20 rounded-lg border border-rose-200 dark:border-rose-900 text-xs text-foreground space-y-1">
                      {feedback?.gaps?.map((gap, idx) => (
                        <p key={idx} className="flex items-start gap-2">
                          <span className="text-rose-600 font-bold">•</span>
                          <span>{gap}</span>
                        </p>
                      )) || <p>Alignment with role-specific technical requirements.</p>}
                    </div>
                  </div>

                  {/* Recommendation */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                      <Lightbulb className="h-4 w-4 text-amber-500" />
                      Recommendations for Future Roles
                    </h4>
                    <div className="p-3 bg-amber-50/40 dark:bg-amber-950/20 rounded-lg border border-amber-200 dark:border-amber-900 text-xs text-foreground space-y-1">
                      {feedback?.recommendations?.map((rec, idx) => (
                        <p key={idx}>• {rec}</p>
                      )) || (
                        <p>
                          Focus on highlighting tangible project outcomes and core architectural proficiencies aligned with modern cloud stacks.
                        </p>
                      )}
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="border-t pt-4">
                  <Button variant="outline" className="w-full gap-2 text-xs">
                    View Similar Open Positions
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </CardFooter>
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
};
