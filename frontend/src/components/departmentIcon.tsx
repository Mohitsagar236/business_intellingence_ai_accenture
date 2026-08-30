import { Boxes, Code2, Database, Headset, Landmark, Settings2, TrendingUp, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

const MAP: Record<string, LucideIcon> = {
  sales: TrendingUp,
  finance: Landmark,
  support: Headset,
  "customer success": Users,
  engineering: Code2,
  operations: Settings2,
  "data engineering": Database,
};

export function departmentIcon(department: string): LucideIcon {
  return MAP[department.trim().toLowerCase()] ?? Boxes;
}
