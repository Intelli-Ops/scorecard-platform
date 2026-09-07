import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, bucketLabel, bucketSort, count, money, monthName, pct } from "../api";
import {
  Card, ChartFrame, DataTable, ErrorBox, Loading, SERIES, Tile, Tip,
} from "../components";

/* The dashboard - what the client opens instead of the workbook.

   Choices worth stating:

   ONE AXIS, ALWAYS. Settlement amount and settlement % are different scales,
   so they are two charts, never one with two y-axes.

   TOP FIVE GROUPS, THEN "OTHER". There are more provider groups than a
   categorical palette can keep apart. The eight validated hues stay in fixed
   order and the tail folds into a single grey Other rather than inventing a
   ninth colour that a colourblind reader could not separate from the first.

   MONTHS THEN WEEKS. The report shows monthly totals for the year so far and
   weekly detail for the current month, so the x axis is ordered that way -
   sorting the raw labels as text would put Wk 32 before Feb. */

const OTHER = "Other";

/* Provider names run long ("United Services Plus", "SUPPORT CLAIMS WEST") and
   wrapped over three lines into the bars. Truncate on the axis; the tooltip
   still carries the full name. */
const shorten = (s) => (s.length > 18 ? s.slice(0, 17) + "…" : s);
const OTHER_COLOR = "var(--ink-muted)";
const TOP_N = 5;

function useFigures(runId) {
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

/* Rank groups once, by total settlement across the whole period, and keep that
   order everywhere. Colour then follows the group rather than its rank inside
   whichever block is on screen, so switching In House to Board does not
   repaint anything. */
function rankGroups(rows) {
  const total = {};
  for (const r of rows) total[r.group] = (total[r.group] ?? 0) + r.amount;
  return Object.entries(total).sort((a, b) => b[1] - a[1]).map(([g]) => g);
}

function pivot(rows, ranked, block) {
  const keep = new Set(ranked.slice(0, TOP_N));
  const byBucket = {};
  for (const r of rows) {
    if (r.block !== block) continue;
    const g = keep.has(r.group) ? r.group : OTHER;
    byBucket[r.bucket] ??= { bucket: r.bucket, label: bucketLabel(r.bucket) };
    byBucket[r.bucket][g] = (byBucket[r.bucket][g] ?? 0) + r.amount;
  }
  return Object.values(byBucket).sort((a, b) => bucketSort(a.bucket, b.bucket));
}

export default function Dashboard() {
  const { id } = useParams();
  const { run, settlement, totals, cp, kpi, loading, error } = useFigures(id);
  const [block, setBlock] = useState("In House");

  const ranked = useMemo(() => (settlement ? rankGroups(settlement) : []), [settlement]);
  const series = useMemo(() => {
    const top = ranked.slice(0, TOP_N);
    return [...top.map((g, i) => ({ name: g, color: SERIES[i] })),
            ...(ranked.length > TOP_N ? [{ name: OTHER, color: OTHER_COLOR }] : [])];
  }, [ranked]);

  const rows = useMemo(
    () => (settlement ? pivot(settlement, ranked, block) : []),
    [settlement, ranked, block]);

  const totalRows = useMemo(() => (totals ?? [])
    .filter((t) => t.block === block)
    .map((t) => ({ ...t, label: bucketLabel(t.bucket) }))
    .sort((a, b) => bucketSort(a.bucket, b.bucket)), [totals, block]);

  const kpiBlocks = useMemo(() => {
    const by = {};
    for (const k of kpi ?? []) (by[k.block] ??= []).push(k);
    for (const b of Object.values(by)) b.sort((a, c) => c.value - a.value);
    return by;
  }, [kpi]);

  if (loading) return <Loading what="Loading the dashboard" />;
  if (error) return <ErrorBox error={error} />;

  const blocks = [...new Set(settlement.map((r) => r.block))];
  const settledYtd = cp.reduce((s, m) => s + m.settled, 0);
  const casesYtd = cp.reduce((s, m) => s + m.cases, 0);
  const periodTotal = rows.reduce((s, r) => s + series.reduce(
    (t, g) => t + (r[g.name] ?? 0), 0), 0);

  return (
    <>
      <div className="head spread">
        <div>
          <h1>{run.run.report} · {run.run.week}</h1>
          <div className="sub">
            Run #{run.run.id} · {run.run.status}
            {run.run.approved_by && ` · approved by ${run.run.approved_by}`}
          </div>
        </div>
        <Link className="btn" to={`/runs/${id}`}>Review & warnings</Link>
      </div>

      <div className="grid cols-3" style={{ marginBottom: 16 }}>
        <Tile label={`Settlement — ${block}`} value={money(periodTotal)}
              foot="year to date, all groups" />
        <Tile label="CP settled cases" value={count(casesYtd)}
              foot={`${money(settledYtd)} settled`} />
        <Tile label="Raw Data rows"
              value={count(run.tables.find((t) => t.name === "raw_data")?.rows)}
              foot="kept out of the file, queried on demand" />
      </div>

      <div className="row" style={{ marginBottom: 12 }}>
        <label>Block</label>
        <select value={block} onChange={(e) => setBlock(e.target.value)}>
          {blocks.map((b) => <option key={b}>{b}</option>)}
        </select>
        <span className="mono">
          Months are totals; weeks are the current month's detail.
        </span>
      </div>

      <ChartFrame
        title={`Settlement amount — ${block}`}
        sub={`Top ${TOP_N} groups by total; the rest are grouped as Other.`}
        legend={series}
        table={
          <DataTable
            columns={[
              { key: "label", label: "Period" },
              ...series.map((g) => ({
                key: g.name, label: g.name, num: true,
                render: (r) => money(r[g.name]),
              })),
            ]}
            rows={rows}
          />
        }
      >
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={rows} margin={{ top: 6, right: 12, left: 6, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="label" stroke="var(--axis)"
                   tick={{ fill: "var(--ink-muted)", fontSize: 12 }} tickLine={false} />
            <YAxis stroke="var(--axis)" tickLine={false} axisLine={false}
                   tick={{ fill: "var(--ink-muted)", fontSize: 12 }}
                   tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<Tip format={money} />}
                     cursor={{ stroke: "var(--axis)" }} />
            {series.map((g) => (
              <Line key={g.name} type="monotone" dataKey={g.name} name={g.name}
                    stroke={g.color} strokeWidth={2} dot={false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </ChartFrame>

      <ChartFrame
        title={`Settlement % — ${block}, whole block`}
        sub="The Total row: the block's settlement plus paid, over the block's billed. Not an average of the group percentages."
        table={
          <DataTable
            columns={[
              { key: "label", label: "Period" },
              { key: "settlement_pct", label: "Settlement %", num: true,
                render: (r) => pct(r.settlement_pct) },
            ]}
            rows={totalRows}
          />
        }
      >
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={totalRows} margin={{ top: 6, right: 12, left: 6, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="label" stroke="var(--axis)" tickLine={false}
                   tick={{ fill: "var(--ink-muted)", fontSize: 12 }} />
            <YAxis stroke="var(--axis)" tickLine={false} axisLine={false}
                   tick={{ fill: "var(--ink-muted)", fontSize: 12 }}
                   tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
            <Tooltip content={<Tip format={pct} />} cursor={{ stroke: "var(--axis)" }} />
            <Line type="monotone" dataKey="settlement_pct" name="Settlement %"
                  stroke="var(--series-1)" strokeWidth={2} dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} />
          </LineChart>
        </ResponsiveContainer>
      </ChartFrame>

      <div className="grid cols-2">
        <ChartFrame
          title="CP settled cases"
          sub="From the Hearing Calendar, by month."
          table={
            <DataTable
              columns={[
                { key: "month", label: "Month", render: (r) => monthName(r.month) },
                { key: "cases", label: "Cases", num: true },
                { key: "settled", label: "Settled", num: true,
                  render: (r) => money(r.settled) },
                { key: "outstanding", label: "Outstanding", num: true,
                  render: (r) => money(r.outstanding) },
              ]}
              rows={cp}
            />
          }
        >
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={cp.map((m) => ({ ...m, label: monthName(m.month) }))}
                      margin={{ top: 6, right: 12, left: 6, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="label" stroke="var(--axis)" tickLine={false}
                     tick={{ fill: "var(--ink-muted)", fontSize: 12 }} />
              <YAxis stroke="var(--axis)" tickLine={false} axisLine={false}
                     tick={{ fill: "var(--ink-muted)", fontSize: 12 }}
                     tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip content={<Tip format={money} />}
                       cursor={{ fill: "var(--grid)", fillOpacity: .4 }} />
              <Bar dataKey="settled" name="Settled" fill="var(--series-1)"
                   radius={[4, 4, 0, 0]} maxBarSize={38} />
            </BarChart>
          </ResponsiveContainer>
        </ChartFrame>

      </div>

      <h2 style={{ marginTop: 24 }}>KPI blocks</h2>
      <div className="grid cols-3">
        {Object.entries(kpiBlocks).map(([name, values]) => (
          <ChartFrame
            key={name}
            title={name}
            sub={`${values.length} groups`}
            table={
              <DataTable
                columns={[{ key: "group", label: "Group" },
                          { key: "value", label: name, num: true,
                            render: (r) => count(r.value) }]}
                rows={values}
              />
            }
          >
            <ResponsiveContainer width="100%" height={Math.max(150, values.length * 22)}>
              <BarChart data={values} layout="vertical"
                        margin={{ top: 2, right: 40, left: 4, bottom: 2 }}>
                <CartesianGrid stroke="var(--grid)" horizontal={false} />
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="group" width={132}
                       stroke="var(--axis)" tickLine={false} axisLine={false}
                       interval={0}
                       tick={{ fill: "var(--ink-muted)", fontSize: 11 }}
                       tickFormatter={shorten} />
                <Tooltip content={<Tip format={count} />}
                         cursor={{ fill: "var(--grid)", fillOpacity: .4 }} />
                {/* One series, so one hue: the bars encode magnitude, not
                    identity, and the group is already on the axis. */}
                {/* minPointSize gives a zero a 2px stub so its "0" label has
                    something to sit beside. Without it Recharts draws nothing
                    and a genuine zero reads as a missing figure. */}
                <Bar dataKey="value" name={name} fill="var(--series-1)"
                     radius={[0, 4, 4, 0]} barSize={11} minPointSize={2}>
                  {values.map((v) => (
                    <Cell key={v.group}
                          fill={v.value ? "var(--series-1)" : "var(--grid)"} />
                  ))}
                  {/* The number beside the bar. A KPI block is read for its
                      value, not its shape, and several of these are zero -
                      which a bar of no length cannot say out loud. */}
                  <LabelList dataKey="value" position="right"
                             fill="var(--ink-2)" fontSize={11}
                             formatter={(v) => count(v)} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartFrame>
        ))}
      </div>
    </>
  );
}
