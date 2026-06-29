"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getTeamStatus, type TeamStatus as TeamStatusData } from "@/lib/api";
import { ShieldCheck, ShieldOff, Users } from "lucide-react";

export function TeamStatus() {
  const t = useTranslations("TeamStatus");
  const [status, setStatus] = useState<TeamStatusData | null>(null);

  useEffect(() => {
    getTeamStatus().then(setStatus).catch(() => {});
  }, []);

  if (!status) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-md text-xs text-zinc-500">
      {status.auth_enabled ? (
        <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
      ) : (
        <ShieldOff className="w-3.5 h-3.5" />
      )}
      <span>{status.auth_enabled ? t("teamMode") : t("soloMode")}</span>
      {status.users.length > 0 && (
        <span className="flex items-center gap-1 text-zinc-600">
          <Users className="w-3 h-3" />
          {status.users.length}
        </span>
      )}
    </div>
  );
}
