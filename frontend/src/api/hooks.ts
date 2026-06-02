import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AppConfig,
  AskResponse,
  Building,
  BuildingObservation,
  DefectCount,
  Observation,
  ObservationsResponse,
  ProcessStats,
  ReportRow,
  SeverityCount,
} from "./types";

// ---- queries ----
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => (await api.get<AppConfig>("/config")).data,
  });
}

export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: async () => (await api.get<ReportRow[]>("/reports")).data,
  });
}

export function useExtractionLog() {
  return useQuery({
    queryKey: ["extraction-log"],
    queryFn: async () =>
      (await api.get<{ status: string; stats: number }[]>("/extraction-log")).data,
  });
}

export function useObservations() {
  return useQuery({
    queryKey: ["observations"],
    queryFn: async () => (await api.get<ObservationsResponse>("/observations")).data,
  });
}

export function useBuildings() {
  return useQuery({
    queryKey: ["buildings"],
    queryFn: async () => (await api.get<Building[]>("/buildings")).data,
  });
}

export function useBuildingObservations(buildingId: number | null) {
  return useQuery({
    enabled: buildingId != null,
    queryKey: ["building-observations", buildingId],
    queryFn: async () =>
      (await api.get<BuildingObservation[]>(`/buildings/${buildingId}/observations`)).data,
  });
}

export function useTopDefects(reports: string[], buildings: number[], limit = 10) {
  return useQuery({
    queryKey: ["top-defects", reports, buildings, limit],
    queryFn: async () =>
      (
        await api.get<DefectCount[]>("/analytics/top-defects", {
          params: { reports, buildings, limit },
        })
      ).data,
  });
}

export function useSeverity(reports: string[], buildings: number[]) {
  return useQuery({
    queryKey: ["severity", reports, buildings],
    queryFn: async () =>
      (
        await api.get<SeverityCount[]>("/analytics/severity", {
          params: { reports, buildings },
        })
      ).data,
  });
}

// ---- mutations ----
export function useUploadReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (await api.post<ProcessStats>("/reports", form)).data;
    },
    onSuccess: () => invalidateAll(qc),
  });
}

export function useDeleteReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (reportId: number) =>
      (await api.delete(`/reports/${reportId}`)).data,
    onSuccess: () => invalidateAll(qc),
  });
}

export function useDismissFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (buildingId: number) =>
      (await api.post(`/buildings/${buildingId}/dismiss-flag`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
  });
}

export function useUpdateCanonical() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { buildingId: number; canonical: string }) =>
      (
        await api.put(`/buildings/${args.buildingId}/canonical`, {
          canonical_address: args.canonical,
        })
      ).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["buildings"] }),
  });
}

export function useMergeBuilding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { buildingId: number; targetId: number }) =>
      (
        await api.post(`/buildings/${args.buildingId}/merge`, {
          target_id: args.targetId,
        })
      ).data,
    onSuccess: () => invalidateAll(qc),
  });
}

export function useAsk() {
  return useMutation({
    mutationFn: async (question: string) =>
      (await api.post<AskResponse>("/ask", { question })).data,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { username: string; password: string }) =>
      (await api.post("/login", args)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["config"] }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/logout")).data,
    onSuccess: () => qc.clear(),
  });
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  ["reports", "extraction-log", "observations", "buildings", "top-defects", "severity"].forEach(
    (k) => qc.invalidateQueries({ queryKey: [k] }),
  );
}

export type { Observation };
