// Reviewing a build before approving it.
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, count, when } from "../api";
import { Card, ErrorBox, Loading, Notes, PartialNotice, Stat, Status } from "../components";
import { Button, ConfirmButton, LinkButton } from "../buttons";
import { CheckIcon } from "../icons";

// The review: what a person has to check before the report goes out.
export default function Review() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);             // the run would not load
  const [actionError, setActionError] = useState(null); // a button did not work
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true, timer;
    const tick = async () => {
      try {
        const d = await api.run(id);
        if (!alive) return;
        setData(d);
        if (["pending", "running"].includes(d.run.status)) {
          timer = setTimeout(tick, 1500);
        }
      } catch (e) { if (alive) setError(e); }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  const act = (fn) => async () => {
    setBusy(true); setActionError(null);
    try {
      await fn(id);
      setData(await api.run(id));
    } catch (e) { setActionError(e); }
    finally { setBusy(false); }
  };
  const approve = act(api.approve);
  const unapprove = act(api.unapprove);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="Loading the run" />;

  const run = data.run;

  if (["pending", "running"].includes(run.status)) {
    return (
      <>
        <div className="head">
          <h1>{run.week}</h1>
          <div className="sub">
            {run.status === "pending" ? "Queued." : "Reading the files and working out the numbers."}
            {" "}This takes about a minute. The page updates itself.
          </div>
        </div>
        <Card><Status value={run.status} /></Card>
      </>
    );
  }

  if (run.status === "failed") {
    return (
      <>
        <div className="head"><h1>{run.week} · failed</h1></div>
        <Card><div className="err">{run.error}</div></Card>
      </>
    );
  }

  const bySection = (key) => data.notes.filter((n) => n.section === key);
  const providers = bySection("providers");
  const noData = bySection("no_data");
  const duplicates = bySection("duplicates");
  const other = bySection("other");
  const open = (notes) => notes.filter((n) => n.change !== "resolved since last week").length;

  const SECTIONS = [
    { title: "New providers", notes: providers,
      sub: "Providers or groups this week's data has that the report had no row for, and whether their figures were added.",
      empty: "No new providers this week." },
    { title: "No data for the week", notes: noData,
      sub: "Figures the report shows that had nothing to go on this week.",
      empty: "Every figure had data this week." },
    { title: "Duplicate case IDs", notes: duplicates,
      sub: "Case IDs that appear more than once in Delta Comparison.",
      empty: "No duplicate case IDs." },
  ];

  return (
    <>
      <div className="head spread">
        <div>
          <h1>{run.report}</h1>
          <div className="sub">
            {run.week} · run #{run.id} · built in {run.seconds?.toFixed(0)}s ·{" "}
            {data.compared_with
              ? `compared with ${data.compared_with.week}`
              : "no earlier week to compare with"}
          </div>
        </div>
        <div className="row">
          <Status value={run.status} />
          {run.status === "review" && run.missing?.length ? (
            <ConfirmButton tone="primary" size="md" icon={<CheckIcon />}
                           label="Approve partial" confirm="Approve without them"
                           busyLabel="Approving…" onConfirm={approve}
                           title={`Missing: ${run.missing.join(", ")}`} />
          ) : run.status === "review" ? (
            <Button tone="primary" icon={<CheckIcon />} onClick={approve}
                    busy={busy} busyLabel="Approving…">
              Approve
            </Button>
          ) : run.status === "approved" ? (
            <>
              <span className="small muted">
                approved by {run.approved_by} · {when(run.approved_at)}
              </span>
              <Button tone="soft" onClick={unapprove} busy={busy} busyLabel="Working…">
                Unapprove
              </Button>
            </>
          ) : null}
          <LinkButton to={`/dashboard/${run.id}`}>Open scorecard</LinkButton>
        </div>
      </div>

      <ErrorBox error={actionError} />
      <PartialNotice missing={run.missing} />

      <div className="grid cols-4" style={{ marginBottom: 26 }}>
        <Stat label="Needs attention" value={data.needs_attention ? "Yes" : "No"}
              foot={data.needs_attention ? "check the items below" : "nothing new or blocking"} />
        <Stat label="New providers" value={count(open(providers))}
              foot={open(providers) ? "check where their figures landed" : "none this week"} />
        <Stat label="No data" value={count(open(noData))}
              foot={open(noData) ? "figures with nothing behind them" : "every figure had data"} />
        <Stat label="Duplicate case IDs" value={count(duplicates.reduce(
                (s, n) => s + (n.change === "resolved since last week" ? 0 : n.detail?.count ?? 0), 0))}
              foot="in Delta Comparison" />
      </div>

      {SECTIONS.map((sec) => (
        <Card flush key={sec.title} title={sec.title} sub={sec.sub}>
          <div style={{ padding: "4px 22px 10px" }}>
            <Notes notes={sec.notes} empty={sec.empty} />
          </div>
        </Card>
      ))}

      {other.length > 0 && (
        <Card flush title="Other">
          <div style={{ padding: "4px 22px 10px" }}>
            <Notes notes={other} />
          </div>
        </Card>
      )}
    </>
  );
}
