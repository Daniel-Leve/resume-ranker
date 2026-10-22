import React from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Briefcase,
  Users,
  AlertCircle,
  Coins,
  PlusCircle,
  ArrowRight,
  TrendingUp,
  FileCheck2,
} from "lucide-react";
import { useJobs } from "@/hooks/useJobs";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatDate } from "@/lib/utils";

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: jobs = [], isLoading, error } = useJobs();

  // Compute metrics client-side from jobs array
  const totalJobs = jobs.length;
  const totalApplications = jobs.reduce((acc, job) => acc + (job.applications_count || 0), 0);
  const totalShortlisted = jobs.reduce((acc, job) => acc + (job.shortlisted_count || 0), 0);
  const totalReviewQueue = jobs.reduce((acc, job) => acc + (job.review_queue_count || 0), 0);

  // Approximate budget / LLM tokens used (e.g. estimated at $0.015 per application)
  const budgetUsed = `$${(totalApplications * 0.015).toFixed(2)}`;

  const recentJobs = [...jobs]
    .sort((a, b) => new Date(b.created_at || "").getTime() - new Date(a.created_at || "").getTime())
    .slice(0, 5);

  const kpis = [
    {
      title: "Total Jobs",
      value: totalJobs,
      icon: Briefcase,
      color: "text-blue-600",
      bgColor: "bg-blue-50 dark:bg-blue-950",
      change: `${jobs.filter((j) => j.status === "OPEN").length} active`,
    },
    {
      title: "Total Applications",
      value: totalApplications,
      icon: Users,
      color: "text-emerald-600",
      bgColor: "bg-emerald-50 dark:bg-emerald-950",
      change: `${totalShortlisted} shortlisted`,
    },
    {
      title: "Review Queue",
      value: totalReviewQueue,
      icon: AlertCircle,
      color: "text-amber-600",
      bgColor: "bg-amber-50 dark:bg-amber-950",
      change: totalReviewQueue > 0 ? "Requires attention" : "All cleared",
    },
    {
      title: "Budget Used",
      value: budgetUsed,
      icon: Coins,
      color: "text-violet-600",
      bgColor: "bg-violet-50 dark:bg-violet-950",
      change: "Phase 1-4 LLM usage",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Top Welcome Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
            Recruiter Dashboard
          </h1>
          <p className="text-sm text-muted-foreground">
            Overview of your active hiring pipelines and AI candidate screenings
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={() => navigate("/jobs/new")} className="gap-2 shadow-sm">
            <PlusCircle className="h-4 w-4" />
            New Job
          </Button>
        </div>
      </div>

      {isLoading ? (
        <LoadingSpinner text="Computing workspace metrics..." />
      ) : error ? (
        <Card className="border-destructive/30 bg-destructive/5 p-6">
          <p className="text-sm text-destructive font-medium">
            Failed to load metrics: {error.message}
          </p>
        </Card>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {kpis.map((kpi, idx) => {
              const Icon = kpi.icon;
              return (
                <Card key={idx} className="shadow-sm hover:shadow transition-shadow">
                  <CardHeader className="flex flex-row items-center justify-between pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">
                      {kpi.title}
                    </CardTitle>
                    <div className={`p-2 rounded-lg ${kpi.bgColor} ${kpi.color}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{kpi.value}</div>
                    <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                      <TrendingUp className="h-3 w-3 text-emerald-500" />
                      {kpi.change}
                    </p>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Quick Actions & Recent Jobs */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Recent Jobs Table */}
            <Card className="lg:col-span-2 shadow-sm">
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle>Recent Job Postings</CardTitle>
                  <CardDescription>Latest positions and screening status</CardDescription>
                </div>
                <Link to="/jobs">
                  <Button variant="ghost" size="sm" className="gap-1 text-xs">
                    View all <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              </CardHeader>
              <CardContent>
                {recentJobs.length === 0 ? (
                  <EmptyState
                    title="No jobs created yet"
                    description="Create your first job posting to calibrate AI rubrics and screen resumes."
                    actionLabel="Create Job"
                    onAction={() => navigate("/jobs/new")}
                  />
                ) : (
                  <div className="divide-y divide-border">
                    {recentJobs.map((job) => (
                      <div
                        key={job.job_id}
                        onClick={() => navigate(`/jobs/${job.job_id}`)}
                        className="flex items-center justify-between py-3.5 px-2 hover:bg-muted/50 rounded-lg cursor-pointer transition-colors"
                      >
                        <div className="space-y-1">
                          <p className="font-medium text-sm text-foreground hover:text-blue-600 transition-colors">
                            {job.title}
                          </p>
                          <div className="flex items-center gap-3 text-xs text-muted-foreground">
                            <span>{job.location || "Remote"}</span>
                            <span>•</span>
                            <span>{formatDate(job.created_at)}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <Badge
                            variant={
                              job.rubric_status === "APPROVED"
                                ? "success"
                                : job.rubric_status === "DRAFT"
                                ? "warning"
                                : "outline"
                            }
                          >
                            Rubric: {job.rubric_status || "NONE"}
                          </Badge>
                          <Badge variant={job.status === "OPEN" ? "default" : "secondary"}>
                            {job.status || "OPEN"}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Quick Actions Card */}
            <Card className="shadow-sm flex flex-col justify-between">
              <CardHeader>
                <CardTitle>Recruiting Workflow</CardTitle>
                <CardDescription>Shortcuts to key pipeline actions</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <Button
                  onClick={() => navigate("/jobs/new")}
                  variant="outline"
                  className="w-full justify-start gap-3 h-12"
                >
                  <PlusCircle className="h-5 w-5 text-blue-600" />
                  <div className="text-left">
                    <p className="text-sm font-medium">Create New Position</p>
                    <p className="text-xs text-muted-foreground">Draft JD and generate rubric</p>
                  </div>
                </Button>

                {recentJobs[0] && (
                  <>
                    <Button
                      onClick={() => navigate(`/jobs/${recentJobs[0].job_id}/candidates`)}
                      variant="outline"
                      className="w-full justify-start gap-3 h-12"
                    >
                      <Users className="h-5 w-5 text-emerald-600" />
                      <div className="text-left">
                        <p className="text-sm font-medium">Candidate Leaderboard</p>
                        <p className="text-xs text-muted-foreground">{recentJobs[0].title}</p>
                      </div>
                    </Button>

                    <Button
                      onClick={() => navigate(`/jobs/${recentJobs[0].job_id}/review-queue`)}
                      variant="outline"
                      className="w-full justify-start gap-3 h-12"
                    >
                      <AlertCircle className="h-5 w-5 text-amber-600" />
                      <div className="text-left">
                        <p className="text-sm font-medium">Pending Review Queue</p>
                        <p className="text-xs text-muted-foreground">Review flagged borderline candidates</p>
                      </div>
                    </Button>
                  </>
                )}
              </CardContent>
              <div className="p-6 pt-0">
                <div className="rounded-lg bg-blue-50/70 dark:bg-blue-950/40 p-3 border border-blue-100 dark:border-blue-900 flex items-start gap-3">
                  <FileCheck2 className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" />
                  <p className="text-xs text-blue-900 dark:text-blue-200">
                    Rubrics are calibrated against your job description using structured LLM evaluation.
                  </p>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
};
