import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Database, FileText, LayoutDashboard, LogOut, ShieldCheck, Zap } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { CAN_RUN_DETECTION, CAN_UPLOAD_DATA, ROLE_LABELS } from "../auth/types";
import "./NavShell.css";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export default function NavShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark">›</span>
            <span className="brand-name">BusinessIntelligence.ai</span>
          </div>
          <nav className="topnav">
            <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
              <LayoutDashboard size={15} strokeWidth={2.25} aria-hidden="true" />
              Dashboard
            </NavLink>
            <NavLink to="/reports" className={({ isActive }) => (isActive ? "active" : "")}>
              <FileText size={15} strokeWidth={2.25} aria-hidden="true" />
              Reports
            </NavLink>
            {!!user && CAN_RUN_DETECTION.includes(user.role) && (
              <NavLink to="/detection" className={({ isActive }) => (isActive ? "active" : "")}>
                <Zap size={15} strokeWidth={2.25} aria-hidden="true" />
                Detection
              </NavLink>
            )}
            {!!user && CAN_UPLOAD_DATA.includes(user.role) && (
              <NavLink to="/data" className={({ isActive }) => (isActive ? "active" : "")}>
                <Database size={15} strokeWidth={2.25} aria-hidden="true" />
                Data
              </NavLink>
            )}
            {user?.role === "admin" && (
              <NavLink to="/admin" className={({ isActive }) => (isActive ? "active" : "")}>
                <ShieldCheck size={15} strokeWidth={2.25} aria-hidden="true" />
                Admin
              </NavLink>
            )}
          </nav>
          {user && (
            <div className="user-menu">
              <div className="user-avatar" aria-hidden="true">
                {initials(user.display_name)}
              </div>
              <div className="user-info">
                <span className="user-name">{user.display_name}</span>
                <span className="user-role mono">{ROLE_LABELS[user.role]}</span>
              </div>
              <button className="btn-secondary" onClick={handleLogout}>
                <LogOut size={13} strokeWidth={2.25} aria-hidden="true" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
