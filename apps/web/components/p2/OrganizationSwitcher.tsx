"use client";
import { useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";

type Org = { id: string; name: string; slug: string; membership: { role: string } };
export function OrganizationSwitcher() {
  const [items, setItems] = useState<Org[]>([]);
  const [selected, setSelected] = useState("");
  useEffect(() => { void clientApi<Org[]>("/organizations/me").then((rows) => { setItems(rows); if (rows[0]) setSelected(rows[0].id); }).catch(() => setItems([])); }, []);
  if (!items.length) return null;
  async function change(value: string) {
    setSelected(value);
    await fetch("/api/organization/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ organization_id: value }) });
    window.location.reload();
  }
  return <label className="org-switcher"><span className="sr-only">Tổ chức</span><select aria-label="Chọn tổ chức" value={selected} onChange={(event) => void change(event.target.value)}>{items.map((org) => <option key={org.id} value={org.id}>{org.name} · {org.membership.role}</option>)}</select></label>;
}
