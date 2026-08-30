export type Role = "analyst" | "dept_head" | "admin" | "executive";

export interface AuthUser {
  username: string;
  display_name: string;
  role: Role;
  department: string | null;
}

export const ROLE_LABELS: Record<Role, string> = {
  analyst: "Analyst",
  dept_head: "Department Head",
  admin: "Admin",
  executive: "Executive",
};

// Roles allowed to trigger Stage 2-4 on demand (SRS FR — investigation is an analyst/admin action).
export const CAN_RUN_DETECTION: Role[] = ["analyst", "admin"];

// Roles allowed to upload observations/text-evidence (Stage 1 ingestion) — matches the backend's
// require_roles("analyst", "admin") on the upload/template routes. Metric create/delete stays
// admin-only and is gated separately in Data.tsx.
export const CAN_UPLOAD_DATA: Role[] = ["analyst", "admin"];

// Roles allowed to see the suppressed-log audit trail and playbook library.
export const CAN_VIEW_ADMIN: Role[] = ["admin"];
