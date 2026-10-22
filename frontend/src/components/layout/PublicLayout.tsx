import React from "react";
import { Link, Outlet } from "react-router-dom";
import { Sparkles, Compass, FileText, CheckCircle2 } from "lucide-react";

export const PublicLayout: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950 text-foreground">
      {/* Candidate Portal Header */}
      <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b bg-background/95 backdrop-blur px-4 sm:px-8">
        <div className="flex items-center gap-3">
          <Link to="/track" className="flex items-center gap-2.5 font-bold text-lg text-foreground">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-500 shadow-md text-white">
              <Sparkles className="h-4 w-4" />
            </div>
            <span>Recruit<span className="text-blue-600">AI</span></span>
            <span className="hidden sm:inline-block ml-2 text-xs font-normal text-muted-foreground border-l pl-3">
              Candidate Portal
            </span>
          </Link>
        </div>

        <nav className="flex items-center gap-4 text-sm font-medium text-muted-foreground">
          <Link
            to="/track"
            className="flex items-center gap-1.5 hover:text-foreground transition-colors"
          >
            <Compass className="h-4 w-4" />
            <span>Track Application</span>
          </Link>
          <Link
            to="/feedback"
            className="flex items-center gap-1.5 hover:text-foreground transition-colors"
          >
            <CheckCircle2 className="h-4 w-4" />
            <span>View Feedback</span>
          </Link>
        </nav>
      </header>

      {/* Portal Content */}
      <main className="flex-1 p-4 sm:p-6 md:p-10 flex items-center justify-center">
        <div className="w-full max-w-3xl">
          <Outlet />
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t py-6 text-center text-xs text-muted-foreground bg-background">
        <p>© {new Date().getFullYear()} RecruitAI Candidate Platform. Powered by intelligent resume screening.</p>
      </footer>
    </div>
  );
};
