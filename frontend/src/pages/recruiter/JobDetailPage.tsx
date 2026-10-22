import React, { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  ArrowLeft,
  Copy,
  Check,
  Share2,
  Users,
  AlertCircle,
  FileText,
  MapPin,
  Calendar,
  ExternalLink,
} from "lucide-react";
import { useJob } from "@/hooks/useJobs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { RubricViewer } from "@/components/recruiter/RubricViewer";
import { formatDate } from "@/lib/utils";
import ReactMarkdown from "react-markdown";

export const JobDetailPage: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { data: job, isLoading, error } = useJob(jobId);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");

  if (isLoading) {
    return <LoadingSpinner text="Loading job requisition..." />;
  }

  if (error || !job) {
    return (
      <div className="text-center py-12">
        <h2 className="text-lg font-bold text-destructive">Failed to load job details</h2>
        <p className="text-sm text-muted-foreground mt-1 mb-4">{error?.message || "Job not found"}</p>
        <Button variant="outline" onClick={() => navigate("/jobs")}>
          Back to Jobs
        </Button>
      </div>
    );
  }

  const publicApplyUrl = `${window.location.origin}/apply/${job.job_id}`;

  const handleCopyLink = () => {
    navigator.clipboard.writeText(publicApplyUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Breadcrumb */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="space-y-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/jobs")}
            className="gap-1.5 -ml-2 text-muted-foreground hover:text-foreground h-8 mb-1"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Jobs
          </Button>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
              {job.title}
            </h1>
            <Badge variant={job.status === "OPEN" ? "default" : "secondary"}>
              {job.status || "OPEN"}
            </Badge>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" />
              {job.location || "Remote"}
            </span>
            <span>•</span>
            <span className="flex items-center gap-1">
              <Calendar className="h-3.5 w-3.5" />
              Created {formatDate(job.created_at)}
            </span>
          </div>
        </div>

        {/* Quick Nav to Candidates & Review Queue */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => navigate(`/jobs/${job.job_id}/candidates`)}
            className="gap-2"
          >
            <Users className="h-4 w-4 text-emerald-600" />
            Candidates ({job.applications_count ?? 0})
          </Button>
          <Button
            variant="outline"
            onClick={() => navigate(`/jobs/${job.job_id}/review-queue`)}
            className="gap-2"
          >
            <AlertCircle className="h-4 w-4 text-amber-600" />
            Review Queue
          </Button>
        </div>
      </div>

      {/* Shareable Candidate Application Portal Link */}
      <Card className="border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20 shadow-sm">
        <CardContent className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-blue-900 dark:text-blue-200">
              <Share2 className="h-4 w-4 text-blue-600" />
              Public Candidate Portal Link
            </div>
            <p className="text-xs text-blue-700/80 dark:text-blue-300/80">
              Share this link with applicants to submit their resumes for automated extraction and screening.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={publicApplyUrl}
              className="text-xs bg-background border px-3 py-1.5 rounded-md text-foreground font-mono w-64 select-all"
            />
            <Button size="sm" variant="outline" onClick={handleCopyLink} className="gap-1.5">
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5 text-emerald-600" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" />
                  Copy Link
                </>
              )}
            </Button>
            <Link to={`/apply/${job.job_id}`} target="_blank">
              <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
                <ExternalLink className="h-4 w-4 text-muted-foreground" />
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* Navigation Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="overview">Overview & Rubric</TabsTrigger>
          <TabsTrigger value="description">Full Job Description</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          {/* Calibrated Rubric Section */}
          <RubricViewer
            jobId={job.job_id}
            rubric={job.rubric}
            rubricStatus={job.rubric_status}
          />

          {/* Quick Summary Card */}
          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle className="text-base">Role Overview</CardTitle>
              <CardDescription>Key expectations summary</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="prose prose-sm dark:prose-invert max-w-none line-clamp-6 text-muted-foreground">
                <ReactMarkdown>{job.description}</ReactMarkdown>
              </div>
              <Button
                variant="link"
                size="sm"
                onClick={() => setActiveTab("description")}
                className="mt-2 p-0 text-xs"
              >
                Read full job description →
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="description">
          <Card className="shadow-sm">
            <CardHeader>
              <div className="flex items-center gap-2 text-sm font-semibold">
                <FileText className="h-4 w-4 text-primary" />
                Original Job Description
              </div>
            </CardHeader>
            <CardContent>
              <div className="prose prose-slate dark:prose-invert max-w-none text-sm leading-relaxed font-sans bg-muted/20 p-6 rounded-lg border">
                <ReactMarkdown>{job.description}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};
