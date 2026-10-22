import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Job, Rubric } from "@/lib/api";

export function useJobs() {
  return useQuery<Job[], Error>({
    queryKey: ["jobs"],
    queryFn: () => api.getJobs(),
    staleTime: 1000 * 30, // 30s
  });
}

export function useJob(jobId?: string) {
  return useQuery<Job, Error>({
    queryKey: ["job", jobId],
    queryFn: () => {
      if (!jobId) throw new Error("Job ID is required");
      return api.getJob(jobId);
    },
    enabled: !!jobId,
  });
}

export function useCreateJob() {
  const queryClient = useQueryClient();

  return useMutation<Job, Error, { title: string; location?: string; description: string }>({
    mutationFn: (data) => api.createJob(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useGenerateRubric(jobId: string) {
  const queryClient = useQueryClient();

  return useMutation<Rubric, Error, void>({
    mutationFn: () => api.generateRubric(jobId),
    onSuccess: (newRubric) => {
      queryClient.setQueryData<Job>(["job", jobId], (old) => {
        if (!old) return old;
        return {
          ...old,
          rubric_status: newRubric.status || "DRAFT",
          rubric: newRubric,
        };
      });
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useApproveRubric(jobId: string) {
  const queryClient = useQueryClient();

  return useMutation<Rubric, Error, void>({
    mutationFn: () => api.approveRubric(jobId),
    onSuccess: (approvedRubric) => {
      queryClient.setQueryData<Job>(["job", jobId], (old) => {
        if (!old) return old;
        return {
          ...old,
          rubric_status: "APPROVED",
          rubric: approvedRubric,
        };
      });
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
