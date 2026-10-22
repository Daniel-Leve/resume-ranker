import React, { useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, AlertTriangle, Copy, Check, ArrowRight } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ApplicationSuccessCardProps {
  jobTitle: string;
  jobId: string;
  applicationId: string;
  accessToken: string;
}

export const ApplicationSuccessCard: React.FC<ApplicationSuccessCardProps> = ({
  jobTitle,
  jobId,
  applicationId,
  accessToken,
}) => {
  const [copiedToken, setCopiedToken] = useState(false);

  const handleCopyToken = () => {
    navigator.clipboard.writeText(accessToken);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <Card className="border-emerald-200 dark:border-emerald-900 shadow-lg">
        <CardHeader className="text-center pb-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-300 mx-auto mb-3">
            <CheckCircle2 className="h-8 w-8" />
          </div>
          <CardTitle className="text-2xl font-bold text-foreground">
            Application Submitted Successfully!
          </CardTitle>
          <CardDescription className="text-sm">
            Your resume for <strong>{jobTitle}</strong> has entered our intelligent screening pipeline.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-5">
          <div className="p-4 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <h4 className="font-semibold text-xs text-amber-900 dark:text-amber-200 uppercase tracking-wide">
                  Crucial Action Required
                </h4>
                <p className="text-xs text-amber-800 dark:text-amber-300 leading-relaxed font-medium">
                  Save this access token — it is the only way to access your feedback and status.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Your Private Candidate Access Token
            </Label>
            <div className="flex items-center gap-2">
              <Input
                readOnly
                value={accessToken}
                className="font-mono text-sm bg-muted/50 select-all font-semibold"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={handleCopyToken}
                className="shrink-0 h-9 w-9"
                title="Copy Access Token"
              >
                {copiedToken ? (
                  <Check className="h-4 w-4 text-emerald-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
            <p className="text-[11px] text-muted-foreground font-mono">
              Application ID: {applicationId}
            </p>
          </div>
        </CardContent>

        <CardFooter className="flex flex-col sm:flex-row gap-3 pt-2">
          <Link
            to={`/track?jobId=${jobId}&appId=${applicationId}`}
            className="w-full sm:w-1/2"
          >
            <Button className="w-full gap-2">
              Track Pipeline
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <Link
            to={`/feedback?jobId=${jobId}&appId=${applicationId}&token=${accessToken}`}
            className="w-full sm:w-1/2"
          >
            <Button variant="outline" className="w-full">
              View Feedback Portal
            </Button>
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
};
