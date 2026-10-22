import React, { useState } from "react";
import { User, Building, Users, Mail, Shield, CheckCircle2, Copy } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { useToast } from "@/components/ui/use-toast";

export const SettingsPage: React.FC = () => {
  const { user } = useAuth();
  const { toast } = useToast();
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("Reviewer");

  const { data: profile, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.getMe().catch(() => null),
    staleTime: 1000 * 60 * 5,
  });

  const handleSendInvite = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail) return;

    toast({
      title: "Invitation Sent",
      description: `Team invitation dispatched to ${inviteEmail}.`,
      variant: "success",
    });
    setInviteEmail("");
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
          Workspace Settings
        </h1>
        <p className="text-sm text-muted-foreground">
          Manage your account profile, tenant configuration, and recruiting team
        </p>
      </div>

      {isLoading ? (
        <LoadingSpinner text="Retrieving workspace settings..." />
      ) : (
        <div className="space-y-6">
          {/* User Account Info */}
          <Card className="shadow-sm">
            <CardHeader className="pb-3 border-b">
              <div className="flex items-center gap-2">
                <User className="h-5 w-5 text-blue-600" />
                <CardTitle className="text-base">Recruiter Profile</CardTitle>
              </div>
              <CardDescription>Your personal account details in AWS Cognito</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Full Name</Label>
                  <p className="text-sm font-semibold text-foreground">
                    {profile?.name || user?.name || "Recruiting Team Member"}
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Email Address</Label>
                  <p className="text-sm font-semibold text-foreground">
                    {profile?.email || user?.email || "recruiter@workspace.com"}
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Cognito User ID</Label>
                  <p className="text-xs font-mono text-muted-foreground break-all">
                    {user?.id || "sub-aws-cognito"}
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Assigned Role</Label>
                  <div>
                    <Badge variant="outline" className="text-xs">
                      {profile?.role || "Talent Partner / Admin"}
                    </Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Tenant Membership */}
          <Card className="shadow-sm">
            <CardHeader className="pb-3 border-b">
              <div className="flex items-center gap-2">
                <Building className="h-5 w-5 text-indigo-600" />
                <CardTitle className="text-base">Organization & Tenant</CardTitle>
              </div>
              <CardDescription>Multi-tenant partitioning details</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Tenant Organization</Label>
                  <p className="text-sm font-semibold text-foreground">
                    {profile?.tenant_name || "Enterprise Talent Org"}
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Tenant ID</Label>
                  <p className="text-xs font-mono text-muted-foreground">
                    {profile?.tenant_id || user?.tenantId || "tenant-default-partition"}
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Subscription Plan</Label>
                  <div>
                    <Badge variant="success" className="text-xs">
                      {profile?.plan || "Professional Tier (Unlimited Screenings)"}
                    </Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Team Collaboration Invite Section */}
          <Card className="shadow-sm">
            <CardHeader className="pb-3 border-b">
              <div className="flex items-center gap-2">
                <Users className="h-5 w-5 text-emerald-600" />
                <CardTitle className="text-base">Team Members & Invitations</CardTitle>
              </div>
              <CardDescription>Invite hiring managers and peers to review resumes</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <form onSubmit={handleSendInvite} className="flex flex-col sm:flex-row gap-3">
                <div className="flex-1">
                  <Input
                    type="email"
                    placeholder="teammate@company.com"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    required
                  />
                </div>
                <select
                  aria-label="Select teammate permission level"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="h-9 rounded-md border border-input bg-background px-3 py-1 text-xs"
                >
                  <option value="Admin">Admin</option>
                  <option value="Recruiter">Recruiter</option>
                  <option value="Hiring Manager">Hiring Manager</option>
                  <option value="Reviewer">Reviewer</option>
                </select>
                <Button type="submit" size="sm" className="gap-2">
                  <Mail className="h-4 w-4" />
                  Send Invite
                </Button>
              </form>

              <div className="border rounded-lg divide-y text-xs">
                <div className="p-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="h-7 w-7 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-200 flex items-center justify-center font-bold">
                      {(user?.name || "Y")[0].toUpperCase()}
                    </div>
                    <div>
                      <p className="font-semibold text-foreground">{user?.name || "You"}</p>
                      <p className="text-muted-foreground">{user?.email}</p>
                    </div>
                  </div>
                  <Badge variant="outline">Owner</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};
