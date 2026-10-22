import React, { useState } from "react";
import { HelpCircle, ChevronDown, ChevronUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { InterviewQuestion } from "@/lib/api";

interface InterviewQuestionsAccordionProps {
  questions: InterviewQuestion[];
}

export const InterviewQuestionsAccordion: React.FC<InterviewQuestionsAccordionProps> = ({
  questions,
}) => {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  if (!questions || questions.length === 0) return null;

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <HelpCircle className="h-4 w-4 text-blue-600" />
          Recommended Targeted Interview Questions
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {questions.map((item, idx) => {
          const isOpen = openIndex === idx;
          return (
            <div key={idx} className="border rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setOpenIndex(isOpen ? null : idx)}
                className="w-full text-left p-3.5 bg-muted/30 hover:bg-muted/60 flex items-center justify-between text-xs font-semibold gap-3 transition-colors"
              >
                <span className="text-foreground">
                  {idx + 1}. {item.question}
                </span>
                {isOpen ? (
                  <ChevronUp className="h-4 w-4 shrink-0" />
                ) : (
                  <ChevronDown className="h-4 w-4 shrink-0" />
                )}
              </button>
              {isOpen && item.purpose && (
                <div className="p-3 bg-card border-t text-xs text-muted-foreground">
                  <strong className="text-foreground">Interviewer Note:</strong> {item.purpose}
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
};
