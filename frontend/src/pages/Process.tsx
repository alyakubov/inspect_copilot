import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import {
  Alert,
  Box,
  Button,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import { isAxiosError } from "axios";
import { useRef, useState } from "react";

import {
  useDeleteReport,
  useExtractionLog,
  useReports,
  useUploadReport,
} from "../api/hooks";
import type { ProcessStats } from "../api/types";
import { useToast } from "../components/Toast";

export default function Process({ noDelete }: { noDelete: boolean }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [stats, setStats] = useState<ProcessStats | null>(null);

  const reports = useReports();
  const log = useExtractionLog();
  const upload = useUploadReport();
  const del = useDeleteReport();

  const runPipeline = () => {
    if (!file) return;
    setStats(null);
    upload.mutate(file, {
      onSuccess: (s) => {
        setStats(s);
        setFile(null);
        if (fileRef.current) fileRef.current.value = "";
        toast(`Processed ${s.file}`, "success");
      },
      onError: (e) => {
        const detail = isAxiosError(e) ? e.response?.data?.detail : null;
        toast(detail ?? "Processing failed.", "error");
      },
    });
  };

  const onDelete = (reportId: number, label: string) => {
    if (noDelete) {
      toast("Report deletion is disabled (NO_DELETE_REPORT=true).", "warning");
      return;
    }
    if (!window.confirm(`Delete ${label}? This removes its observations and orphaned buildings.`)) {
      return;
    }
    del.mutate(reportId, {
      onSuccess: (r: any) =>
        toast(
          `Deleted: ${r.observations} obs, ${r.chunks} chunks, ${r.buildings_deleted} buildings`,
          "success",
        ),
      onError: (e) => {
        const detail = isAxiosError(e) ? e.response?.data?.detail : null;
        toast(detail ?? "Delete failed.", "error");
      },
    });
  };

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Process inspection reports
      </Typography>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" spacing={2} alignItems="center">
          <Button variant="outlined" startIcon={<UploadFileIcon />} component="label">
            {file ? file.name : "Choose PDF"}
            <input
              ref={fileRef}
              hidden
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Button>
          <Button
            variant="contained"
            disabled={!file || upload.isPending}
            onClick={runPipeline}
          >
            {upload.isPending ? "Ingesting, extracting, embedding, geocoding…" : "Run pipeline"}
          </Button>
        </Stack>

        {stats && (
          <Alert severity="success" sx={{ mt: 2 }}>
            {stats.observations} observations from {stats.chunks} chunks · OCR used:{" "}
            {String(stats.ocr_used)} · geocoded: {stats.geocoded} · buildings merged:{" "}
            {stats.buildings_merged} · flagged for review: {stats.buildings_flagged}
          </Alert>
        )}
      </Paper>

      {(log.data?.length ?? 0) > 0 && (
        <>
          <Typography variant="h6" gutterBottom>
            Extraction log
          </Typography>
          <Table size="small" sx={{ mb: 3, maxWidth: 360 }}>
            <TableHead>
              <TableRow>
                <TableCell>status</TableCell>
                <TableCell align="right">stats</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {log.data!.map((r) => (
                <TableRow key={r.status}>
                  <TableCell>{r.status}</TableCell>
                  <TableCell align="right">{r.stats}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}

      <Typography variant="h6" gutterBottom>
        Processed reports
      </Typography>
      {(reports.data?.length ?? 0) === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No reports yet.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell width={50}>#</TableCell>
              <TableCell>Report</TableCell>
              <TableCell>Pages / obs</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {reports.data!.map((d) => (
              <TableRow key={d.report_id}>
                <TableCell>
                  <strong>#{d.report_id}</strong>
                </TableCell>
                <TableCell>{d.source_file}</TableCell>
                <TableCell>
                  {d.n_pages} pages · {d.n_obs} obs
                </TableCell>
                <TableCell align="right">
                  <Tooltip title="Download original PDF">
                    <IconButton
                      component="a"
                      href={`/api/reports/${d.report_id}/download`}
                      size="small"
                    >
                      <DownloadIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={noDelete ? "Deletion disabled (NO_DELETE_REPORT)" : "Delete report"}>
                    <span>
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => onDelete(d.report_id, `#${d.report_id}`)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Box>
  );
}
