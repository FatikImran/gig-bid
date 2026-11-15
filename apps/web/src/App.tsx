import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, BadgeCheck, BarChart3, Bell,
  BriefcaseBusiness, Check, ChevronDown, CircleDollarSign, Clock3, FileText, Filter,
  GitBranch, LayoutDashboard, Menu, MessageSquareText, MoreHorizontal, Search,
  Send, Settings, ShieldAlert, Sparkles, Wallet, X,
} from "lucide-react";

type Job = {
  job_id: string; title: string; description: string; required_skills: string[];
  budget: { min: number | null; max: number | null; currency: string; type?: string }; duration_days?: number | null;
  connects_cost: number | null; recommendation: string; fit_score: number | null; risk_score?: number;
  suggested_price_usd?: number; upwork_url?: string; applied?: boolean; can_apply?: boolean | null;
  data_provenance?: string; published_date?: string; synthetic_scenario?: string;
};

type Proposal = {
  id: string; job_id: string; status: string; marketplace?: string; analysis: {
    decision: { action: string; reasons: string[] }; risk_report: { score: number; flags: string[]; explanation: string };
    fit_report: { score: number; matched_skills: string[]; missing_skills: string[] };
    price_quote: { amount: number; unit: "fixed" | "hourly"; connects_cost: number; rationale: string };
    evidence: { evidence_id: string; title: string; summary: string; outcome: string; source: string }[];
    claim_verification: { claim: string; status: string; evidence_ids: string[] }[];
    proposal_draft: { cover_letter: string; screening_answers: string[] };
    compliance_verdict: { allowed: boolean; violations: string[] };
    dry_run: { external_write_enabled: boolean; connects_cost: number };
  }; proposal: { cover_letter: string; screening_answers: string[] };
  external_submission?: string;
  upwork_preview?: { ready: boolean; connects_cost: number | null; connects_balance: number | null; can_apply: boolean | null; screening_questions: string[] };
  simulator_result?: { outcome?: string; connects_spent?: number };
};
type Message = {
  id: string; job_id: string; status: string; intent: string; marketplace?: string;
  incoming_message: string; draft: string; rejection_reason?: string;
  negotiation_decision?: {
    action: string; offered_amount: number | null; recommended_amount: number | null;
    unit: "fixed" | "hourly"; profile_floor: number; budget_ceiling: number | null; reason: string;
  };
};
type Run = { event: string; trace_id: string; details: { job_id?: string; proposal_id?: string; message_id?: string }; created_at: string };
type Analytics = {
  proposal_count: number; simulated_outcome_count: number;
  simulated_reply_rate: number | null; simulated_hire_rate: number | null;
  synthetic_connects_spent: number; outcome_provenance: string;
};
type Portfolio = {
  profiles: { freelancer_id: string; display_name: string; headline: string; hourly_rate_usd: number; minimum_project_budget_usd: number; skills: string[] }[];
  evidence: { evidence_id: string; freelancer_id: string; title: string; summary: string; outcome: string; source: string }[];
  provenance: string; uploads_enabled: boolean;
};

function jobBudget(job: Job): string {
  const { min, max, type } = job.budget;
  const unit = type === "hourly" ? "/hr" : "";
  if (min !== null && max !== null) return `$${min}–$${max}${unit}`;
  if (min !== null) return `From $${min}${unit}`;
  if (max !== null) return `Up to $${max}${unit}`;
  return "Unlisted";
}

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const todayLabel = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  month: "long",
  day: "numeric",
}).format(new Date()).toUpperCase();
const NAV = [
  { name: "Overview", icon: LayoutDashboard },
  { name: "Job inbox", icon: BriefcaseBusiness },
  { name: "Pipeline", icon: Activity },
  { name: "Messages", icon: MessageSquareText },
  { name: "Agent runs", icon: GitBranch },
  { name: "Analytics", icon: BarChart3 },
  { name: "Portfolio", icon: FileText },
  { name: "Settings", icon: Settings },
];

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("gigbid-token") ?? "");
  const [personaId, setPersonaId] = useState(
    localStorage.getItem("gigbid-persona") ?? "sample-ai-engineer",
  );
  const [authenticated, setAuthenticated] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [selected, setSelected] = useState<Job | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [draft, setDraft] = useState("");
  const [activeNav, setActiveNav] = useState("Job inbox");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [messageJobId, setMessageJobId] = useState("");
  const [incomingMessage, setIncomingMessage] = useState("");
  const [evidenceId, setEvidenceId] = useState("");
  const [bid, setBid] = useState("");
  const [bidUnit, setBidUnit] = useState("fixed");
  const [proposalBusy, setProposalBusy] = useState(false);
  const upworkMode = portfolio?.provenance === "local_owner_portfolio";

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`${API}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail?.message ?? body?.detail ?? `Request failed (${response.status})`);
    }
    return response.json();
  }, [token]);

  const refresh = useCallback(async (query = "") => {
    setLoading(true);
    setError("");
    try {
      const [jobData, proposalData, messageData, runData, analyticsData, portfolioData] = await Promise.all([
        request(`/api/jobs?persona_id=${encodeURIComponent(personaId)}${query ? `&query=${encodeURIComponent(query)}` : ""}`),
        request("/api/proposals"), request("/api/messages"), request("/api/runs"),
        request("/api/analytics"),
        request(`/api/portfolio?persona_id=${encodeURIComponent(personaId)}`),
      ]);
      setJobs(jobData);
      setProposals(proposalData);
      setMessages(messageData);
      setRuns(runData);
      setAnalytics(analyticsData);
      setPortfolio(portfolioData);
      setAuthenticated(true);
      localStorage.setItem("gigbid-token", token);
      localStorage.setItem("gigbid-persona", personaId);
    } catch (reason) {
      setAuthenticated(false);
      setError(reason instanceof Error ? reason.message : "Could not connect to GigBid API.");
    } finally { setLoading(false); }
  }, [personaId, request, token]);

  useEffect(() => {
    if (token && localStorage.getItem("gigbid-token") === token) void refresh();
  }, [refresh, token]);

  const openJob = async (job: Job) => {
    setSelected(job);
    setProposal(null);
    setNotice("");
    setError("");
    if (job.data_provenance === "upwork_live") {
      setEvidenceId("");
      setBid("");
      setBidUnit(job.budget.type === "hourly" ? "hourly" : "fixed");
      const existing = proposals.find((item) => item.marketplace === "upwork" && item.job_id === job.job_id);
      if (existing && existing.status !== "rejected") {
        setProposal(existing);
        setDraft(existing.proposal.cover_letter);
      }
      try {
        const details = await request(`/api/jobs/${encodeURIComponent(job.job_id)}`);
        setSelected((current) => current?.job_id === job.job_id ? { ...current, ...details } : current);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not load the Upwork job details.");
      }
      return;
    }
    if (job.recommendation === "skip") return;
    setLoading(true);
    try {
      const result = await request(
        `/api/jobs/${encodeURIComponent(job.job_id)}/analyze?persona_id=${encodeURIComponent(personaId)}`,
        { method: "POST" },
      );
      setProposal(result);
      setDraft(result.proposal.cover_letter);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analysis failed.");
    } finally { setLoading(false); }
  };

  const draftUpworkProposal = async () => {
    if (!selected || !evidenceId || !Number.isFinite(Number(bid)) || Number(bid) <= 0) return;
    setProposalBusy(true);
    setError("");
    try {
      const next = await request(`/api/jobs/${encodeURIComponent(selected.job_id)}/analyze`, {
        method: "POST", body: JSON.stringify({ evidence_id: evidenceId, amount: Number(bid), unit: bidUnit }),
      });
      setProposal(next);
      setProposals((current) => [next, ...current.filter((item) => item.id !== next.id)]);
      setDraft(next.proposal.cover_letter);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not prepare the Upwork draft.");
    } finally { setProposalBusy(false); }
  };

  const saveEdit = async () => {
    if (!proposal) return;
    setProposalBusy(true);
    setError("");
    try {
      const updated = await request(`/api/proposals/${proposal.id}`, {
        method: "PUT", body: JSON.stringify({ cover_letter: draft, screening_answers: proposal.proposal.screening_answers }),
      });
      setProposal(updated);
      setProposals((current) => current.map((item) => item.id === updated.id ? updated : item));
      setDraft(updated.proposal.cover_letter);
      setNotice("Draft saved and all claims re-verified.");
      if (proposal.marketplace !== "upwork") await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save draft."); }
    finally { setProposalBusy(false); }
  };

  const approve = async () => {
    if (!proposal || proposalBusy) return;
    const live = proposal.marketplace === "upwork";
    setProposalBusy(true);
    setError("");
    try {
      const result = await request(`/api/proposals/${proposal.id}/approve`, {
        method: "POST", headers: { "Idempotency-Key": `proposal-approve-${proposal.id}` },
      });
      if (live) {
        const approved = { ...proposal, ...result };
        setProposal(approved);
        setProposals((current) => current.map((item) => item.id === approved.id ? approved : item));
      } else {
        setNotice(`Approved for your records. ${result.external_submission}`);
        setProposal(null);
        await refresh();
      }
    } catch (reason) {
      if (live) {
        const latest = await request(`/api/proposals/${proposal.id}`).catch(() => null);
        if (latest) {
          setProposal(latest);
          setProposals((current) => current.map((item) => item.id === latest.id ? latest : item));
        }
      }
      setError(reason instanceof Error ? reason.message : "Approval failed.");
    } finally { setProposalBusy(false); }
  };

  const reject = async () => {
    if (!proposal) return;
    const reason = window.prompt("Why are you rejecting this proposal?");
    if (!reason) return;
    try {
      await request(`/api/proposals/${proposal.id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
      setNotice("Proposal rejected. Reason recorded.");
      setProposal(null);
      await refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Rejection failed."); }
  };

  const draftMessage = async () => {
    if ((!upworkMode && !messageJobId) || !incomingMessage.trim()) return;
    try {
      await request("/api/messages/draft", {
        method: "POST",
        body: JSON.stringify({ job_id: messageJobId || null, message: incomingMessage, persona_id: personaId }),
      });
      setIncomingMessage("");
      setNotice("Reply drafted for your review. Nothing was sent.");
      if (upworkMode) setMessages(await request("/api/messages"));
      else await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not draft a reply.");
    }
  };

  const decideMessage = async (message: Message, approve: boolean) => {
    let reason: string | null = null;
    if (!approve) {
      reason = window.prompt("Why are you rejecting this reply?");
      if (!reason) return;
    }
    try {
      const result = await request(
        `/api/messages/${message.id}/${approve ? "approve" : "reject"}`,
        {
          method: "POST",
          headers: approve ? { "Idempotency-Key": `message-approve-${message.id}` } : undefined,
          body: approve ? undefined : JSON.stringify({ reason }),
        },
      );
      setNotice(approve ? `Reply approved. ${result.external_send}` : "Reply rejected.");
      if (upworkMode) setMessages(await request("/api/messages"));
      else await refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not update reply.");
    }
  };

  const copyApprovedReply = async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.draft);
      setNotice("Draft copied. Paste it into your Upwork conversation for final review.");
    } catch {
      setError("Clipboard access was unavailable. Select and copy the approved draft text.");
    }
  };

  const filteredJobs = useMemo(() => upworkMode ? jobs : jobs.filter((job) =>
    `${job.title} ${job.description} ${job.required_skills.join(" ")}`.toLowerCase().includes(search.toLowerCase())
  ), [jobs, search, upworkMode]);

  const summary = useMemo(() => ({
    recommended: jobs.filter((job) => job.recommendation === "bid").length,
    pending: proposals.filter((item) => item.status === "awaiting_review" || item.status === "edited").length,
    connects: proposals.reduce((total, item) => total + (item.analysis?.price_quote.connects_cost ?? 0), 0),
  }), [jobs, proposals]);
  const activeProfile = portfolio?.profiles[0];
  const pipelineStages = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"];
  const stageFor = (item: Proposal) => {
    const outcome = item.simulator_result?.outcome;
    if (item.status === "rejected" || outcome === "ignored") return "lost";
    if (outcome === "hired") return "hired";
    if (outcome === "interview") return "interview";
    if (outcome === "replied") return "replied";
    if (item.status === "approved") return "submitted";
    return "drafted";
  };

  if (!authenticated) return <div className="login">
    <div className="login-card">
      <div className="brand-mark"><Sparkles size={22} /></div>
      <p className="eyebrow">FREELANCER COPILOT</p>
      <h1>Work worth<br />winning.</h1>
      <p className="muted">GigBid finds the signal in your job feed, grounds every proposal in your work, and leaves every decision to you.</p>
      <label htmlFor="token">Local API access token</label>
      <input id="token" value={token} onChange={(event) => setToken(event.target.value)} />
      <button className="primary full" onClick={() => void refresh()}>Connect workspace <ArrowUpRight size={16} /></button>
      {error && <p className="error">{error}</p>}
      <p className="fine">Use your workspace access token to connect.</p>
    </div>
    <div className="login-art"><span>Evidence in.</span><span>Confidence out.</span><div className="orbit o1" /><div className="orbit o2" /><div className="orbit o3" /></div>
  </div>;

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Sparkles size={19} /></div><span>gigbid<span className="brand-dot">.</span></span></div>
      <div className="workspace"><div className="avatar">GB</div><div><strong>{activeProfile?.display_name ?? "GigBid profile"}</strong><small>{activeProfile?.headline ?? "Choose a persona"}</small></div><ChevronDown size={15} /></div>
      <p className="nav-label">WORKSPACE</p>
      <nav>{NAV.map((item) => <button key={item.name} className={activeNav === item.name ? "nav-item active" : "nav-item"} onClick={() => setActiveNav(item.name)}><item.icon size={17} /><span>{item.name}</span>{item.name === "Job inbox" && jobs.length > 0 && <small>{jobs.length.toString().padStart(2, "0")}</small>}</button>)}</nav>
      <p className="nav-label tools-label">YOUR TOOLS</p>
      <button className={activeNav === "Portfolio" ? "nav-item active" : "nav-item"} onClick={() => setActiveNav("Portfolio")}><FileText size={17} /><span>Portfolio</span></button>
      <button className="nav-item" onClick={() => setActiveNav("Settings")}><Wallet size={17} /><span>Connects budget</span></button>
      <div className="sidebar-bottom"><div className="safe-card"><div className="safe-icon"><ShieldAlert size={16} /></div><div><b>Human-first by design</b><span>Nothing is sent without you.</span></div></div>                  <button className="profile-foot profile-button" onClick={() => setActiveNav("Settings")}><div className="avatar small">GB</div><div><b>{activeProfile?.display_name ?? "GigBid profile"}</b><span>Settings & profile</span></div><MoreHorizontal size={17} /></button></div>
    </aside>
    <main className="main">
      <header className="topbar"><button className="icon-btn mobile-menu" aria-label="Menu"><Menu size={19} /></button><div className="breadcrumb">Workspace <span>/</span> <b>{activeNav}</b></div><div className="top-actions"><div className="connection"><i /> {upworkMode ? "Upwork · local workspace" : "Sample mode · local data"}</div><button className="icon-btn" aria-label="Notifications"><Bell size={18} /><i className="notify-dot" /></button><div className="avatar small">AM</div></div></header>
      <div className="content">
        <div className="page-heading"><div><p className="eyebrow">{todayLabel}</p><h1>{activeNav === "Job inbox" ? "Find your next good fit." : activeNav}</h1><p className="muted">A considered shortlist, grounded in your portfolio.</p></div><button className="quiet-button" onClick={() => void refresh()}><Activity size={15} /> Refresh feed</button></div>
        {error && <div className="alert error"><ShieldAlert size={16} /> {String(error)} <button onClick={() => setError("")}><X size={15} /></button></div>}
        {notice && <div className="alert success"><Check size={16} /> {notice} <button onClick={() => setNotice("")}><X size={15} /></button></div>}
        {(activeNav === "Overview" || activeNav === "Job inbox") && <section className="metric-row">
          <div className="metric-card"><div className="metric-top"><span>Worth a look</span><span className="metric-icon green"><BriefcaseBusiness size={16} /></span></div><strong>{summary.recommended.toString().padStart(2, "0")}</strong><small><span className="positive"><ArrowUpRight size={13} />Curated</span> from this sample feed</small></div>
          <div className="metric-card"><div className="metric-top"><span>Awaiting your review</span><span className="metric-icon lavender"><FileText size={16} /></span></div><strong>{summary.pending.toString().padStart(2, "0")}</strong><small>Nothing leaves without approval</small></div>
          <div className="metric-card"><div className="metric-top"><span>Connects in review queue</span><span className="metric-icon peach"><CircleDollarSign size={16} /></span></div><strong>{summary.connects.toString().padStart(2, "0")} <em>credits</em></strong><small><span className="muted">Proposed spend · never charged</span></small></div>
          <div className="metric-card accent-card"><div className="accent-orb" /><div className="metric-top"><span>Portfolio match</span><span className="metric-icon dark"><Sparkles size={16} /></span></div><strong>Evidence<span className="brand-dot">.</span></strong><small>Every claim linked to real work</small></div>
        </section>}
        {(activeNav === "Overview" || activeNav === "Job inbox") && <section className="feed-section">
          <div className="section-head"><div><h2>{upworkMode ? "Upwork listings" : "Curated for you"} <span className="count-pill">{filteredJobs.length}</span></h2><p>{upworkMode ? "Search Upwork or open a listing to review it." : "Ranked by fit, budget, and client safety signals."}</p></div><div className="feed-controls"><label className="search"><Search size={16} /><input placeholder="Search opportunities..." maxLength={160} value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (upworkMode && event.key === "Enter") void refresh(search.trim()); }} /></label>{upworkMode ? <button className="filter-btn" disabled={loading} onClick={() => void refresh(search.trim())}>Search Upwork</button> : <button className="filter-btn"><Filter size={15} /> Filters <ChevronDown size={13} /></button>}</div></div>
          {loading && <div className="loading"><span /> Refreshing your workspace…</div>}
          <div className="job-list">{filteredJobs.map((job, index) => <article key={job.job_id} className={`job-card ${selected?.job_id === job.job_id ? "chosen" : ""}`}>
            <div className="job-main"><div className={`company-mark mark-${index}`}>{index === 0 ? "N" : "!"}</div><div className="job-copy"><div className="job-labels"><span className={job.recommendation === "bid" ? "status good" : "status danger"}><i />{job.data_provenance === "upwork_live" ? "LIVE LISTING" : job.recommendation === "bid" ? "GOOD FIT" : "RISK FLAG"}</span><span className="posted">{job.data_provenance === "upwork_live" ? "Upwork" : job.data_provenance === "kaggle_posting" ? `Historical Kaggle posting${job.published_date ? ` · ${job.published_date}` : ""}` : job.data_provenance === "synthetic_scenario" ? `Synthetic test · ${job.synthetic_scenario ?? "scenario"}` : "Starter-kit synthetic sample"}</span></div><h3>{job.title}</h3><p>{job.description}</p><div className="skill-list">{job.required_skills.map((skill) => <span key={skill}>{skill}</span>)}</div></div></div>
            <div className="job-side"><div><small>{job.budget.type === "hourly" ? "HOURLY RATE" : "PROJECT BUDGET"}</small><b>{jobBudget(job)}</b></div>{job.fit_score !== null && <div className="fit-line"><div><span>Portfolio fit</span><b>{Math.round(job.fit_score * 100)}%</b></div><div className="progress"><i style={{ width: `${job.fit_score * 100}%` }} /></div></div>}<button className={job.recommendation === "bid" ? "open-button" : "open-button muted-button"} onClick={() => void openJob(job)}>{job.data_provenance === "upwork_live" ? "View Upwork listing" : job.recommendation === "bid" ? "Review opportunity" : "View risk details"} <ArrowUpRight size={14} /></button></div>
          </article>)}</div>
        </section>}
        {(activeNav === "Overview" || activeNav === "Job inbox") && <section className="pipeline-section"><div className="section-head"><div><h2>In your pipeline</h2><p>Your opportunities, at a glance.</p></div><button className="text-button" onClick={() => setActiveNav("Pipeline")}>View pipeline <ArrowUpRight size={14} /></button></div><div className="pipeline-lanes">{["Drafted", "Submitted", "In conversation", "Won"].map((stage, index) => <div className="lane" key={stage}><div className="lane-head"><span><i className={`lane-dot lane-${index}`} />{stage}</span><small>{index === 0 ? proposals.filter((p) => p.status === "awaiting_review").length : 0}</small></div>{index === 0 && proposals.filter((p) => p.status === "awaiting_review").map((p) => <button className="pipeline-card" key={p.id} onClick={() => { setProposal(p); setDraft(p.proposal.cover_letter); setSelected(jobs.find((j) => j.job_id === p.job_id) ?? null); }}><span>{p.job_id}</span><b>{jobs.find((j) => j.job_id === p.job_id)?.title ?? "Proposal draft"}</b><small>Needs your review <ArrowDownRight size={12} /></small></button>)}</div>)}</div></section>}
        {activeNav === "Pipeline" && <section className="pipeline-board">
          {pipelineStages.map((stage) => <div className="lane" key={stage}>
            <div className="lane-head"><span>{stage}</span><small>{proposals.filter((item) => stageFor(item) === stage).length}</small></div>
            {proposals.filter((item) => stageFor(item) === stage).map((item) => (
              <button className="pipeline-card" key={item.id} onClick={() => {
                setProposal(item);
                setDraft(item.proposal.cover_letter);
                setSelected(jobs.find((job) => job.job_id === item.job_id) ?? null);
              }}>
                <span>{item.job_id}</span>
                <b>{jobs.find((job) => job.job_id === item.job_id)?.title ?? "Proposal"}</b>
                <small>{item.simulator_result?.outcome ?? item.status}</small>
              </button>
            ))}
          </div>)}
          <p className="screen-note">“Viewed” and “lost” states are not supplied by the local simulator unless explicitly returned; no events are inferred.</p>
        </section>}
        {activeNav === "Messages" && <section className="screen-card">
          <div className="section-head"><div><h2>Conversation review</h2><p>{upworkMode ? "Paste a received Upwork message. After approval, copy the reply into Upwork Messages for final review." : "Enter a received simulator message to draft a reply."}</p></div></div>
          {!upworkMode && <><label className="field-label" htmlFor="message-job">Related job</label>
          <select id="message-job" value={messageJobId} onChange={(event) => setMessageJobId(event.target.value)}>
            <option value="">Choose a job</option>
            {jobs.map((job) => <option value={job.job_id} key={job.job_id}>{job.title}</option>)}
          </select></>}
          <label className="field-label" htmlFor="incoming-message">Received message</label>
          <textarea id="incoming-message" value={incomingMessage} onChange={(event) => setIncomingMessage(event.target.value)} placeholder="Paste or type a message for local intent classification…" />
          <button className="primary" disabled={(!upworkMode && !messageJobId) || !incomingMessage.trim()} onClick={() => void draftMessage()}><Send size={14} /> Draft reply</button>
          <div className="message-list">{messages.map((message) => <article className="screen-card message-card" key={message.id}>
            <div className="message-header"><b>{message.marketplace === "upwork" ? "Upwork conversation" : (jobs.find((job) => job.job_id === message.job_id)?.title ?? message.job_id)}</b><span>{message.intent} · {message.status === "ready_to_copy" ? "Ready to copy" : message.status}</span></div>
            <p><strong>Message:</strong> {message.incoming_message}</p>
            {message.negotiation_decision && <p><strong>Negotiation coach ({message.negotiation_decision.action}):</strong> {message.negotiation_decision.reason}</p>}
            {message.draft && <p><strong>Draft:</strong> {message.draft}</p>}
            {message.rejection_reason && <p><strong>Rejection:</strong> {message.rejection_reason}</p>}
            {message.status === "awaiting_review" && <div className="drawer-actions">
              <button className="secondary" onClick={() => void decideMessage(message, false)}>Reject</button>
              <button className="primary" onClick={() => void decideMessage(message, true)}>Approve reply</button>
            </div>}
            {message.status === "ready_to_copy" && <div className="drawer-actions">
              <button className="secondary" onClick={() => void copyApprovedReply(message)}>Copy approved reply</button>
              <a href="https://www.upwork.com/ab/messages/" target="_blank" rel="noopener noreferrer">Open Upwork Messages</a>
            </div>}
            {message.status === "blocked" && <span className="screen-note">Safety signal blocked this draft.</span>}
          </article>)}</div>
          {messages.length === 0 && <p className="screen-note">No conversation drafts yet.</p>}
        </section>}
        {activeNav === "Agent runs" && <section className="screen-card">
          <div className="section-head"><div><h2>Agent run history</h2><p>Audit events and graph thread IDs from this local workspace.</p></div></div>
          {runs.length === 0 ? <p className="screen-note">No runs recorded yet.</p> : <div className="run-list">
            {runs.map((run, index) => <article className="run-row" key={`${run.trace_id}-${index}`}>
              <GitBranch size={16} /><div><b>{run.event.replace(/_/g, " ")}</b><span>{run.details.job_id ?? run.details.proposal_id ?? run.details.message_id ?? "Local workflow"}</span></div>
              <code>{run.trace_id}</code><time>{run.created_at}</time>
            </article>)}
          </div>}
          <p className="screen-note">This is a minimal local audit viewer, not a hosted distributed trace with per-node tokens or costs.</p>
        </section>}
        {activeNav === "Analytics" && <section className="screen-card">
          <div className="section-head"><div><h2>Outcome analytics</h2><p>Only local simulator outcomes are shown; historical postings have no real outcome labels.</p></div></div>
          <div className="metric-row analytics-metrics">
            <div className="metric-card"><span>Reviewed proposals</span><strong>{analytics?.proposal_count ?? 0}</strong></div>
            <div className="metric-card"><span>Synthetic outcomes</span><strong>{analytics?.simulated_outcome_count ?? 0}</strong></div>
            <div className="metric-card"><span>Simulated reply rate</span><strong>{analytics?.simulated_reply_rate == null ? "N/A" : `${Math.round(analytics.simulated_reply_rate * 100)}%`}</strong></div>
            <div className="metric-card"><span>Simulated hire rate</span><strong>{analytics?.simulated_hire_rate == null ? "N/A" : `${Math.round(analytics.simulated_hire_rate * 100)}%`}</strong></div>
          </div>
          <p className="screen-note">Connects reported here are synthetic: {analytics?.synthetic_connects_spent ?? 0}. Provenance: {analytics?.outcome_provenance ?? "not available"}.</p>
        </section>}
        {activeNav === "Portfolio" && <section className="screen-card">
          <div className="section-head"><div><h2>Portfolio evidence</h2><p>Examples below are authored synthetic coursework; replace them with evidence you own before real use.</p></div></div>
          <div className="profile-picker">
            {portfolio?.profiles.map((profile) => <button className={profile.freelancer_id === personaId ? "profile-choice selected" : "profile-choice"} key={profile.freelancer_id} onClick={() => setPersonaId(profile.freelancer_id)}>
              <b>{profile.display_name}</b><span>{profile.headline}</span><small>${profile.hourly_rate_usd}/hr · ${profile.minimum_project_budget_usd} project floor</small>
            </button>)}
          </div>
          <div className="message-list">{portfolio?.evidence.map((item) => <article className="screen-card evidence-card" key={item.evidence_id}>
            <FileText size={16} /><div><b>{item.title}</b><p>{item.summary}</p><small>{item.evidence_id} · {item.outcome} · {item.source}</small></div>
          </article>)}</div>
          <p className="screen-note">Portfolio uploads and GitHub ingestion are not enabled in this prototype.</p>
        </section>}
        {activeNav === "Settings" && <section className="screen-card">
          <div className="section-head"><div><h2>Workspace settings</h2><p>Choose the synthetic profile used for local fit and pricing analysis.</p></div></div>
          <label className="field-label" htmlFor="persona">Active persona</label>
          <select id="persona" value={personaId} onChange={(event) => setPersonaId(event.target.value)}>
            {portfolio?.profiles.map((profile) => <option key={profile.freelancer_id} value={profile.freelancer_id}>{profile.display_name} — {profile.headline}</option>)}
          </select>
          <div className="settings-grid"><div><b>Marketplace</b><span>Local GigSim-style simulator or sample adapter</span></div><div><b>Autonomy</b><span>Manual approval required for every proposal and message</span></div><div><b>Weekly Connects budget</b><span>Not enforced; simulator Connects are fictional</span></div><div><b>Account connection</b><span>Upwork OAuth is not configured</span></div></div>
        </section>}
        <footer className="footer"><span>GigBid · evidence-first freelance copilot</span><span><i /> All systems operational</span></footer>
      </div>
    </main>
    {selected && <div className="drawer-backdrop" onClick={() => { setSelected(null); setProposal(null); }}><section className="proposal-drawer" onClick={(event) => event.stopPropagation()}>
      <div className="drawer-top"><div><span className="status good"><i /> OPPORTUNITY REVIEW</span><h2>{selected.title}</h2></div><button className="icon-btn" aria-label="Close" onClick={() => { setSelected(null); setProposal(null); }}><X size={18} /></button></div>
      {error && <p className="alert danger" role="alert">{error}</p>}
      {proposal ? <><div className="decision-box"><div className="decision-icon"><BadgeCheck size={19} /></div><div><b>{proposal.analysis.decision.action === "bid" ? "Recommended: prepare a proposal" : "Recommendation: do not bid"}</b><span>{proposal.analysis.decision.reasons.join(" ")}</span></div><strong>{Math.round(proposal.analysis.fit_report.score * 100)}%<small>fit</small></strong></div>
        {proposal.analysis.risk_report.flags.length > 0 && <div className="risk-box"><ShieldAlert size={17} /><div><b>Safety signals detected</b><span>{proposal.analysis.risk_report.flags.join(" · ")}</span></div><strong>{Math.round(proposal.analysis.risk_report.score * 100)}%</strong></div>}
        <div className="detail-grid"><div><small>RECOMMENDED PRICE</small><b>${proposal.analysis.price_quote.amount} <em>USD{proposal.analysis.price_quote.unit === "hourly" ? "/hr" : ""}</em></b><span>{proposal.analysis.price_quote.rationale}</span></div><div><small>CONNECTS PREVIEW</small><b>{proposal.analysis.price_quote.connects_cost} credits</b><span>No Connects are spent by this preview.</span></div></div>
        <div className="drawer-section"><div className="drawer-section-head"><h3>Evidence behind this match</h3><span>{proposal.analysis.evidence.length} items</span></div>{proposal.analysis.evidence.map((item) => <div className="evidence-card" key={item.evidence_id}><div className="evidence-icon"><FileText size={16} /></div><div><b>{item.title}</b><p>{item.summary}</p><span>{item.outcome} · {item.source}</span></div><BadgeCheck size={16} /></div>)}</div>
        <div className="drawer-section"><div className="drawer-section-head"><h3>Proposal studio</h3><span className="verified"><BadgeCheck size={14} /> Claim checks on</span></div><textarea value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Proposal draft" /><div className="claim-list">{proposal.analysis.claim_verification.map((claim, index) => <div key={`${claim.claim}-${index}`}><i className={claim.status === "supported" ? "claim-ok" : "claim-warn"} /> <span>{claim.claim}</span><small>{claim.status}</small></div>)}</div><div className="compliance"><ShieldAlert size={15} /><span>{proposal.analysis.compliance_verdict.allowed ? "Compliance check passed" : `Review required: ${proposal.analysis.compliance_verdict.violations.join("; ")}`}</span></div></div>
        <div className="dryrun"><div><b><Wallet size={15} /> Dry-run preview</b><span>Proposed amount ${proposal.analysis.price_quote.amount} · {proposal.analysis.dry_run.connects_cost} Connects</span></div><span className="no-send">NO EXTERNAL SEND</span></div>
        {proposal.marketplace === "upwork" && proposal.upwork_preview && <div className="drawer-section">
          <h3>{proposal.upwork_preview.ready ? "Upwork preview received" : "Upwork preview needs details"}</h3>
          <p>{proposal.external_submission}</p>
          {proposal.upwork_preview.connects_cost !== null && <p>Connects required: {proposal.upwork_preview.connects_cost}</p>}
          {proposal.upwork_preview.connects_balance !== null && <p>Connects balance: {proposal.upwork_preview.connects_balance}</p>}
          {proposal.upwork_preview.can_apply === false && <p>Upwork reports this account cannot currently apply.</p>}
          {proposal.upwork_preview.screening_questions.length > 0 && <ul>{proposal.upwork_preview.screening_questions.map((question) => <li key={question}>{question}</li>)}</ul>}
          {selected.upwork_url && <a href={selected.upwork_url} target="_blank" rel="noopener noreferrer">Review listing on Upwork</a>}
        </div>}
        {proposal.marketplace === "upwork" && ["preview_failed", "preview_requested"].includes(proposal.status) && <div className="drawer-section">
          <p>{proposal.status === "preview_failed" ? "Upwork did not return a preview." : "The preview request has no recorded outcome."}</p>
          <button className="secondary" onClick={() => setProposal(null)}>Start a new draft</button>
        </div>}
        {(proposal.marketplace !== "upwork" || ["awaiting_review", "edited"].includes(proposal.status)) && <div className="drawer-actions">
          <button className="secondary" disabled={proposalBusy} onClick={() => void reject()}>Reject</button>
          <button className="secondary" disabled={proposalBusy} onClick={() => void saveEdit()}>Save edits</button>
          <button className="primary" disabled={proposalBusy || !proposal.analysis.compliance_verdict.allowed || proposal.analysis.decision.action !== "bid" || (proposal.marketplace === "upwork" && draft !== proposal.proposal.cover_letter)} onClick={() => void approve()}>
            <Check size={15} /> {proposal.marketplace === "upwork" ? "Approve and request Upwork preview" : "Approve draft"}
          </button>
        </div>}
      </> : selected.data_provenance === "upwork_live" ? <div className="skip-panel">
        <h3>Upwork listing</h3><p>{selected.description}</p>
        <p>{jobBudget(selected)} · {selected.connects_cost === null ? "Connects cost unavailable" : `${selected.connects_cost} Connects`}{selected.applied ? " · Already applied" : ""}</p>
        {selected.can_apply === false && <p>Upwork reports this account cannot currently apply.</p>}
        {selected.upwork_url && <a href={selected.upwork_url} target="_blank" rel="noopener noreferrer">Open on Upwork</a>}
        {!selected.applied && Boolean(portfolio?.evidence.length) && <div className="drawer-section">
          <label className="field-label" htmlFor="offer-evidence">Portfolio evidence</label>
          <select id="offer-evidence" value={evidenceId} onChange={(event) => setEvidenceId(event.target.value)}>
            <option value="">Choose a project</option>
            {portfolio?.evidence.map((item) => <option key={item.evidence_id} value={item.evidence_id}>{item.title}</option>)}
          </select>
          <label className="field-label" htmlFor="offer-amount">Bid in USD</label>
          <input id="offer-amount" type="number" min="0.01" step="0.01" value={bid} onChange={(event) => setBid(event.target.value)} />
          <label className="field-label" htmlFor="offer-unit">Bid type</label>
          <select id="offer-unit" value={bidUnit} onChange={(event) => setBidUnit(event.target.value)}>
            <option value="fixed">Fixed price</option><option value="hourly">Hourly</option>
          </select>
          <button className="primary" disabled={proposalBusy || !evidenceId || !Number.isFinite(Number(bid)) || Number(bid) <= 0} onClick={() => void draftUpworkProposal()}>Prepare proposal draft</button>
        </div>}
      </div> : selected.recommendation === "skip" ? <div className="skip-panel"><ShieldAlert size={22} /><h3>This opportunity has a high-risk signal.</h3><p>{selected.description}</p><p>GigBid recommends skipping and will not draft or submit a proposal. You can inspect the job, but the platform safety rules remain in force.</p></div> : <div className="loading"><span /> Building evidence-backed analysis…</div>}
    </section></div>}
  </div>;
}
