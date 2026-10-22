import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Candidate, CandidateReport, ReviewQueueItem } from "@/lib/api";

export function useCandidates(jobId?: string) {
  return useQuery<Candidate[], Error>({
    queryKey: ["candidates", jobId],
    queryFn: () => {
      if (!jobId) throw new Error("Job ID required");
      return api.getCandidates(jobId);
    },
    enabled: !!jobId,
  });
}

export function useCandidate(jobId?: string, candidateId?: string) {
  return useQuery<CandidateReport, Error>({
    queryKey: ["candidate", jobId, candidateId],
    queryFn: () => {
      if (!jobId || !candidateId) throw new Error("Job ID and Candidate ID required");
      return api.getCandidate(jobId, candidateId);
    },
    enabled: !!jobId && !!candidateId,
  });
}

export function useReviewQueue(jobId?: string) {
  return useQuery<ReviewQueueItem[], Error>({
    queryKey: ["review-queue", jobId],
    queryFn: () => {
      if (!jobId) throw new Error("Job ID required");
      return api.getReviewQueue(jobId);
    },
    enabled: !!jobId,
  });
}

export function usePromoteCandidate(jobId: string) {
  const queryClient = useQueryClient();

  return useMutation<any, Error, { candidateId: string; notes?: string }>({
    mutationFn: ({ candidateId, notes }) =>
      api.promoteCandidate(jobId, candidateId, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue", jobId] });
      queryClient.invalidateQueries({ queryKey: ["candidates", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useRejectCandidate(jobId: string) {
  const queryClient = useQueryClient();

  return useMutation<any, Error, { candidateId: string; notes?: string }>({
    mutationFn: ({ candidateId, notes }) =>
      api.rejectCandidate(jobId, candidateId, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue", jobId] });
      queryClient.invalidateQueries({ queryKey: ["candidates", jobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
