import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles, ArrowRight, Lock, Mail, User, CheckCircle2, Loader2, KeyRound } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";

export const SignUpPage: React.FC = () => {
  const [step, setStep] = useState<"REGISTER" | "CONFIRM">("REGISTER");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmationCode, setConfirmationCode] = useState("");
  const [loading, setLoading] = useState(false);

  const { signUp, confirmSignUp, signIn } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !email || !password) {
      toast({
        title: "Missing Fields",
        description: "Please complete all fields.",
        variant: "destructive",
      });
      return;
    }

    if (password.length < 8) {
      toast({
        title: "Weak Password",
        description: "Password must be at least 8 characters long.",
        variant: "destructive",
      });
      return;
    }

    setLoading(true);
    try {
      await signUp(email.trim(), password, name.trim());
      toast({
        title: "Account Created!",
        description: "Verification code sent to your email.",
        variant: "success",
      });
      setStep("CONFIRM");
    } catch (err: any) {
      toast({
        title: "Sign-Up Failed",
        description: err.message || "Failed to create account.",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirmationCode) {
      toast({
        title: "Enter Code",
        description: "Please enter the verification code sent to your email.",
        variant: "destructive",
      });
      return;
    }

    setLoading(true);
    try {
      await confirmSignUp(email.trim(), confirmationCode.trim());
      toast({
        title: "Email Verified!",
        description: "Logging you in...",
        variant: "success",
      });

      // Auto sign-in
      try {
        await signIn(email.trim(), password);
        navigate("/dashboard");
      } catch {
        navigate("/sign-in");
      }
    } catch (err: any) {
      toast({
        title: "Verification Failed",
        description: err.message || "Invalid verification code.",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 p-4">
      <div className="w-full max-w-md">
        <div className="flex flex-col items-center mb-8">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 shadow-lg text-white mb-3">
            <Sparkles className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">RecruitAI</h1>
          <p className="text-sm text-muted-foreground">Autonomous AI resume screening for modern teams</p>
        </div>

        <Card className="border shadow-lg">
          {step === "REGISTER" ? (
            <>
              <CardHeader className="space-y-1">
                <CardTitle className="text-xl">Create Recruiter Account</CardTitle>
                <CardDescription>
                  Start ranking candidates with calibrated AI rubrics
                </CardDescription>
              </CardHeader>

              <form onSubmit={handleRegister}>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="name">Full Name</Label>
                    <div className="relative">
                      <User className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="name"
                        placeholder="Jane Doe"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className="pl-9"
                        required
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="email">Work Email</Label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="email"
                        type="email"
                        placeholder="recruiter@company.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        className="pl-9"
                        required
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="password">Password</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="password"
                        type="password"
                        placeholder="At least 8 characters"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="pl-9"
                        required
                        disabled={loading}
                      />
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="flex flex-col space-y-4">
                  <Button type="submit" className="w-full gap-2" disabled={loading}>
                    {loading ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Creating Account...
                      </>
                    ) : (
                      <>
                        Continue
                        <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>

                  <div className="text-center text-sm text-muted-foreground">
                    Already registered?{" "}
                    <Link to="/sign-in" className="font-medium text-blue-600 hover:underline">
                      Sign in here
                    </Link>
                  </div>
                </CardFooter>
              </form>
            </>
          ) : (
            <>
              <CardHeader className="space-y-1">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-blue-600 mb-2">
                  <KeyRound className="h-5 w-5" />
                </div>
                <CardTitle className="text-xl">Verify your email</CardTitle>
                <CardDescription>
                  We sent a 6-digit confirmation code to <strong>{email}</strong>
                </CardDescription>
              </CardHeader>

              <form onSubmit={handleConfirmCode}>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="code">Confirmation Code</Label>
                    <Input
                      id="code"
                      placeholder="123456"
                      value={confirmationCode}
                      onChange={(e) => setConfirmationCode(e.target.value)}
                      className="text-center tracking-widest text-lg font-mono"
                      required
                      disabled={loading}
                      autoFocus
                    />
                  </div>
                </CardContent>

                <CardFooter className="flex flex-col space-y-4">
                  <Button type="submit" className="w-full gap-2" disabled={loading}>
                    {loading ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Verifying...
                      </>
                    ) : (
                      <>
                        Confirm and Sign In
                        <CheckCircle2 className="h-4 w-4" />
                      </>
                    )}
                  </Button>

                  <button
                    type="button"
                    onClick={() => setStep("REGISTER")}
                    className="text-sm text-muted-foreground hover:text-foreground"
                  >
                    Back to registration
                  </button>
                </CardFooter>
              </form>
            </>
          )}
        </Card>
      </div>
    </div>
  );
};
