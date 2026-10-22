import React from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ScreeningControlsProps {
  shortlistCount: number;
  setShortlistCount: (count: number) => void;
  onRunScreening: () => void;
  isScreeningInProgress: boolean;
  screeningStatus?: {
    status?: string;
    phase3_status?: string;
    phase4_status?: string;
  };
}

export const ScreeningControls: React.FC<ScreeningControlsProps> = ({
  shortlistCount,
  setShortlistCount,
  onRunScreening,
  isScreeningInProgress,
  screeningStatus,
}) => {
  return (
    <Card className="border shadow-sm bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-blue-600" />
          AI Screening Engine (Phase 3 & 4)
        </CardTitle>
        <CardDescription>
          Execute criteria matching and LLM consistency checks against applicants
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <label
              htmlFor="shortlist"
              className="text-sm font-medium text-muted-foreground whitespace-nowrap"
            >
              Target Shortlist Size:
            </label>
            <Input
              id="shortlist"
              type="number"
              min={1}
              max={50}
              value={shortlistCount}
              onChange={(e) => setShortlistCount(parseInt(e.target.value) || 1)}
              className="w-24 h-9"
              disabled={isScreeningInProgress}
            />
          </div>

          <div className="flex items-center gap-3">
            {isScreeningInProgress && (
              <div className="flex items-center gap-2 text-xs font-medium text-blue-600 bg-blue-50 dark:bg-blue-950/50 px-3 py-1.5 rounded-md">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>
                  Screening in progress ({screeningStatus?.phase3_status || "Phase 3"} /{" "}
                  {screeningStatus?.phase4_status || "Phase 4"}). Polling...
                </span>
              </div>
            )}

            <Button
              onClick={onRunScreening}
              disabled={isScreeningInProgress}
              className="gap-2"
            >
              {isScreeningInProgress ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Run Screening
                </>
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
