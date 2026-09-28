import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, count, monthName } from "../api";
import { Card, DataTable, ErrorBox, Loading, Segmented } from "../components";
import { col } from "../columns";
import Settlement, { SettlementTiles } from "../settlement";
import Collections, { CollectionsTiles } from "../collections";
import Delta from "../delta";
import Kpi from "../kpi";
import CaseAr from "../caseAr";
import { Button, LinkButton } from "../buttons";
import { DownloadIcon } from "../icons";

/* The dashboard: figures and tables, nothing else.

   A scorecard is read for its numbers, so the numbers are what is on screen.
   The only concession to shape is the tiles along the top - a single headline
   figure is clearer as a number than as anything drawn.

   One section at a time. The workbook puts six sheets in front of you at once
   and that is part of why it is hard to read; a segmented control keeps the
   page to one table. */

function useDashboard(runId) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [run, settlement, totals, pace, cp, kpi, meta,
               collections, collectionsPace, delta] = await Promise.all([
          api.run(runId),
          api.figures(runId, "settlement"),
          api.figures(runId, "settlement_totals"),
          /* Older runs were built before the Pace blocks existed and have no
             such figure. That is a missing section, not a broken dashboard,
             so these resolve to nothing rather than failing the whole page. */
          api.figures(runId, "settlement_pace").catch(() => []),
          api.figures(runId, "cp_settled"),
          api.figures(runId, "kpi"),
          api.figures(runId, "meta").catch(() => []),
          /* Collections is a produced TABLE, not figures - but a small one,
             one row per group per week per payment type. Fetched whole rather
             than paged, because the sheet's grid needs all of it at once. */
          api.table(runId, "collections", { limit: 5000 })
             .then((t) => t.data).catch(() => []),
          api.figures(runId, "collections_pace").catch(() => []),
          /* The delta rows, whole. The pivot and its filters are built from
             them in the browser, so they all have to be here - and there are
             hundreds, not hundreds of thousands. */
          api.table(runId, "delta_comparison", { limit: 5000 })
             .then((t) => t.data).catch(() => []),
        ]);
        alive && setState({ run, settlement, totals, pace, cp, kpi, meta,
                            collections, collectionsPace, delta,
                            loading: false });
      } catch (error) { alive && setState({ error, loading: false }); }
    })();
    return () => { alive = false; };
  }, [runId]);
  return state;
}

/* A page of one produced table, fetched when it is looked at. Raw Data is
   278,930 rows and stays where it is - only the page on screen crosses the
   wire, which is why this opens at once and the workbook does not. */
function TablePage({ runId, name, note }) {
  const [page, setPage] = useState(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);
  const limit = 50;

  /* Export the WHOLE table, not the page on screen. Raw Data is 278,930 rows
     and that is exactly the case someone needs a file for; exporting only the
     50 rows they happen to be looking at would be a trap. */
  async function exportCsv() {
    setExporting(true);
    try { await api.downloadCsv(runId, name); }
    catch (e) { setError(e); }
    finally { setExporting(false); }
  }

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

  /* Format by COLUMN, using the type the server sent - not per cell.
     A cell-by-cell guess put "$3,071" beside a bare "614" in one money column,
     because 614.0 is a whole number and 3070.59 is not. Identifiers are
     printed plain: 861,440 is not a quantity and should not wear a comma. */
  /* Identifiers, listed rather than matched. A pattern for "ends in id" also
     catches PAID, which is money. */
  const ID_COLUMNS = new Set(["caseid", "case_id", "businessregid", "regid",
                              "provider_id", "providerid", "mrn"]);
  const isId = (c) => {
    const k = c.trim().toLowerCase();
    return ID_COLUMNS.has(k) || k.endsWith("_id");
  };
  /* Built from the same column builders as every other table, so a figure in
     Raw Data is drawn like a figure on the Settlement sheet. An id is text
     that happens to be digits - it must never be grouped with thousands
     separators or read as money. */
  const columns = page.columns.map((c) => {
    const kind = page.kinds?.[c] ?? "text";
    if (kind === "text" || isId(c)) {
      return col.text(c, c, { render: (r) => (r[c] == null ? "" : String(r[c])) });
    }
    return kind === "float" ? col.money2(c, c) : col.count(c, c);
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

/* The run page: the scorecard of one particular build, reached from the run
   history or the review, with a way back to that review. */
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

/* The scorecard itself - tiles, tabs and tables - for any run. The page
   around it decides the heading: the run page names the build, the "This
   week" page names who approved it. */
export function ScorecardView({ id, header }) {
  const { run, settlement, totals, pace, cp, kpi, meta, collections,
          collectionsPace, delta, loading, error } = useDashboard(id);
  const [tab, setTab] = useState("settlement");

  /* Which month the run is reporting on, named. The pipeline records it, and
     the column headings need to say WHICH August this is. */
  const currentMonth = meta?.[0]?.current_month;
  const monthLabel = currentMonth
    ? `${monthName(currentMonth)}${meta[0].year ? ` ${meta[0].year}` : ""}`
    : null;

  if (loading) return <Loading what="Loading the scorecard" />;
  if (error) return <ErrorBox error={error} />;

  /* Sheet order, which is the order the workbook prints them and the order the
     people reading it expect. Raw Data sits last because it is the evidence
     under the others rather than one of them. */
  const tabs = [
    { value: "settlement", label: "Settlement" },
    { value: "collections", label: "Collections" },
    { value: "delta", label: "Delta" },
    /* The rows the Delta pivot is built from, beside it rather than under it:
       666 rows below the grid would bury the grid. */
    { value: "delta_comparison", label: "Delta raw data" },
    { value: "kpi", label: "KPI" },
    { value: "case_ar", label: "Case AR" },
    { value: "raw_data", label: "Raw data" },
  ];

  return (
    <>
      {header(run)}

      {/* The tiles follow the tab. On Settlement they are this month's, which
          is what the scorecard is reporting on; elsewhere they describe the
          run itself. A fixed row of headline figures that ignores what is on
          screen under it is furniture, not information. */}
      {tab === "settlement" ? (
        <SettlementTiles settlement={settlement} pace={pace} cp={cp}
                         monthLabel={monthLabel} currentMonth={currentMonth} />
      ) : tab === "collections" ? (
        <CollectionsTiles rows={collections} pace={collectionsPace}
                          monthLabel={monthLabel} />
      ) : (
        /* No other tab carries tiles. Delta's figure changes with every
           filter and the grid already shows it; raw rows are evidence, not a
           headline; KPI is eight categories at once; Case AR and Raw Data are
           tables to read, and tiles over them only pushed them down. */
        null
      )}

      <div className="spread" style={{ marginBottom: 18 }}>
        <Segmented options={tabs} value={tab} onChange={setTab} />
      </div>

      {tab === "settlement" && (
        <Settlement settlement={settlement} totals={totals} pace={pace}
                    cp={cp} monthLabel={monthLabel} />
      )}

      {tab === "kpi" && <Kpi kpi={kpi} monthLabel={monthLabel} />}

      {tab === "delta" && <Delta rows={delta} />}

      {tab === "collections" && (
        <Collections rows={collections} pace={collectionsPace}
                     monthLabel={monthLabel} />
      )}

      {tab === "case_ar" && <CaseAr runId={id} />}

      {["delta_comparison", "raw_data"].includes(tab) && (
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
