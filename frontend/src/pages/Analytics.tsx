import {
  Box,
  Chip,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useBuildings, useReports, useSeverity, useTopDefects } from "../api/hooks";

const DEFECT_SHORT: Record<string, string> = {
  damp_infiltration: "damp",
  fire_safety_noncompliance: "fire_safety",
  material_degradation: "degradation",
};

export default function Analytics() {
  const reportsQ = useReports();
  const buildingsQ = useBuildings();
  const [reports, setReports] = useState<string[]>([]); // source_file values
  const [buildings, setBuildings] = useState<number[]>([]);

  const top = useTopDefects(reports, buildings, 10);
  const sev = useSeverity(reports, buildings);

  const reportOpts = reportsQ.data ?? [];
  const buildingOpts = buildingsQ.data ?? [];
  const filtered = reports.length > 0 || buildings.length > 0;
  const total = (top.data ?? []).reduce((s, d) => s + d.n, 0);

  const defectData = (top.data ?? []).map((d) => ({
    name: DEFECT_SHORT[d.defect_type] ?? d.defect_type,
    n: d.n,
  }));
  const sevData = (sev.data ?? []).map((d) => ({ name: d.severity, n: d.n }));

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Portfolio analytics
      </Typography>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          select
          label="Report"
          value={reports}
          onChange={(e) => setReports(e.target.value as unknown as string[])}
          SelectProps={{
            multiple: true,
            renderValue: (sel) => (
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                {(sel as string[]).map((v) => {
                  const r = reportOpts.find((o) => o.source_file === v);
                  return <Chip key={v} size="small" label={r ? `${r.report_id} — ${v}` : v} />;
                })}
              </Box>
            ),
          }}
          sx={{ minWidth: 260, flex: 1 }}
        >
          {reportOpts.map((r) => (
            <MenuItem key={r.report_id} value={r.source_file}>
              {r.report_id} — {r.source_file}
            </MenuItem>
          ))}
        </TextField>

        <TextField
          select
          label="Building"
          value={buildings.map(String)}
          onChange={(e) =>
            setBuildings((e.target.value as unknown as string[]).map((v) => Number(v)))
          }
          SelectProps={{
            multiple: true,
            renderValue: (sel) => (
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                {(sel as string[]).map((v) => {
                  const b = buildingOpts.find((o) => o.building_id === Number(v));
                  return <Chip key={v} size="small" label={b ? b.display_name : v} />;
                })}
              </Box>
            ),
          }}
          sx={{ minWidth: 260, flex: 1 }}
        >
          {buildingOpts.map((b) => (
            <MenuItem key={b.building_id} value={String(b.building_id)}>
              {b.display_name}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {total} observations{filtered ? " (filtered)" : ""}
      </Typography>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Paper sx={{ p: 2, flex: 1 }}>
          <Typography variant="subtitle1" gutterBottom>
            Most frequent defect types
          </Typography>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={defectData} margin={{ bottom: 40 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" angle={-30} textAnchor="end" interval={0} height={60} />
              <YAxis allowDecimals={false} />
              <RTooltip />
              <Bar dataKey="n" fill="#1f77b4" />
            </BarChart>
          </ResponsiveContainer>
        </Paper>

        <Paper sx={{ p: 2, flex: 1 }}>
          <Typography variant="subtitle1" gutterBottom>
            Severity distribution
          </Typography>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={sevData} margin={{ bottom: 40 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" angle={-30} textAnchor="end" interval={0} height={60} />
              <YAxis allowDecimals={false} />
              <RTooltip />
              <Bar dataKey="n" fill="#1f77b4" />
            </BarChart>
          </ResponsiveContainer>
        </Paper>
      </Stack>
    </Box>
  );
}
