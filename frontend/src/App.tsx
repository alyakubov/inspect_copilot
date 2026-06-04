import AnalyticsIcon from "@mui/icons-material/BarChart";
import AskIcon from "@mui/icons-material/ChatBubbleOutline";
import BrowseIcon from "@mui/icons-material/TableRows";
import BuildingsIcon from "@mui/icons-material/Apartment";
import LogoutIcon from "@mui/icons-material/Logout";
import ProcessIcon from "@mui/icons-material/CloudUpload";
import {
  AppBar,
  Box,
  CircularProgress,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import { Suspense, lazy } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { useConfig, useLogout } from "./api/hooks";
import LoginScreen from "./auth/LoginScreen";

// Route-level code splitting: each page (and its heavy deps — Recharts, Leaflet,
// react-markdown, the DataGrid) loads only when first navigated to, keeping the
// initial bundle small.
const Process = lazy(() => import("./pages/Process"));
const Buildings = lazy(() => import("./pages/Buildings"));
const Browse = lazy(() => import("./pages/Browse"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Ask = lazy(() => import("./pages/Ask"));

const DRAWER_WIDTH = 220;

const NAV = [
  { to: "/process", label: "Process", icon: <ProcessIcon /> },
  { to: "/buildings", label: "Buildings", icon: <BuildingsIcon /> },
  { to: "/browse", label: "Browse", icon: <BrowseIcon /> },
  { to: "/analytics", label: "Analytics", icon: <AnalyticsIcon /> },
  { to: "/ask", label: "Ask", icon: <AskIcon /> },
];

export default function App() {
  const { data: config, isLoading } = useConfig();
  const logout = useLogout();

  if (isLoading || !config) {
    return (
      <Box sx={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center" }}>
        <CircularProgress />
      </Box>
    );
  }

  if (config.auth_required && !config.authenticated) {
    return <LoginScreen />;
  }

  return (
    <Box sx={{ display: "flex" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            InspectCopilot — building defect intelligence
          </Typography>
          {config.auth_required && (
            <Tooltip title="Log out">
              <IconButton color="inherit" onClick={() => logout.mutate()}>
                <LogoutIcon />
              </IconButton>
            </Tooltip>
          )}
        </Toolbar>
      </AppBar>

      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: "border-box" },
        }}
      >
        <Toolbar />
        <List>
          {NAV.map((item) => (
            <ListItemButton
              key={item.to}
              component={NavLink}
              to={item.to}
              sx={{ "&.active": { bgcolor: "action.selected" } }}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, p: 3, width: `calc(100% - ${DRAWER_WIDTH}px)` }}>
        <Toolbar />
        <Suspense
          fallback={
            <Box sx={{ display: "flex", justifyContent: "center", mt: 8 }}>
              <CircularProgress />
            </Box>
          }
        >
          <Routes>
            <Route path="/" element={<Navigate to="/process" replace />} />
            <Route path="/process" element={<Process noDelete={config.no_delete_report} />} />
            <Route path="/buildings" element={<Buildings />} />
            <Route path="/browse" element={<Browse />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="*" element={<Navigate to="/process" replace />} />
          </Routes>
        </Suspense>
      </Box>
    </Box>
  );
}
