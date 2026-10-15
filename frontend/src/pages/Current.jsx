// This week's approved scorecards.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, stamp, weekRange } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../hooks";
import { ClearX, ErrorBox, Loading, Segmented } from "../components";
import { ScorecardView } from "./Dashboard";

const KEY = "scorecard.current.report";
const CLOSED = "scorecard.current.closed";

function read() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

// Which runs' approval banners have been closed.
function closedRuns() {
  try { return JSON.parse(localStorage.getItem(CLOSED) ?? "[]"); } catch { return []; }
}

export default function Current() {
  const { user } = useAuth();
  const { data: cards, error } = useLoad(api.currentScorecards, []);
  const [report, setReport] = useState(read() ?? "gfs");
  const [closed, setClosed] = useState(closedRuns);
  const [closing, setClosing] = useState(null);

  function close(runId) {
    setClosing(runId);
    setTimeout(() => {
      const next = [...closedRuns().filter((id) => id !== runId), runId].slice(-50);
      try { localStorage.setItem(CLOSED, JSON.stringify(next)); } catch { /* storage blocked */ }
      setClosed(next);
      setClosing(null);
    }, 320);
  }

  function choose(key) {
    setReport(key);
    try { localStorage.setItem(KEY, key); } catch { /* storage blocked */ }
  }

  if (error) return <ErrorBox error={error} />;
  if (!cards) return <Loading what="Finding this week's scorecard" />;

  if (cards.length === 0) {
    return (
      <>
        <div className="head"><h1>This week&apos;s scorecard</h1></div>
        <div className="card empty-state rise">
          <div className="empty-mark" aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 26 26">
              <rect x="6" y="11" width="14" height="10" rx="2.5" fill="none"
                    stroke="currentColor" strokeWidth="1.6" />
              <path d="M9 11V8.5a4 4 0 0 1 8 0V11" fill="none"
                    stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </div>
          <h2>No scorecards shared with you yet</h2>
          <p className="muted">
            An admin chooses which scorecards each account can see. Ask one to
            give you GFS, All Providers, or both.
          </p>
        </div>
      </>
    );
  }

  const card = cards.find((c) => c.key === report) ?? cards[0];
  const picker = cards.length > 1 ? (
    <Segmented value={card.key} onChange={choose}
               options={cards.map((c) => ({ value: c.key, label: c.short }))} />
  ) : null;

  if (!card.run) {
    return (
      <>
        <div className="head spread">
          <div>
            <h1>{card.label}</h1>
            <div className="sub">Mailed {card.send_day}</div>
          </div>
          {picker}
        </div>
        <div className="card empty-state rise">
          <div className="empty-mark" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 28 28">
              <rect x="5" y="4" width="18" height="20" rx="3" fill="none"
                    stroke="currentColor" strokeWidth="1.6" />
              <path d="M9.5 10h9M9.5 14h9M9.5 18h5" stroke="currentColor"
                    strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </div>
          <h2>No approved {card.short} scorecard yet</h2>
          <p className="muted">
            It appears here as soon as someone approves a build.
            {card.waiting && ` ${card.waiting.week} is built and waiting for review.`}
          </p>
        </div>
      </>
    );
  }

  const run = card.run;
  return (
    <ScorecardView key={run.id} id={run.id} header={(detail) => (
      <>
        <div className="head spread">
          <div>
            <div className="eyebrow">This week&apos;s scorecard</div>
            <h1>{card.label}</h1>
          </div>
          {picker}
        </div>

        {!closed.includes(run.id) && (
        <div className={`approval rise${closing === run.id ? " closing" : ""}`}>
          <div className="seal" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 22 22">
              <path d="M6 11.5l3.2 3.2L16 8" fill="none" stroke="currentColor"
                    strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="approval-main">
            <div className="approval-label">Approved by</div>
            <div className="approval-who" title={run.approved_by}>
              {run.approver_name}
            </div>
            <div className="approval-when">{stamp(run.approved_at)}</div>
          </div>
          <div className="approval-facts">
            <div>
              <div className="approval-label">Week</div>
              <div className="approval-value">{run.week}</div>
              <div className="approval-when">{weekRange(run.week)}</div>
            </div>
            <div>
              <div className="approval-label">Mailed</div>
              <div className="approval-value">{card.send_day}</div>
              <div className="approval-when">run #{run.id}</div>
            </div>
            {detail.run.working_days && (
              <div title="The month's working days the pace figures are projected on">
                <div className="approval-label">Paced on</div>
                <div className="approval-value">{detail.run.working_days} days</div>
                <div className="approval-when">
                  {detail.run.working_days_source === "entered"
                    ? "entered for the month" : "from the calendar"}
                </div>
              </div>
            )}
          </div>
          <ClearX title="Close" onClick={() => close(run.id)} />
        </div>
        )}

        {card.waiting && (
          <div className="waiting rise">
            <span className="pulse" aria-hidden="true" />
            {card.waiting.week} is built and waiting for approval. These figures
            are from {run.week} until it is approved.
            {user.is_admin && (
              <Link to={`/runs/${card.waiting.id}`}>Open the review</Link>
            )}
          </div>
        )}
      </>
    )} />
  );
}
