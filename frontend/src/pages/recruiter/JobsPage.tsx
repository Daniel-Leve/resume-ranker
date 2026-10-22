import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PlusCircle, Search, Briefcase, ChevronRight } from "lucide-react";
import { useJobs } from "@/hooks/useJobs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatDate } from "@/lib/utils";

export const JobsPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: jobs = [], isLoading, error } = useJobs();
  const [searchTerm, setSearchTerm] = useState("");

  const filteredJobs = jobs.filter((job) =>
    job.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (job.location && job.location.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
            Job Openings
          </h1>
          <p className="text-sm text-muted-foreground">
            Manage your hiring requisitions, rubrics, and screening pipelines
          </p>
        </div>
        <Button onClick={() => navigate("/jobs/new")} className="gap-2 shadow-sm">
          <PlusCircle className="h-4 w-4" />
          New Job
        </Button>
      </div>

      <Card className="shadow-sm">
        <CardHeader className="p-4 sm:p-6 pb-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div>
              <CardTitle className="text-lg">All Active Requisitions</CardTitle>
              <CardDescription>
                {filteredJobs.length} {filteredJobs.length === 1 ? "position" : "positions"} in your workspace
              </CardDescription>
            </div>
            <div className="relative w-full sm:w-72">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by title or location..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-9 h-9"
              />
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0 sm:p-6 sm:pt-0">
          {isLoading ? (
            <LoadingSpinner text="Fetching job requisitions..." />
          ) : error ? (
            <div className="p-6 text-center text-destructive">
              Failed to load jobs: {error.message}
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<Briefcase className="h-6 w-6" />}
                title={searchTerm ? "No matching jobs" : "No job openings yet"}
                description={
                  searchTerm
                    ? "Try adjusting your search criteria"
                    : "Create your first job posting to start evaluating candidate resumes."
                }
                actionLabel={searchTerm ? undefined : "Create New Job"}
                onAction={searchTerm ? undefined : () => navigate("/jobs/new")}
              />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[30%]">Job Title</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-center">Applications</TableHead>
                  <TableHead className="text-center">Shortlisted</TableHead>
                  <TableHead>Rubric Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredJobs.map((job) => (
                  <TableRow
                    key={job.job_id}
                    onClick={() => navigate(`/jobs/${job.job_id}`)}
                    className="cursor-pointer hover:bg-muted/60 transition-colors"
                  >
                    <TableCell className="font-medium">
                      <div>
                        <span className="font-semibold text-foreground hover:text-blue-600 transition-colors">
                          {job.title}
                        </span>
                        <div className="text-xs text-muted-foreground">
                          {job.location || "Remote / Unspecified"}
                        </div>
                      </div>
                    </TableCell>

                    <TableCell>
                      <Badge variant={job.status === "OPEN" ? "default" : "secondary"}>
                        {job.status || "OPEN"}
                      </Badge>
                    </TableCell>

                    <TableCell className="text-center font-medium">
                      {job.applications_count ?? 0}
                    </TableCell>

                    <TableCell className="text-center">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                        {job.shortlisted_count ?? 0}
                      </span>
                    </TableCell>

                    <TableCell>
                      <Badge
                        variant={
                          job.rubric_status === "APPROVED"
                            ? "success"
                            : job.rubric_status === "DRAFT"
                            ? "warning"
                            : "outline"
                        }
                      >
                        {job.rubric_status || "NONE"}
                      </Badge>
                    </TableCell>

                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(job.created_at)}
                    </TableCell>

                    <TableCell className="text-right">
                      <ChevronRight className="h-4 w-4 text-muted-foreground inline" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
