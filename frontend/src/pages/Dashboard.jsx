import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, bucketLabel, bucketSort, count, money, monthName, pct } from "../api";
import { Card, DataTable, ErrorBox, Loading, Segmented, Tile } from "../components";

/* The dashboard: figures and tables, nothing else.

   A scorecard is read for its numbers, so the numbers are what is on screen.
   The only concession to shape is the tiles along the top - a single headline
   figure is clearer as a number than as anything drawn.

   One section at a time. The workbook puts six sheets in front of you at once
   and that is part of why it is hard to read; a segmented control keeps the
   page to one table. */

const TOTAL = "Total";

function useDashboard(runId) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [run, settlement, totals, cp, kpi] = await Promise.all([
          api.run(runId),
          api.figures(runId, "settlement"),
          api.figures(runId, "settlement_totals"),
          api.figures(runId, "cp_settled"),
          api.figures(runId, "kpi"),
        ]);
        alive && setState({ run, settlement, totals, cp, kpi, loading: false });
      } catch (error) { alive && setState({ error, loading: false }); }
    })();
    return () => { alive = false; };
  }, [runId]);
  return state;
}

/* One row per group, one column per period, plus a Total row. The buckets are
   the sheet's own: months for the year so far, then the current month's weeks. */
function pivotSettlement(rows, block) {
  const inBlock = rows.filter((r) => r.block === block);
  const buckets = [...new Set(inBlock.map((r) => r.bucket))].sort(bucketSort);
  const byGroup = {};
  for (const r of inBlock) {
    (byGroup[r.group] ??= { group: r.group, _total: 0 });
    byGroup[r.group][r.bucket] = (byGroup[r.group][r.bucket] ?? 0) + r.amount;
    byGroup[r.group]._total += r.amount;
  }
  const body = Object.values(byGroup).sort((a, b) => b._total - a._total);
  const total = { group: TOTAL, _total: 0 };
  for (const b of buckets) {
    total[b] = body.reduce((s, g) => s + (g[b] ?? 0), 0);
    total._total += total[b];
  }
  return { buckets, rows: [...body, total] };
}

/* A page of one produced table, fetched when it is looked at. Raw Data is
   278,930 rows and stays where it is - only the page on screen crosses the
   wire, which is why this opens at once and the workbook does not. */
function TablePage({ runId, name, note }) {
  const [page, setPage] = useState(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState(null);
  const limit = 50;

  useEffect(() => { setOffset(0); }, [name]);

  useEffect(() => {
    let alive = true;
    setPage(null);
    api.table(runId, name, { limit, offset })
      .then((p) => alive && setPage(p))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [runId, name, offset]);

  if (error) return <ErrorBox error={error} />;
  if (!page) return <Loading />;

  const columns = page.columns.map((c) => ({
    key: c, label: c,
    num: page.data.length > 0 && typeof page.data[0][c] === "number",
    render: (r) => {
      const v = r[c];
      if (v == null) return "";
      if (typeof v !== "number") return String(v);
      return Number.isInteger(v) ? count(v) : money(v);
    },
  }));

  const pages = Math.max(1, Math.ceil(page.rows / limit));
  const current = Math.floor(offset / limit);

  return (
    <Card flush
          title={name.replace(/_/g, " ")}
          sub={`${count(page.rows)} rows${note ? ` · ${note}` : ""}`}
          right={page.rows > limit && (
            <div className="row">
              <button className="small" disabled={current === 0}
                      onClick={() => setOffset(Math.max(0, offset - limit))}>
                Previous
              </button>
              <span className="small muted">{current + 1} of {count(pages)}</span>
              <button className="small" disabled={current >= pages - 1}
                      onClick={() => setOffset(offset + limit)}>
                Next
              </button>
            </div>
          )}>
      <DataTable columns={columns} rows={page.data} />
    </Card>
  );
}

export default function Dashboard() {
  const { id } = useParams();
  const { run, settlement, totals, cp, kpi, loading, error } = useDashboard(id);
  const [tab, setTab] = useState("settlement");
  const [block, setBlock] = useState(null);

  const blocks = useMemo(
    () => [...new Set((settlement ?? []).map((r) => r.block))], [settlement]);
  const current = block ?? blocks[0];

  const pivot = useMemo(
    () => (settlement && current
      ? pivotSettlement(settlement, current)
      : { buckets: [], rows: [] }),
    [settlement, current]);

  const totalRows = useMemo(() => (totals ?? [])
    .filter((t) => t.block === current)
    .sort((a, b) => bucketSort(a.bucket, b.bucket)), [totals, current]);

  const kpiBlocks = useMemo(() => {
    const by = {};
    for (const k of kpi ?? []) (by[k.block] ??= []).push(k);
    for (const v of Object.values(by)) v.sort((a, b) => b.value - a.value);
    return by;
  }, [kpi]);

  if (loading) return <Loading what="Loading the scorecard" />;
  if (error) return <ErrorBox error={error} />;

  const settledYtd = cp.reduce((s, m) => s + m.settled, 0);
  const casesYtd = cp.reduce((s, m) => s + m.cases, 0);
  const grand = pivot.rows.find((r) => r.group === TOTAL)?._total ?? 0;
  const rawRows = run.tables.find((t) => t.name === "raw_data")?.rows;

  const tabs = [
    { value: "settlement", label: "Settlement" },
    { value: "kpi", label: "KPI" },
    { value: "cp", label: "CP settled" },
    { value: "collections", label: "Collections" },
    { value: "case_ar", label: "Case AR" },
    { value: "delta_comparison", label: "Delta" },
    { value: "raw_data", label: "Raw data" },
  ];

  return (
    <>
      <div className="head spread">
        <div>
          <h1>{run.run.report}</h1>
          <div className="sub">
            {run.run.week} · run #{run.run.id} · {run.run.status}
            {run.run.approved_by && ` · approved by ${run.run.approved_by}`}
          </div>
        </div>
        <Link className="btn" to={`/runs/${id}`}>Review</Link>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 26 }}>
        <Tile label={`Settlement · ${current ?? ""}`} value={money(grand)}
              foot="year to date, all groups" />
        <Tile label="CP settled cases" value={count(casesYtd)}
              foot={`${money(settledYtd)} settled`} />
        <Tile label="Provider groups"
              value={count(new Set((kpi ?? []).map((k) => k.group)).size)}
              foot={`across ${Object.keys(kpiBlocks).length} KPI blocks`} />
        <Tile label="Raw data rows" value={count(rawRows)}
              foot="queried on demand" />
      </div>

      <div className="spread" style={{ marginBottom: 18 }}>
        <Segmented options={tabs} value={tab} onChange={setTab} />
        {tab === "settlement" && blocks.length > 1 && (
          <div className="row">
            <label>Block</label>
            <select value={current} onChange={(e) => setBlock(e.target.value)}>
              {blocks.map((b) => <option key={b}>{b}</option>)}
            </select>
          </div>
        )}
      </div>

      {tab === "settlement" && (
        <>
          <Card flush title={`Settlement · ${current}`}
                sub="Months are totals for the year so far; weeks are the current month.">
            <DataTable
              isTotal={(r) => r.group === TOTAL}
              columns={[
                { key: "group", label: "Group", strong: true },
                ...pivot.buckets.map((b) => ({
                  key: b, label: bucketLabel(b), num: true,
                  render: (r) => (r[b] ? money(r[b]) : "—"),
                })),
                { key: "_total", label: "Total", num: true, strong: true,
                  render: (r) => money(r._total) },
              ]}
              rows={pivot.rows}
            />
          </Card>

          {totalRows.length > 0 && (
            <Card flush title="Settlement %"
                  sub="The whole block's settlement plus paid, over its billed — not an average of the group percentages.">
              <DataTable
                columns={[
                  { key: "bucket", label: "Period", strong: true,
                    render: (r) => bucketLabel(r.bucket) },
                  { key: "settlement_pct", label: "Settlement %", num: true,
                    render: (r) => pct(r.settlement_pct) },
                ]}
                rows={totalRows}
              />
            </Card>
          )}
        </>
      )}

      {tab === "kpi" && (
        <div className="grid cols-2">
          {Object.entries(kpiBlocks).map(([name, values]) => {
            const sum = values.reduce((s, v) => s + v.value, 0);
            return (
              <Card key={name} flush title={name}
                    sub={`${values.length} groups`}>
                <DataTable
                  isTotal={(r) => r.group === TOTAL}
                  columns={[
                    { key: "group", label: "Group" },
                    { key: "value", label: "Value", num: true,
                      render: (r) => count(r.value) },
                  ]}
                  rows={[...values, { group: TOTAL, value: sum }]}
                />
              </Card>
            );
          })}
        </div>
      )}

      {tab === "cp" && (
        <Card flush title="CP settled cases"
              sub="From the Hearing Calendar, by month.">
          <DataTable
            isTotal={(r) => r.month === TOTAL}
            columns={[
              { key: "month", label: "Month", strong: true,
                render: (r) => (r.month === TOTAL ? TOTAL : monthName(r.month)) },
              { key: "cases", label: "Cases", num: true,
                render: (r) => count(r.cases) },
              { key: "settled", label: "Settled", num: true,
                render: (r) => money(r.settled) },
              { key: "outstanding", label: "Outstanding", num: true,
                render: (r) => money(r.outstanding) },
            ]}
            rows={[...cp, {
              month: TOTAL, cases: casesYtd, settled: settledYtd,
              outstanding: cp.reduce((s, m) => s + m.outstanding, 0),
            }]}
          />
        </Card>
      )}

      {["collections", "case_ar", "delta_comparison", "raw_data"].includes(tab) && (
        <TablePage
          runId={id} name={tab}
          note={tab === "raw_data"
            ? "hidden inside the workbook; here it is simply a table"
            : null}
        />
      )}
    </>
  );
}
