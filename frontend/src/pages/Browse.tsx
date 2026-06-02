import {
  Alert,
  Box,
  Chip,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { useMemo, useState } from "react";

import { useObservations } from "../api/hooks";

export default function Browse() {
  const { data, isLoading, isError } = useObservations();
  const [reports, setReports] = useState<string[]>([]);
  const [defectTypes, setDefectTypes] = useState<string[]>([]);
  const [severities, setSeverities] = useState<string[]>([]);
  const [showOptional, setShowOptional] = useState(false);

  const obs = data?.observations ?? [];
  const reportIndex = data?.report_index ?? {};

  const sourceOptions = useMemo(
    () => Array.from(new Set(obs.map((o) => o.source_file))).sort(),
    [obs],
  );
  const defectOptions = useMemo(
    () => Array.from(new Set(obs.map((o) => o.defect_type))).sort(),
    [obs],
  );
  const severityOptions = useMemo(
    () => Array.from(new Set(obs.map((o) => o.severity))).sort(),
    [obs],
  );

  const filtered = obs.filter(
    (o) =>
      (reports.length === 0 || reports.includes(o.source_file)) &&
      (defectTypes.length === 0 || defectTypes.includes(o.defect_type)) &&
      (severities.length === 0 || severities.includes(o.severity)),
  );

  const rows = filtered.map((o, i) => ({ id: i, report: reportIndex[o.source_file] ?? "?", ...o }));

  const columns: GridColDef[] = [
    {
      field: "report",
      headerName: "Report",
      width: 90,
      renderCell: (p) => (
        <Tooltip title={p.row.source_file}>
          <span style={{ borderBottom: "1px dotted #999", cursor: "help" }}>{p.value}</span>
        </Tooltip>
      ),
    },
    { field: "page", headerName: "Page", width: 70 },
    { field: "defect_type", headerName: "Defect type", width: 160 },
    ...(showOptional
      ? ([
          { field: "building_element", headerName: "Element", width: 130 },
          { field: "material", headerName: "Material", width: 120 },
        ] as GridColDef[])
      : []),
    { field: "severity", headerName: "Severity", width: 110 },
    {
      field: "confidence",
      headerName: "Conf.",
      width: 80,
      valueFormatter: (v: number | null) => (v == null ? "—" : v.toFixed(2)),
    },
    { field: "verbatim_quote", headerName: "Verbatim quote", flex: 1, minWidth: 300 },
  ];

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Observations
      </Typography>
      {isError && <Alert severity="error">Failed to load observations.</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
        <MultiSelect label="Report" value={reports} setValue={setReports} options={sourceOptions} renderOption={(s) => `${reportIndex[s] ?? "?"} — ${s}`} />
        <MultiSelect label="Defect type" value={defectTypes} setValue={setDefectTypes} options={defectOptions} />
        <MultiSelect label="Severity" value={severities} setValue={setSeverities} options={severityOptions} />
      </Stack>

      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="body2" color="text.secondary">
          {filtered.length} of {obs.length} observations
        </Typography>
        <FormControlLabel
          control={<Switch checked={showOptional} onChange={(e) => setShowOptional(e.target.checked)} />}
          label="Show optional columns (element, material)"
        />
      </Stack>

      <DataGrid
        rows={rows}
        columns={columns}
        loading={isLoading}
        autoHeight
        density="compact"
        getRowHeight={() => "auto"}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        pageSizeOptions={[25, 50, 100]}
        sx={{ "& .MuiDataGrid-cell": { py: 1, alignItems: "flex-start" } }}
      />
    </Box>
  );
}

function MultiSelect({
  label,
  value,
  setValue,
  options,
  renderOption,
}: {
  label: string;
  value: string[];
  setValue: (v: string[]) => void;
  options: string[];
  renderOption?: (o: string) => string;
}) {
  return (
    <TextField
      select
      label={label}
      value={value}
      onChange={(e) =>
        setValue(typeof e.target.value === "string" ? e.target.value.split(",") : (e.target.value as unknown as string[]))
      }
      SelectProps={{
        multiple: true,
        renderValue: (sel) => (
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
            {(sel as string[]).map((v) => (
              <Chip key={v} size="small" label={renderOption ? renderOption(v) : v} />
            ))}
          </Box>
        ),
      }}
      sx={{ minWidth: 240, flex: 1 }}
    >
      {options.map((o) => (
        <MenuItem key={o} value={o}>
          {renderOption ? renderOption(o) : o}
        </MenuItem>
      ))}
    </TextField>
  );
}
