import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Divider,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";

import {
  useBuildingObservations,
  useBuildings,
  useDismissFlag,
  useMergeBuilding,
  useUpdateCanonical,
} from "../api/hooks";
import type { Building } from "../api/types";
import { useToast } from "../components/Toast";

export default function Buildings() {
  const toast = useToast();
  const { data: buildings, isLoading } = useBuildings();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState(0);

  const selected: Building | undefined = useMemo(
    () => buildings?.find((b) => b.building_id === selectedId),
    [buildings, selectedId],
  );

  // Default to the first building once loaded.
  useEffect(() => {
    if (buildings && buildings.length && selectedId == null) {
      setSelectedId(buildings[0].building_id);
    }
  }, [buildings, selectedId]);

  const obs = useBuildingObservations(selectedId);
  const dismiss = useDismissFlag();
  const updateCanonical = useUpdateCanonical();
  const merge = useMergeBuilding();

  const [canonical, setCanonical] = useState("");
  const [mergeTarget, setMergeTarget] = useState<number | "">("");
  useEffect(() => {
    setCanonical(selected?.canonical_address ?? selected?.raw_address ?? "");
    setMergeTarget("");
  }, [selected]);

  if (isLoading) return <Typography>Loading…</Typography>;
  if (!buildings || buildings.length === 0) {
    return <Alert severity="info">No buildings yet — process a report first.</Alert>;
  }

  const others = buildings.filter((b) => b.building_id !== selected?.building_id);

  const cols: GridColDef[] = [
    { field: "page", headerName: "Page", width: 70 },
    { field: "defect_type", headerName: "Defect type", width: 160 },
    { field: "building_element", headerName: "Element", width: 130 },
    { field: "material", headerName: "Material", width: 120 },
    { field: "severity", headerName: "Severity", width: 110 },
    {
      field: "confidence",
      headerName: "Conf.",
      width: 80,
      valueFormatter: (v: number | null) => (v == null ? "—" : v.toFixed(2)),
    },
    { field: "verbatim_quote", headerName: "Verbatim quote", flex: 1, minWidth: 280 },
  ];
  const rows = (obs.data ?? []).map((o, i) => ({ id: i, ...o }));

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Buildings
      </Typography>

      <TextField
        select
        label="Select building"
        value={selectedId ?? ""}
        onChange={(e) => setSelectedId(Number(e.target.value))}
        sx={{ minWidth: 420, mb: 2 }}
      >
        {buildings.map((b) => (
          <MenuItem key={b.building_id} value={b.building_id}>
            {b.flag ? "⚠️ " : ""}
            {b.display_name} ({b.n_obs} defects)
          </MenuItem>
        ))}
      </TextField>

      {selected && (
        <>
          <Typography variant="h6">{selected.display_name}</Typography>
          {selected.canonical_address &&
            selected.canonical_address !== selected.raw_address && (
              <Typography variant="caption" color="text.secondary">
                Originally extracted as: "{selected.raw_address}"
              </Typography>
            )}

          {selected.flag && (
            <Alert
              severity="warning"
              sx={{ my: 2 }}
              action={
                <Button
                  color="inherit"
                  size="small"
                  onClick={() =>
                    dismiss.mutate(selected.building_id, {
                      onSuccess: () => toast("Flag dismissed.", "success"),
                    })
                  }
                >
                  Dismiss
                </Button>
              }
            >
              <strong>
                {selected.flag === "ambiguous_name"
                  ? "Ambiguous name"
                  : "Possible duplicate"}
              </strong>{" "}
              — {selected.flag_reasoning}
            </Alert>
          )}

          <Accordion defaultExpanded={Boolean(selected.flag)} sx={{ my: 2 }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              Edit / merge this building
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2}>
                <Stack direction="row" spacing={1}>
                  <TextField
                    label="Canonical address (saving re-geocodes)"
                    value={canonical}
                    onChange={(e) => setCanonical(e.target.value)}
                    fullWidth
                  />
                  <Button
                    variant="contained"
                    disabled={updateCanonical.isPending}
                    onClick={() =>
                      updateCanonical.mutate(
                        { buildingId: selected.building_id, canonical },
                        { onSuccess: () => toast("Saved & re-geocoded.", "success") },
                      )
                    }
                  >
                    Save & re-geocode
                  </Button>
                </Stack>
                <Divider />
                <Stack direction="row" spacing={1} alignItems="center">
                  <TextField
                    select
                    label="Merge into another building (this row is deleted)"
                    value={mergeTarget}
                    onChange={(e) => setMergeTarget(Number(e.target.value))}
                    sx={{ minWidth: 360 }}
                  >
                    {others.map((b) => (
                      <MenuItem key={b.building_id} value={b.building_id}>
                        {b.display_name} (id #{b.building_id})
                      </MenuItem>
                    ))}
                  </TextField>
                  <Button
                    variant="outlined"
                    color="error"
                    disabled={mergeTarget === "" || merge.isPending}
                    onClick={() =>
                      merge.mutate(
                        { buildingId: selected.building_id, targetId: Number(mergeTarget) },
                        {
                          onSuccess: () => {
                            toast("Merged.", "success");
                            setSelectedId(Number(mergeTarget));
                          },
                        },
                      )
                    }
                  >
                    Merge
                  </Button>
                </Stack>
              </Stack>
            </AccordionDetails>
          </Accordion>

          {selected.latitude != null && selected.longitude != null ? (
            <Paper sx={{ mb: 2 }}>
              <Typography variant="caption" sx={{ display: "block", p: 1 }}>
                📍 {selected.latitude.toFixed(5)}, {selected.longitude.toFixed(5)}
                {selected.country ? ` · ${selected.country}` : ""}
              </Typography>
              <Tabs value={tab} onChange={(_, v) => setTab(v)}>
                <Tab label="2D map" />
                <Tab label="3D view" />
              </Tabs>
              {tab === 0 ? (
                <MapContainer
                  key={`${selected.building_id}-${selected.latitude}-${selected.longitude}`}
                  center={[selected.latitude, selected.longitude]}
                  zoom={17}
                  style={{ height: 460, width: "100%" }}
                >
                  <TileLayer
                    attribution="&copy; OpenStreetMap contributors"
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  <CircleMarker
                    center={[selected.latitude, selected.longitude]}
                    radius={9}
                    pathOptions={{ color: "#1f77b4", fillColor: "#1f77b4", fillOpacity: 0.7 }}
                  >
                    <Popup>{selected.display_name}</Popup>
                  </CircleMarker>
                </MapContainer>
              ) : (
                <iframe
                  key={`cesium-${selected.building_id}`}
                  title="3D view"
                  src={`/api/buildings/${selected.building_id}/cesium`}
                  style={{ height: 520, width: "100%", border: 0 }}
                />
              )}
            </Paper>
          ) : (
            <Alert severity="warning" sx={{ mb: 2 }}>
              This building's address could not be geocoded — no map available.
            </Alert>
          )}

          <Typography variant="h6" gutterBottom>
            Defects ({rows.length})
          </Typography>
          <DataGrid
            rows={rows}
            columns={cols}
            loading={obs.isLoading}
            autoHeight
            density="compact"
            getRowHeight={() => "auto"}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
            pageSizeOptions={[25, 50, 100]}
            sx={{ "& .MuiDataGrid-cell": { py: 1, alignItems: "flex-start" } }}
          />
        </>
      )}
    </Box>
  );
}
