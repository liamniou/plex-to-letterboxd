import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: (q) => (q.state.data?.runner.current || q.state.data?.runner.queued.length ? 2000 : 10000),
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: api.settings });
}

export function useStartJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.startJob,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

/** Busy = a job is running or queued; components disable job buttons while busy. */
export function useBusy() {
  const { data } = useStatus();
  return { current: data?.runner.current ?? null, queued: data?.runner.queued ?? [], busy: !!(data?.runner.current || data?.runner.queued.length) };
}
