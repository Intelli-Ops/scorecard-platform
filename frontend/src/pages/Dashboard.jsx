// One build's scorecard: tiles, tabs and tables.
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, count, monthName } from "../api";
import { Card, DataTable, ErrorBox, Loading, PartialNotice, Segmented } from "../components";
import { col } from "../columns";
import Settlement, { SettlementTiles } from "../settlement";
import Collections, { CollectionsTiles } from "../collections";
import Delta from "../delta";
import DeltaComparison from "../deltaComparison";
import CollectionsHistory from "../collectionsHistory";
import { rowsOf } from "../layout";
import Kpi from "../kpi";
import CaseAr from "../caseAr";
import PaceFormula from "../pace";
import { Button, LinkButton } from "../buttons";
import { DownloadIcon } from "../icons";
import { useLoad } from "../hooks";

// The dashboard: figures and tables, nothing else.

function useDashboard(runId) {
  const { data, error } = useLoad(async () => {
    const [run, settlement, totals, pace, cp, kpi, meta,
           collections, collectionsPace, delta, monthWeeks, layout] = await Promise.all([
      api.run(runId),
      api.figures(runId, "settlement"),
      api.figures(runId, "settlement_totals"),
      api.figures(runId, "settlement_pace").catch(() => []),
      api.figures(runId, "cp_settled"),
      api.figures(runId, "kpi"),
      api.figures(runId, "meta").catch(() => []),
      api.table(runId, "collections", { limit: 5000 })
         .then((t) => t.data).catch(() => []),
      api.figures(runId, "collections_pace").catch(() => []),
      api.table(runId, "delta_comparison", { limit: 5000 })
         .then((t) => t.data).catch(() => []),
      api.figures(runId, "settlement_month_weeks").catch(() => []),
      api.figures(runId, "layout").catch(() => []),     // builds before it have none
    ]);
    return { run, settlement, totals, pace, cp, kpi, meta,
             collections, collectionsPace, delta, monthWeeks, layout };
  }, [runId]);
  if (error) return { error, loading: false };
  return data ? { ...data, loading: false } : { loading: true };
}

const ID_COLUMNS = new Set(["caseid", "case_id", "businessregid", "regid",
                            "provider_id", "providerid", "mrn"]);
const isId = (c) => {
  const k = c.trim().toLowerCase();
  return ID_COLUMNS.has(k) || k.endsWith("_id");
};
const PAGE = 50;

// A page of one produced table, fetched when it is looked at.
function TablePage({ runId, name, note }) {
  const [offset, setOffset] = useState(0);
  const [exporting, setExporting] = useState(false);
  const limit = PAGE;
  const { data: page, error, setError } =
    useLoad(() => api.table(runId, name, { limit, offset }), [runId, name, offset]);

  async function exportCsv() {
    setExporting(true);
    try { await api.downloadCsv(runId, name); }
    catch (e) { setError(e); }
    finally { setExporting(false); }
  }

  if (error) return <ErrorBox error={error} />;
  if (!page) return <Loading />;

  const columns = page.columns.map((c) => {
    const kind = page.kinds?.[c] ?? "text";
    if (kind === "text" || isId(c)) {
      return col.text(c, c, { render: (r) => (r[c] == null ? "" : String(r[c])) });
    }
    return kind === "float" ? col.money(c, c) : col.count(c, c);
  });

  const pages = Math.max(1, Math.ceil(page.rows / limit));
  const current = Math.floor(offset / limit);

  return (
    <Card flush
          title={name.replace(/_/g, " ")}
          sub={`${count(page.rows)} rows${note ? ` · ${note}` : ""}`}
          right={
            <div className="row">
              {page.rows > limit && (
                <>
                  <Button size="sm" disabled={current === 0}
                          onClick={() => setOffset(Math.max(0, offset - limit))}>
                    Previous
                  </Button>
                  <span className="small muted">{current + 1} of {count(pages)}</span>
                  <Button size="sm" disabled={current >= pages - 1}
                          onClick={() => setOffset(offset + limit)}>
                    Next
                  </Button>
                </>
              )}
              <Button size="sm" icon={<DownloadIcon />} onClick={exportCsv}
                      busy={exporting} busyLabel="Preparing…">
                Export CSV
              </Button>
            </div>
          }>
      <DataTable columns={columns} rows={page.data} />
    </Card>
  );
}

// The run page: the scorecard of one particular build, reached from the run history or the review, with a way back to that review.
export default function Dashboard() {
  const { id } = useParams();
  return (
    <ScorecardView id={id} header={(run) => (
      <div className="head spread">
        <div>
          <h1>{run.run.report}</h1>
          <div className="sub">
            {run.run.week} · run #{run.run.id} · {run.run.status}
            {run.run.approved_by && ` · approved by ${run.run.approved_by}`}
            {run.run.working_days && ` · paced on ${run.run.working_days} working days`}
          </div>
        </div>
        <LinkButton to={`/runs/${id}`}>Review</LinkButton>
      </div>
    )} />
  );
}

// The scorecard itself - tiles, tabs and tables - for any run.
export function ScorecardView({ id, header }) {
  const { run, settlement, totals, pace, cp, kpi, meta, collections,
          collectionsPace, delta, monthWeeks, layout, loading, error } = useDashboard(id);
  const [tab, setTab] = useState("settlement");

  const currentMonth = meta?.[0]?.current_month;
  const monthLabel = currentMonth
    ? `${monthName(currentMonth)}${meta[0].year ? ` ${meta[0].year}` : ""}`
    : null;
  const spans = meta?.[0]?.week_spans;

  if (loading) return <Loading what="Loading the scorecard" />;
  if (error) return <ErrorBox error={error} />;

  // All Providers: its Delta tab is already the whole Delta Comparison sheet, so there
  // is no raw data behind it to show, and its settlement has no Settlement %.
  const allProviders = run.run.report_key === "all_providers";
  const tabs = [
    { value: "settlement", label: "Settlement" },
    { value: "collections", label: "Collections" },
    { value: "delta", label: "Delta" },
    ...(allProviders ? [] : [{ value: "delta_comparison", label: "Delta raw data" }]),
    { value: "kpi", label: "KPI" },
    { value: "case_ar", label: "Case AR" },
    { value: "raw_data", label: "Raw data" },
  ];

  return (
    <>
      {header(run)}
      <PartialNotice missing={run.run.missing} />

      <div className="spread" style={{ marginBottom: 18 }}>
        <Segmented options={tabs} value={tab} onChange={setTab} />
      </div>

      {tab === "settlement" ? (
        <SettlementTiles settlement={settlement} pace={pace} cp={cp}
                         monthLabel={monthLabel} currentMonth={currentMonth} />
      ) : tab === "collections" ? (
        <CollectionsTiles rows={collections} pace={collectionsPace}
                          monthLabel={monthLabel} />
      ) : (
        null
      )}

      {tab === "settlement" && (
        <Settlement settlement={settlement} totals={totals} pace={pace}
                    cp={cp} monthLabel={monthLabel} monthWeeks={monthWeeks}
                    spans={spans} currentMonth={currentMonth}
                    layout={layout} year={meta?.[0]?.year} pct={!allProviders} />
      )}

      {tab === "kpi" && <Kpi kpi={kpi} monthLabel={monthLabel} layout={layout} />}

      {tab === "delta" && (allProviders
        ? <DeltaComparison rows={delta} order={rowsOf(layout, "delta")}
                           currentMonth={currentMonth} year={meta?.[0]?.year} />
        : <Delta rows={delta} dorOrder={rowsOf(layout, "dor")} />)}

      {tab === "collections" && (
        <Collections rows={collections} pace={collectionsPace}
                     monthLabel={monthLabel} spans={spans}
                     currentMonth={currentMonth} order={rowsOf(layout, "collections")} />
      )}

      {["settlement", "collections"].includes(tab) && (
        <PaceFormula meta={meta} monthLabel={monthLabel} />
      )}

      {tab === "collections" && <CollectionsHistory runId={id} />}

      {tab === "case_ar" && <CaseAr runId={id} />}

      {["delta_comparison", "raw_data"].includes(tab) && (
        <TablePage
          key={tab} runId={id} name={tab}
          note={tab === "raw_data"
            ? "hidden inside the workbook; here it is simply a table"
            : null}
        />
      )}
    </>
  );
}
