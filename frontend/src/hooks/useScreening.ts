import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useScreeningStatus(jobId?: string, isScreeningActive: boolean = false) {
  return useQuery({
    queryKey: ["screening-status", jobId],
    queryFn: () => {
      if (!jobId) throw new Error("Job ID required");
      return api.getScreeningStatus(jobId);
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (
        isScreeningActive ||
        data?.status === "IN_PROGRESS" ||
        data?.status === "PROCESSING" ||
        data?.phase3_status === "RUNNING" ||
        data?.phase4_status === "RUNNING"
      ) {
        return 5000;
      }
      return false;
    },
  });
}

export function useRunScreening(jobId: string) {
  const queryClient = useQueryClient();

  return useMutation<{ status: string; message?: string }, Error, number>({
    mutationFn: (shortlistCount: number) => api.runScreening(jobId, shortlistCount),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["screening-status", jobId] });
      queryClient.invalidateQueries({ queryKey: ["candidates", jobId] });
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
