"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { clientApi } from "@/lib/client-api";

type Surface = "team" | "finance" | "contracts" | "intelligence" | "reconstruction" | "mlops";
type Json = Record<string, unknown>;
type Artifact = { id: string; asset_type: string; published: boolean; url?: string | null };
type ReconstructionJob = {
  id: string;
  property_id: string;
  representation: string;
  status: string;
  stage: string;
  progress: number;
  error?: string | null;
  cost_amount: number;
  artifact?: Artifact | null;
};
type MLModel = { id: string; name: string; task: string; version: string; status: string; metrics?: Json };
type MLDeployment = {
  id: string;
  model_id: string;
  task: string;
  environment: string;
  status: string;
  traffic_percent: number;
};
type MLDashboard = {
  models: MLModel[];
  deployments: MLDeployment[];
  usage: { units: number; cost: number };
  governance: Json;
};

function endpointFor(surface: Surface) {
  if (surface === "team") return "/organizations/members";
  if (surface === "finance") return "/finance/ledger";
  if (surface === "contracts") return "/contracts/envelopes";
  if (surface === "reconstruction") return "/reconstruction-jobs";
  if (surface === "mlops") return "/mlops/dashboard";
  return "/organizations/current";
}

function formatMoney(value: unknown) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(number);
}

export function P2AgencyConsole({ surface }: { surface: Surface }) {
  const [data, setData] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      setData(await clientApi(endpointFor(surface)));
    } catch (error) {
      setMessage(String(error));
    } finally {
      setLoading(false);
    }
  }, [surface]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const result = await clientApi("/organizations/invitations", {
      method: "POST",
      body: JSON.stringify({ email: form.get("email"), role: form.get("role") }),
    });
    setMessage(`Đã tạo lời mời ${String((result as Json).id || "")}`);
    await refresh();
  }

  async function reconcile() {
    setLoading(true);
    try {
      setData(await clientApi("/finance/reconcile", { method: "POST" }));
      setMessage("Đối soát hoàn tất.");
    } finally {
      setLoading(false);
    }
  }

  async function createPolicyAndTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await clientApi("/contracts/policies", {
      method: "POST",
      body: JSON.stringify({
        document_type: "reservation_agreement",
        jurisdiction: "VN",
        approved: true,
      }),
    });
    const template = await clientApi<Json>("/contracts/templates", {
      method: "POST",
      body: JSON.stringify({
        name: "Thỏa thuận giữ chỗ",
        document_type: "reservation_agreement",
        content_html: "Khách hàng {{buyer_name}} giữ chỗ {{property_title}}.",
        allowed_fields: ["buyer_name", "property_title"],
        version: 1,
      }),
    });
    setMessage(`Đã tạo template ${String(template.id)}`);
    await refresh();
  }

  async function exportTenant() {
    const result = await clientApi<Json>("/organizations/exports", { method: "POST" });
    setMessage(`Đã tạo export ${String(result.id || "")}`);
  }

  async function reviewArtifact(artifactId: string, status: "approved" | "rejected") {
    await clientApi(`/reconstruction-artifacts/${artifactId}/review`, {
      method: "POST",
      body: JSON.stringify({ status, notes: `Reviewed from agency console: ${status}` }),
    });
    setMessage(status === "approved" ? "Đã duyệt và phát hành asset." : "Đã từ chối asset.");
    await refresh();
  }

  async function runJob(jobId: string) {
    await clientApi(`/reconstruction-jobs/${jobId}/run`, { method: "POST" });
    setMessage("Đã chạy reconstruction job.");
    await refresh();
  }

  async function healthDeployment(deploymentId: string) {
    const result = await clientApi<Json>(`/mlops/deployments/${deploymentId}/health`, {
      method: "POST",
    });
    setMessage(`Health: ${String(result.healthy)}${result.auto_rolled_back ? " · đã rollback" : ""}`);
    await refresh();
  }

  async function rollbackDeployment(deploymentId: string) {
    await clientApi(`/mlops/deployments/${deploymentId}/rollback`, { method: "POST" });
    setMessage("Đã rollback deployment.");
    await refresh();
  }

  const title = useMemo(
    () =>
      ({
        team: "Đội ngũ và phân quyền",
        finance: "Sổ cái và đối soát",
        contracts: "Hợp đồng và chữ ký",
        intelligence: "Định giá và recommendation",
        reconstruction: "Tái dựng 3D và immersive",
        mlops: "ML Ops và quản trị chi phí",
      })[surface],
    [surface],
  );

  return (
    <section className="container section p2-console">
      <div className="section-heading">
        <div>
          <span className="eyebrow">P2 · Agency</span>
          <h1>{title}</h1>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Đang tải…" : "Làm mới"}
        </button>
      </div>

      {surface === "team" ? (
        <TeamPanel data={data} onInvite={invite} onExport={() => void exportTenant()} />
      ) : null}
      {surface === "finance" ? (
        <FinancePanel data={data} onReconcile={() => void reconcile()} />
      ) : null}
      {surface === "contracts" ? (
        <ContractsPanel data={data} onCreate={createPolicyAndTemplate} />
      ) : null}
      {surface === "intelligence" ? <IntelligencePanel /> : null}
      {surface === "reconstruction" ? (
        <ReconstructionPanel
          data={data}
          onReview={(id, status) => void reviewArtifact(id, status)}
          onRun={(id) => void runJob(id)}
        />
      ) : null}
      {surface === "mlops" ? (
        <MLOpsPanel
          data={data}
          onHealth={(id) => void healthDeployment(id)}
          onRollback={(id) => void rollbackDeployment(id)}
        />
      ) : null}

      {message ? <p className="status-banner">{message}</p> : null}
    </section>
  );
}

function TeamPanel({
  data,
  onInvite,
  onExport,
}: {
  data: unknown;
  onInvite: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  onExport: () => void;
}) {
  const members = Array.isArray(data) ? (data as Json[]) : [];
  return (
    <>
      <div className="split-grid">
        <form className="panel form-grid" onSubmit={(event) => void onInvite(event)}>
          <h3>Mời thành viên</h3>
          <label>
            Email<input name="email" type="email" required />
          </label>
          <label>
            Vai trò
            <select name="role">
              <option value="agent">Agent</option>
              <option value="manager">Manager</option>
              <option value="finance">Finance</option>
              <option value="analyst">Analyst</option>
              <option value="reviewer">Reviewer</option>
            </select>
          </label>
          <button className="btn btn-primary">Gửi lời mời</button>
        </form>
        <button className="panel action-card" onClick={onExport}>
          <strong>Xuất dữ liệu tenant</strong>
          <span>Tạo JSON riêng tư có checksum và audit trail.</span>
        </button>
      </div>
      <div className="data-grid">
        {members.map((member) => (
          <article className="panel" key={String(member.id || member.user_id)}>
            <strong>{String(member.full_name || member.email || member.user_id)}</strong>
            <p>{String(member.role)} · {String(member.status)}</p>
          </article>
        ))}
      </div>
    </>
  );
}

function FinancePanel({ data, onReconcile }: { data: unknown; onReconcile: () => void }) {
  const ledger = (data || {}) as Json;
  const entries = Array.isArray(ledger.entries) ? (ledger.entries as Json[]) : [];
  return (
    <>
      <div className="button-row">
        <button className="btn btn-primary" onClick={onReconcile}>Chạy đối soát nhà cung cấp</button>
        <span className="badge">Sổ cái: {ledger.balanced === true ? "Cân bằng" : "Cần kiểm tra"}</span>
      </div>
      <div className="data-grid">
        {entries.map((entry) => (
          <article className="panel" key={String(entry.id)}>
            <strong>{formatMoney(entry.amount)}</strong>
            <p>{String(entry.direction)} · {String(entry.reference_type)}</p>
            <small>{String(entry.reference_id || "")}</small>
          </article>
        ))}
      </div>
    </>
  );
}

function ContractsPanel({
  data,
  onCreate,
}: {
  data: unknown;
  onCreate: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const envelopes = Array.isArray(data) ? (data as Json[]) : [];
  return (
    <>
      <form className="panel form-grid" onSubmit={(event) => void onCreate(event)}>
        <h3>Khởi tạo tài liệu đã duyệt</h3>
        <p>Envelope chỉ được gửi sau khi policy pháp lý được duyệt.</p>
        <button className="btn btn-primary">Tạo policy + template</button>
      </form>
      <div className="data-grid">
        {envelopes.map((envelope) => (
          <article className="panel" key={String(envelope.id)}>
            <strong>{String(envelope.document_type || envelope.id)}</strong>
            <p>{String(envelope.status)} · {String(envelope.provider)}</p>
            {envelope.document_url ? <a href={String(envelope.document_url)}>Mở tài liệu</a> : null}
          </article>
        ))}
      </div>
    </>
  );
}

function IntelligencePanel() {
  return (
    <div className="data-grid">
      <a className="panel action-card" href="/account/valuations">
        <strong>AVM</strong>
        <span>Prediction interval, comparables, model lineage và human override.</span>
      </a>
      <a className="panel action-card" href="/account/recommendations">
        <strong>Recommendation</strong>
        <span>Retrieval, ranking, diversity, hide/reset và deterministic fallback.</span>
      </a>
    </div>
  );
}

function ReconstructionPanel({
  data,
  onReview,
  onRun,
}: {
  data: unknown;
  onReview: (id: string, status: "approved" | "rejected") => void;
  onRun: (id: string) => void;
}) {
  const jobs = Array.isArray(data) ? (data as ReconstructionJob[]) : [];
  return (
    <div className="data-grid">
      {jobs.length ? jobs.map((job) => (
        <article className="panel" key={job.id}>
          <span className="badge">{job.status}</span>
          <h3>{job.representation} · {job.progress}%</h3>
          <p>{job.stage} · chi phí {formatMoney(job.cost_amount)}</p>
          {job.error ? <p className="error-text">{job.error}</p> : null}
          <div className="button-row">
            {job.status === "queued" || job.status === "failed" ? (
              <button className="btn btn-secondary btn-sm" onClick={() => onRun(job.id)}>Chạy lại</button>
            ) : null}
            {job.artifact && !job.artifact.published ? (
              <>
                <button className="btn btn-primary btn-sm" onClick={() => onReview(job.artifact!.id, "approved")}>Duyệt</button>
                <button className="btn btn-ghost btn-sm" onClick={() => onReview(job.artifact!.id, "rejected")}>Từ chối</button>
              </>
            ) : null}
            {job.artifact?.url ? <a className="btn btn-secondary btn-sm" href={job.artifact.url}>Mở asset</a> : null}
          </div>
        </article>
      )) : <div className="empty-state">Chưa có reconstruction job.</div>}
    </div>
  );
}

function MLOpsPanel({
  data,
  onHealth,
  onRollback,
}: {
  data: unknown;
  onHealth: (id: string) => void;
  onRollback: (id: string) => void;
}) {
  const dashboard = (data || { models: [], deployments: [], usage: { units: 0, cost: 0 } }) as MLDashboard;
  return (
    <>
      <div className="split-grid">
        <article className="panel"><strong>{dashboard.usage?.units || 0}</strong><p>Inference/health units</p></article>
        <article className="panel"><strong>{formatMoney(dashboard.usage?.cost || 0)}</strong><p>Chi phí model đã ghi nhận</p></article>
      </div>
      <h2>Models</h2>
      <div className="data-grid">
        {(dashboard.models || []).map((model) => (
          <article className="panel" key={model.id}>
            <span className="badge">{model.status}</span>
            <h3>{model.name}:{model.version}</h3>
            <p>{model.task}</p>
          </article>
        ))}
      </div>
      <h2>Deployments</h2>
      <div className="data-grid">
        {(dashboard.deployments || []).map((deployment) => (
          <article className="panel" key={deployment.id}>
            <span className="badge">{deployment.status}</span>
            <h3>{deployment.task} · {deployment.traffic_percent}%</h3>
            <p>{deployment.environment}</p>
            <div className="button-row">
              <button className="btn btn-secondary btn-sm" onClick={() => onHealth(deployment.id)}>Health check</button>
              {deployment.status === "active" ? (
                <button className="btn btn-ghost btn-sm" onClick={() => onRollback(deployment.id)}>Rollback</button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
