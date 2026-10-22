import React, { useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import {
  UploadCloud,
  FileCheck,
  ArrowRight,
  Loader2,
  FileText,
  MapPin,
} from "lucide-react";
import { useJob } from "@/hooks/useJobs";
import { api } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ApplicationSuccessCard } from "@/components/candidate/ApplicationSuccessCard";
import { useToast } from "@/components/ui/use-toast";
import ReactMarkdown from "react-markdown";

export const ApplyPage: React.FC = () => {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const { data: job, isLoading: jobLoading } = useJob(jobId);
  const { toast } = useToast();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadStep, setUploadStep] = useState<string>("");

  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const selected = acceptedFiles[0];
      if (selected.type === "application/pdf" || selected.name.endsWith(".pdf")) {
        setFile(selected);
      } else {
        toast({
          title: "Invalid file type",
          description: "Please upload a valid PDF document.",
          variant: "destructive",
        });
      }
    }
  }, [toast]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !email || !file) {
      toast({
        title: "Incomplete Application",
        description: "Please provide your name, email, and upload your resume in PDF format.",
        variant: "destructive",
      });
      return;
    }

    setSubmitting(true);
    setUploadStep("Submitting candidate application...");

    try {
      const initRes = await api.submitApplication(jobId, {
        name: name.trim(),
        email: email.trim(),
        resume_filename: file.name,
      });

      setUploadStep("Uploading resume securely to S3...");

      if (initRes.upload_url) {
        await api.uploadResumeToS3(initRes.upload_url, file);
      }

      setApplicationId(initRes.application_id);
      setAccessToken(initRes.candidate_access_token);

      toast({
        title: "Application Received!",
        description: "Your resume has entered the evaluation pipeline.",
        variant: "success",
      });
    } catch (err: any) {
      toast({
        title: "Submission Error",
        description: err.message || "Failed to submit application. Please try again.",
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
      setUploadStep("");
    }
  };

  if (jobLoading) {
    return <LoadingSpinner text="Retrieving position details..." />;
  }

  if (!job) {
    return (
      <Card className="p-8 text-center max-w-lg mx-auto">
        <h2 className="text-xl font-bold text-destructive">Position Not Available</h2>
        <p className="text-sm text-muted-foreground mt-2 mb-4">
          This job opening could not be located or may have expired.
        </p>
      </Card>
    );
  }

  if (applicationId && accessToken) {
    return (
      <ApplicationSuccessCard
        jobTitle={job.title}
        jobId={jobId}
        applicationId={applicationId}
        accessToken={accessToken}
      />
    );
  }

  return (
    <div className="space-y-8 max-w-2xl mx-auto">
      <div className="space-y-2 text-center sm:text-left border-b pb-6">
        <span className="text-xs font-semibold uppercase tracking-wider text-blue-600 bg-blue-50 dark:bg-blue-950 px-2.5 py-1 rounded">
          Open Requisition
        </span>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground mt-2">
          {job.title}
        </h1>
        <p className="text-sm text-muted-foreground flex items-center justify-center sm:justify-start gap-1.5">
          <MapPin className="h-4 w-4" />
          {job.location || "Remote"}
        </p>
      </div>

      <Card className="shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FileText className="h-4 w-4 text-blue-600" />
            Role Overview
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="prose prose-sm dark:prose-invert max-w-none text-xs text-muted-foreground line-clamp-4 leading-relaxed">
            <ReactMarkdown>{job.description}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-md border">
        <CardHeader>
          <CardTitle className="text-lg">Submit Your Application</CardTitle>
          <CardDescription>
            Provide your details and upload your PDF resume for instant AI analysis
          </CardDescription>
        </CardHeader>

        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="applicant-name">
                Full Name <span className="text-rose-500">*</span>
              </Label>
              <Input
                id="applicant-name"
                placeholder="Jane Candidate"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                disabled={submitting}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="applicant-email">
                Email Address <span className="text-rose-500">*</span>
              </Label>
              <Input
                id="applicant-email"
                type="email"
                placeholder="jane@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={submitting}
              />
            </div>

            <div className="space-y-2">
              <Label>
                Resume Document (PDF) <span className="text-rose-500">*</span>
              </Label>
              <div
                {...getRootProps()}
                className={`p-6 border-2 border-dashed rounded-xl text-center cursor-pointer transition-colors ${
                  isDragActive
                    ? "border-blue-500 bg-blue-50/50 dark:bg-blue-950/20"
                    : file
                    ? "border-emerald-500 bg-emerald-50/20 dark:bg-emerald-950/10"
                    : "border-border hover:border-blue-400 bg-card"
                }`}
              >
                <input {...getInputProps()} />
                {file ? (
                  <div className="flex flex-col items-center gap-2">
                    <FileCheck className="h-10 w-10 text-emerald-600" />
                    <div>
                      <p className="text-sm font-semibold text-foreground">{file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {(file.size / 1024).toFixed(1)} KB • Ready to submit
                      </p>
                    </div>
                    <span className="text-xs text-blue-600 hover:underline mt-1">
                      Click or drag to replace
                    </span>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-2">
                    <UploadCloud className="h-10 w-10 text-muted-foreground/60" />
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        Drag and drop your PDF resume here, or{" "}
                        <span className="text-blue-600 underline">browse</span>
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        PDF documents only (max 10MB)
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </CardContent>

          <CardFooter className="pt-2">
            <Button
              type="submit"
              disabled={submitting || !file}
              className="w-full gap-2 h-10"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {uploadStep || "Submitting application..."}
                </>
              ) : (
                <>
                  Submit Application
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
};
