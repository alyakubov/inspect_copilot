export interface AppConfig {
  auth_required: boolean;
  authenticated: boolean;
  no_delete_report: boolean;
  cesium_token_present: boolean;
}

export interface ReportRow {
  report_id: number;
  source_file: string;
  n_pages: number;
  n_obs: number;
}

export interface Observation {
  source_file: string;
  page: number;
  defect_type: string;
  building_element: string | null;
  material: string | null;
  severity: string;
  confidence: number | null;
  verbatim_quote: string;
}

export interface ObservationsResponse {
  observations: Observation[];
  report_index: Record<string, number>;
}

export interface Building {
  building_id: number;
  display_name: string;
  raw_address: string;
  canonical_address: string | null;
  flag: string | null;
  flag_reasoning: string | null;
  possibly_same_as_building_id: number | null;
  latitude: number | null;
  longitude: number | null;
  country: string | null;
  n_obs: number;
}

export interface BuildingObservation {
  page: number;
  defect_type: string;
  building_element: string | null;
  material: string | null;
  severity: string;
  confidence: number | null;
  verbatim_quote: string;
}

export interface DefectCount {
  defect_type: string;
  n: number;
}

export interface SeverityCount {
  severity: string;
  n: number;
}

export interface AskResponse {
  answer: string;
  sources: string[];
  scope: string[];
}

// Stats returned by the ingest pipeline (process_pdf).
export interface ProcessStats {
  file: string;
  chunks: number;
  ocr_used: boolean;
  observations: number;
  geocoded: string;
  buildings_merged: number;
  buildings_flagged: number;
  merges_rejected_geo?: number;
}
