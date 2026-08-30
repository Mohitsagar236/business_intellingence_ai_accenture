import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import NavShell from "./components/NavShell";
import { RequireAuth, RequireRole } from "./auth/RouteGuards";
import Login from "./pages/Login";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const MetricDetail = lazy(() => import("./pages/MetricDetail"));
const Detection = lazy(() => import("./pages/Detection"));
const ReportView = lazy(() => import("./pages/ReportView"));
const Reports = lazy(() => import("./pages/Reports"));
const Admin = lazy(() => import("./pages/Admin"));
const Data = lazy(() => import("./pages/Data"));

export default function App() {
  return (
    <Suspense fallback={<div className="state-msg">Loading…</div>}>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<RequireAuth />}>
          <Route element={<NavShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/metrics/:metricId" element={<MetricDetail />} />
            <Route path="/anomalies/:anomalyId" element={<ReportView />} />
            <Route path="/reports" element={<Reports />} />

            <Route element={<RequireRole roles={["analyst", "admin"]} />}>
              <Route path="/detection" element={<Detection />} />
              <Route path="/data" element={<Data />} />
            </Route>

            <Route element={<RequireRole roles={["admin"]} />}>
              <Route path="/admin" element={<Admin />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}
