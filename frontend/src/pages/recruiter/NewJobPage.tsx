import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Sparkles, Building2, MapPin, FileText, Loader2 } from "lucide-react";
import { useCreateJob } from "@/hooks/useJobs";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/use-toast";

export const NewJobPage: React.FC = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const createJobMutation = useCreateJob();

  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title.trim() || !description.trim()) {
      toast({
        title: "Required Fields",
        description: "Please provide a job title and description.",
        variant: "destructive",
      });
      return;
    }

    try {
      const newJob = await createJobMutation.mutateAsync({
        title: title.trim(),
        location: location.trim() || undefined,
        description: description.trim(),
      });

      toast({
        title: "Job Created!",
        description: "Job posting published. You can now generate an AI screening rubric.",
        variant: "success",
      });

      navigate(`/jobs/${newJob.job_id}`);
    } catch (err: any) {
      toast({
        title: "Failed to create job",
        description: err.message || "An error occurred while creating the job.",
        variant: "destructive",
      });
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Back button */}
      <div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/jobs")}
          className="gap-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Jobs
        </Button>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <div className="flex items-center gap-2.5 text-blue-600 mb-1">
            <Sparkles className="h-5 w-5" />
            <span className="text-xs font-semibold uppercase tracking-wider">New Position</span>
          </div>
          <CardTitle className="text-2xl">Create Hiring Requisition</CardTitle>
          <CardDescription>
            Specify role expectations. The AI will extract requirements to construct an evaluation rubric.
          </CardDescription>
        </CardHeader>

        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="title" className="text-sm font-medium">
                Job Title <span className="text-rose-500">*</span>
              </Label>
              <div className="relative">
                <Building2 className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="title"
                  placeholder="e.g. Senior Full Stack Engineer, Cloud Architect..."
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="pl-9"
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="location" className="text-sm font-medium">
                Location (Optional)
              </Label>
              <div className="relative">
                <MapPin className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="location"
                  placeholder="e.g. San Francisco, CA / Remote / Hybrid"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="description" className="text-sm font-medium">
                  Job Description & Criteria <span className="text-rose-500">*</span>
                </Label>
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <FileText className="h-3.5 w-3.5" />
                  Markdown supported
                </span>
              </div>
              <Textarea
                id="description"
                placeholder="Include responsibilities, required technical skills, minimum years of experience, and nice-to-have qualifications..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={12}
                className="font-mono text-sm leading-relaxed"
                required
              />
              <p className="text-xs text-muted-foreground">
                Tip: Clearly distinguish between must-have technical requirements and bonus skills for more accurate AI scoring.
              </p>
            </div>
          </CardContent>

          <CardFooter className="flex items-center justify-end gap-3 border-t p-6">
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate("/jobs")}
              disabled={createJobMutation.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createJobMutation.isPending} className="gap-2">
              {createJobMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating Position...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Create & Next
                </>
              )}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
};
