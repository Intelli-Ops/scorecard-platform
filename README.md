

## Accounts

Every route except sign-up, sign-in and the health check requires an account,
enforced by one dependency on the whole router rather than route by route.

Two company rules, checked in the API and not only in the form - a form can be
bypassed by opening the developer console:

  * the email must end `@appedology.com`
  * the APD id is `APD-` and exactly four digits (a bare `1234` is completed,
    lower case is accepted; anything else is refused)

Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user 16-byte salt at
240,000 iterations - standard library only, no dependency to keep patched. A
wrong email and a wrong password give the same message, so nobody can discover
which addresses have accounts.

Sessions are opaque tokens in a table rather than self-contained tokens,
because signing out has to actually revoke access. Who uploaded and who
approved are taken from the signed-in account, never from a field the caller
sets.

The health check stays open: a health check that needs credentials is not a
health check.

## A run's life after it is built

`review` -> `approved` is not one-way. **Unapprove** puts a run back to
`review`, clears the approver, and writes an `approval.withdrawn` note naming
who withdrew it and who had approved it. Rebuilding was the only way back
before, and a rebuild changes the run id that screenshots and emails already
point at.

**Delete** removes the run, cascades to its inputs, notes, figures and tables,
and takes the files with it - both the source uploads it read and the result
parquet it produced.

Both are reference counted rather than deleted outright, because both are
shared on purpose:

  * an upload belongs to the week, not to one run. The seven shared files feed
    both reports and every rebuild reads them again, so an upload goes only
    once no surviving run consumes it. Delete the GFS run and All Providers
    keeps its inputs; delete the last run for a week and the files go too. An
    upload no run ever read is left alone - it is not that run's to remove.
  * a result parquet another run also produced. Results are content-addressed,
    so two identical builds share one file; the blob is removed only once no
    `RunTable` row points at the hash.

The same holds one level down, at the bytes. Two `Upload` rows with identical
content share a single stored blob - Thursday's Case AR is often byte-for-byte
Tuesday's - so the blob is unlinked only after the last row naming it is gone.

The response says what went: `uploads_removed` counts rows, and
`upload_files_removed` counts blobs actually unlinked from disk.

A `pending` or `running` build cannot be deleted out from under the worker.

## Deleting a week

`DELETE /api/weeks/{week}` removes a week's builds AND every file uploaded for
it, and it exists because deleting builds one by one cannot get you back to a
clean slate.

Uploads outlive runs on purpose - they are the week's inputs, not one build's -
so a week whose builds have all been deleted keeps its files and goes on
offering a **Build** button with nothing behind it. Reference counting has
nothing left to count against at that point; only asking for the week itself
does anything.

Runs go first, so each retires what it alone was holding; whatever remains is
what no build ever read. Blobs are still reference counted across weeks: two
weeks that uploaded byte-identical files share one stored copy, and it is
unlinked only with the last week naming it.

The week must have no `pending` or `running` build. This cannot be undone - the
files would have to be uploaded again.

Both actions are open to anyone signed in. An admin-only rule needs a role on
the account first, which does not exist yet.

## Run history is bounded by weeks, not rows

`GET /api/runs?weeks=12`. A row limit cuts in the wrong place: rebuild one week
four times and a limit of 20 rows silently drops three older weeks off a list
that still calls itself a history.

## The Settlement tab follows the workbook

The sheet's shape is the reading order the client already has in their hands,
so the screen keeps it rather than inventing its own:

  * one column PAIR per month - Settlement Amount beside Settlement % - under a
    heading that spans the two, which is what stops a row of alternating
    headings turning into a wall;
  * the CURRENT month opened out into its weeks rather than summed, because the
    month is still running and the weeks are the news. Those columns are
    tinted the whole way down;
  * two totals, both amounts: the current month, and the year. Neither carries
    a per cent, because a per cent across a span of weeks is not the sum of
    theirs.
  * both blocks - In House and Board - on screen at once, as the sheet prints
    them. The block picker is gone.

The Total row's Settlement % is read from `settlement_totals`, never summed
from the column above it: it is the whole block's settled-plus-paid over its
billed, which is not the sum or the average of the group percentages.

## Pace

`Settlements (In House - Pace)` and `(Board - Pace)`, the run-rate the workbook
prints under each block: what has banked up to each week, divided by the
working days elapsed, times the working days in the month.

    cumulative / min(5 * week_index, business_days) * business_days

It is only ever the current month - there is nothing to project about a month
that has closed - and at month end the divisor reaches the multiplier, so the
last week of a finished month paces to exactly what it did.

It is emitted for both sheets - `settlement_pace` per block, and
`collections_pace` flat, because Collections has no In House / Board split.
Collections paces a group's whole WEEK rather than each payment type: that
is what the sheet does, and pacing one payment type is projecting noise.

The formula lives in `app/reports/pacing.py`. It was in the All Providers
collections module, which needed it first; the GFS settlement sheet asks the
same question of its own numbers, so it moved rather than being written twice.
`tests/test_pacing.py` checks it against four numbers read out of the delivered
Week-35 workbook.

## The Collections tab

Same manner as Settlement, one dimension different. Where Settlement opens the
current month into weeks and puts a Settlement % beside each, Collections opens
each WEEK into its four payment types and totals them:

    Wk 32                                        Wk 33 ...
    BILLING  REBILLING  APPEAL  SETTLEMENT  Total

Then the Pace block, then the payment-type footer the sheet prints under the
grid.

**What is deliberately missing: the closed months, January to July.** The
workbook carries one column each for them; `build_collections` produces the
current month only, so they are not there to show. The card says so rather than
leaving a reader to wonder. Filling them in means teaching the pipeline to read
the prior months - which is where the workbook itself gets them.

## Tabs are in sheet order

Settlement, Collections, Delta, KPI, Case AR, then Raw Data - the order the
workbook prints them, which is the order the people reading it expect. Raw Data
sits last because it is the evidence under the others rather than one of them.

## The Delta tab, and the rows beside it

Delta Comparison was made by hand: paste the delta rows into a sheet, drop a
pivot next to them, set the filters at the top, read the grid. That is what the
screen is - the filters, then the pivot they drive, then the rows themselves on
the tab next door.

The pivot is built IN THE BROWSER from the rows, not asked of the server. Two
things follow: a filter takes effect immediately, and the pivot can never
disagree with the raw tab beside it, because they are the same rows.

A column with only one value is not offered as a filter - `Type` is GFS for
every row, and a filter that cannot change anything is furniture. Aging is
offered in scale order (1-30, 31-60, 61-90, 90+); sorting those as text puts
90+ in the middle.

The tiles on this tab follow the filters. Filter to 90+ and the headline figure
is 90+'s, not the whole sheet's - tiles that ignore the control above them are
worse than no tiles.

**Verified against the workbook:** the grand total (558,199.10) and every
group's grand total reproduce exactly. The per-bucket aging split does NOT
match the layout workbook, and should not: `Aging` is relative to a date, that
file is a partial snapshot taken at a different one, and rows have aged between
buckets since. The column itself is covered by the golden master.

## KPI has no tiles

A tile is for a figure the whole page is about. This page is about eight
categories at once, and a headline over them would have to pick one or add them
together - the sum of an SBR count and a DDE count is not a number that means
anything.

Each category gets a table instead: who is in it, how many, and what share of
the category that is. The share is drawn as well as written, so a category that
is nearly all one group reads differently at a glance from one spread evenly -
which is what these blocks are looked at for, and what a column of bare counts
hides.

## Weeks are written out

`Week-33`, not `Wk 33`, everywhere. One definition, in `format.js`; it was
written twice and the two could drift.
