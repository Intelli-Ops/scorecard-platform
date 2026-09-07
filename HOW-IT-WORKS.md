# How the Scorecard app works

A plain-English guide. No technical background needed.

---

## 1. What this replaces

**Before.** Every week you opened a folder of files, ran `RUN-WEEK.bat`, waited,
read some messages in a black window, and emailed the client a 21 MB Excel file.
That worked, but:

- it only ran on one laptop, in one folder
- the messages disappeared when you closed the window
- nobody could see last week's run without opening last week's folder
- the client had to open a heavy file that takes 20 seconds to load

**Now.** You open a web page, drag the files in, press **Build**, read what it
found, press **Approve**, and send a link.

The numbers are exactly the same. That was checked — see section 9.

---

## 2. The whole thing in one picture

```
   You                          The app                        The client
   ───                          ───────                        ──────────

   drag files in    ────▶   keeps the files safely
                            works out the numbers
                            writes down what it found

   read the warnings ◀────   "1 figure is missing a source"

   press Approve    ────▶   marks it signed off, with your name

                            shows the finished scorecard  ────▶  opens a link
```

Three things happen: **files go in**, **numbers come out**, **a person checks
them before they go to the client.**

---

## 3. Getting an account

The app is for Appedology staff only, and it checks that itself.

**First time.** Open `http://localhost:5173`, click **Create one**, and give
three things:

| | |
|---|---|
| Work email | must end **@appedology.com** |
| APD ID | your internal ID — **APD-1234**, four digits |
| Password | at least 8 characters |

Then you are signed in straight away.

Two things it will not accept:

```
someone@gmail.com    ->  Use your Appedology email - it must end @appedology.com.
APD-123              ->  The APD ID looks like APD-1234 - four digits.
```

Small kindnesses: the email is not case-sensitive, and if you type just `1234`
it fills in the `APD-` for you.

**After that.** Sign in with your email and password. You stay signed in for
two weeks unless you press **Sign out**, which is at the bottom of the sidebar
next to your email and APD ID.

**Your password is never stored.** What is kept is a scrambled version that
cannot be turned back into your password, with a random ingredient unique to
your account — so two people with the same password still have different
stored values.

**Everything is behind the sign-in.** Not just the screens: the data itself.
Nobody can fetch a number without an account, so there is no way round the
login page.

Two more things now come from your account rather than being typed:

- **who uploaded** each file
- **who approved** each report

Both appear on the review page and in the run history.

---

## 4. Your week, step by step

### Tuesday — the GFS report

**Step 1. Open the app.** Go to `http://localhost:5173`, sign in, and click
**Upload a week**.

**Step 2. Set the week.** The box shows something like `2026-W36`. It fills in
this week automatically, so usually you leave it alone.

**Step 3. Say who the Case ARs are for.** Pick **GFS · Tuesday** from the
dropdown on the right.

> **Why it asks.** Case AR files are made fresh every day. GFS goes out Tuesday
> and uses Tuesday's copy; All Providers goes out Thursday and uses Thursday's.
> Both files are called `Combined Owner Case AR.xlsb` — same name, different
> file. If the app guessed and got it wrong, Thursday's cases would end up in
> Tuesday's report and **nothing in the file would ever show it.** So it asks.

**Step 4. Drag all the files in at once.** Don't rename them. Don't tidy the
folder. A progress bar shows the upload — it is about 385 MB, so give it a
minute.

When it finishes you see exactly what it took:

```
ACCEPTED   Combined Owner Case AR      Combined Owner Case AR.xlsb        46.2 MB
ACCEPTED   Combined Custom Case AR     Combined Custom  Case AR.xlsb     239.7 MB
ACCEPTED   Supporting File             Supporting File.xlsx                3.6 MB
ACCEPTED   Payment Detail Report       Payment Detail Report for 01st…     9.1 MB
…

IGNORED    GFS - Weekly Scorecard (Week -35) 2026 - Partial.xlsx
           not one of the report inputs
```

That last line matters. Your week folder always has old workbooks sitting
alongside the real inputs. **The app knows the difference and refuses to read
the wrong one.**

**Step 5. Press Build.** The GFS card turns from "8 still needed" to a **Build**
button once everything is there.

**Step 6. Read the review page** (section 5 below), then press **Approve**.

**Step 7. Email the client the link.**

### Thursday — the All Providers report

Almost nothing to do:

**Step 1.** Same week number.

**Step 2.** Pick **All Providers · Thursday** from the dropdown.

**Step 3.** Drag in just **three** files:
- `Combined Owner Case AR.xlsb` — Thursday's copy
- `Combined Custom Case AR.xlsb` — Thursday's copy
- `All Provider - Weekly Score Card (Week-35) 2026.xlsx` — last week's workbook

**You do not re-upload the other seven.** They went up on Tuesday and are shared.
The screen already shows them as held.

> **Why All Providers needs last week's workbook.** Its KPI section changes shape
> — the provider list grows when you take on a new provider, and it gains a
> column every week of the month. So instead of guessing the layout, the app
> reads it out of last week's finished file. (It does not open Excel to do this.
> An `.xlsx` is really just a zipped folder of text.)

**Step 4.** Press **Build** on the All Providers card. Review. Approve. Send.

---

## 5. What happens when you press Build

You press the button. **It comes back in under a second.**

That does *not* mean it's finished. It means the job is queued. The work
happens in the background and the page keeps itself up to date:

```
  0 seconds     pending      queued, nothing started
  2 seconds     running      reading the files
 67 seconds     review       finished — waiting for you
```

**Why it works this way.** Reading 385 MB takes about a minute. A web page
cannot sit and wait that long — the browser would give up. So the app says
"started", and the page checks back every couple of seconds until it's done.

**One build at a time, on purpose.** Two at once would each be holding a
quarter-gigabyte spreadsheet in memory, and the reports go out on different
days anyway.

**The second build of the same week takes about 3 seconds.** After the first
read, the app keeps a fast copy of what it read. So if you change a rule and
rebuild, you're not waiting another minute.

Notice the status is **`review`**, not "done". A build never finishes by itself.
A person has to look at it.

---

## 6. The four screens

### Upload a week

Drag files in. Shows what's held, what's missing, and a **Build** button per
report once everything's there.

### Review — the important one

This is the "things worth your eyes" step, with somewhere to live.

Four figures across the top:

```
Needs attention     Warnings     Rows produced     Files read
      Yes               3           279,667             9
1 figure missing                    4 tables      each pinned to
    a source                                       its exact bytes
```

Then what the run wants to tell you, worst first:

```
ACTION    KPI blocks left without a figure — no column for them in the
          KPI-numbers file: 10635 (DDEL)

WARNING   112,960 AR rows dropped — provider not in the Provider List
          (regids [56, 57, 67, 70, 96, 97])

WARNING   1 duplicate case id(s) in Delta Comparison

NOTE      414,413 GFS cases, 56 providers
```

Three levels, and they mean different things:

| | What it means |
|---|---|
| **ACTION** | A number the client will look at isn't there. You decide whether to send anyway. |
| **WARNING** | Rows were dropped or corrected. Normal every week — **the count is the thing to watch.** |
| **NOTE** | Just context. Nothing wrong. |

**Here's the part your old system could never do.** From the second week
onwards, each warning tells you what changed:

```
WARNING   112,960 AR rows dropped — provider not in the Provider List
          changed · rows 900 → 112,960
```

Last week 900. This week 112,960. That jump means something broke in the
Provider List. Before, the message just said "112,960" and you had no way to
know it used to be 900 — last week's message no longer existed anywhere.

You'll see one of four labels on every warning:

- **new this week** ← the one that deserves attention
- **changed** — with the before and after
- **same as last week** — background noise
- **resolved since last week** — it used to warn, now it doesn't

Below that, two tables: what it produced (with last week's row counts beside
this week's), and every file it read with its size and row count.

Then the **Approve** button. It records who approved it and when. Pressing it
twice is refused.

### Scorecard — what the client sees

Four figures at the top, then one section at a time:

```
[ Settlement ]  KPI   CP settled   Collections   Case AR   Delta   Raw data
```

The Settlement table shows every group against every period:

```
Group                Jan       Feb       Mar   …    Wk 35        Total
Russman         $264,255  $193,844  $366,394       $77,441   $2,213,956
Artheon          $35,794   $39,968   $42,763        $9,216     $461,771
Medvantage       $41,537   $30,111   $29,965        $2,652     $253,107
…
Total           $412,693  $323,725  $521,898      $104,702   $3,614,847
```

Months are totals for the year so far; then the current month's weeks.

**Raw data** is worth a mention. It's 278,930 rows — the reason your workbook is
21 MB and slow to open. Here it stays in storage and the page fetches 50 rows at
a time, so it opens instantly.

**Export CSV.** Every table — Raw data, Delta, Case AR, Collections — has an
**Export CSV** button beside the page arrows. It downloads the **whole** table,
not the 50 rows on screen:

```
GFS Raw data          278,930 rows    24 MB
GFS Delta                 666 rows
```

The file is named for what it is, so it doesn't get lost in your downloads
folder: `gfs-2026-W35-raw_data.csv`.

### Run history

Every build of the **last 12 weeks**, both reports, with warning counts and who
approved each one. Your dated folders could only be read by someone sitting at
that laptop.

Twelve weeks is a quarter. Far enough back to see whether something is drifting,
short enough that the page is still a page — a list that grows forever stops
being read.

A week is normally **two rows**: GFS on Tuesday, All Providers on Thursday. They
are told apart by the **Scorecard** column, and each week's rows sit in their own
block with a gap above them:

```
  WEEK      SCORECARD       STATUS     ACTION  WARNINGS  APPROVED BY   OPEN

  2026-W36  GFS             approved      1       3     ali.asghar    Scorecard
  ─────────────────────────────── gap ───────────────────────────────
  2026-W35  All Providers   review        4       2        —          Scorecard
  2026-W35  GFS             approved      1       3     ali.asghar    Scorecard
```

**Unapprove.** Approving is one click, so taking it back is one click too. The
build goes back to `review` and can be approved again. Why it matters: without
it, the only way out of a mis-click was to build the week again — and that gives
you a new run number, while the screenshot you already emailed still points at
the old one.

Un-approving is written into the run's own notes: who withdrew it, and who had
approved it. A report that was signed off on Tuesday and unsigned on Wednesday
should not be a mystery on Thursday.

**Delete.** Removes a build and everything it recorded — its figures, its tables,
its notes.

Two things it deliberately does *not* touch:

- **The files you uploaded.** They belong to the week, and the other report needs
  them too. Deleting a build must never cost you the inputs.
- **A result another build still uses.** Results are stored under a fingerprint
  of their own contents, so two identical builds share one file. It is only
  removed once nothing points at it any more.

Deleting asks twice, in the row itself — **Delete** turns into **Really delete?**
and **Keep**, and gives up after five seconds if you walk away. A pop-up box is
too easy to click through without reading; a second button in the row you are
about to destroy makes you look at it.

> Anyone signed in can delete today. Restricting it to an admin is a later step —
> there is no admin to be yet, because accounts have no roles.

---

## 7. Where everything is kept

Two places:

**The files themselves** are stored under a **fingerprint of their contents** —
a code worked out from every byte in the file.

Three useful things follow from that:

1. **You can prove a file arrived intact.** The app works out the fingerprint of
   what it received. Same fingerprint means identical bytes — not "probably
   fine", identical.

2. **The same file is only stored once.** Thursday's Supporting File is usually
   identical to Tuesday's, so the second copy costs nothing.

3. **A file can never be quietly swapped.** Upload a corrected Payment Detail
   and it lands in a *new* place. The old one stays. So a run from three months
   ago still points at the exact bytes it read — not "whatever is called that
   now".

**Everything else** — which weeks exist, which files arrived when, every build,
every warning, who approved what — is in a database.

---

## 8. Questions you can now answer

Things that were hard or impossible before:

| Question | Where to look |
|---|---|
| Which file produced this number? | Review page → "What it read", with fingerprints |
| Did anyone approve last week's report? | Run history → Approved by |
| Are we dropping more rows than usual? | Review page → the warning says what it was last week |
| What did we send in Week 32? | Run history → open that week's scorecard |
| Did the client get the right Case AR? | The upload is tagged GFS or All Providers |

---

## 9. If something goes wrong

**"9 still needed" won't go away.**
A file is missing. The card lists exactly which. Check the name hasn't been
changed — the app finds files by words in their names.

**A file was ignored.**
It isn't one of the inputs. Old delivered workbooks in the folder get ignored on
purpose. If a real input was ignored, its name has probably been changed.

**A Case AR was refused.**
You didn't pick a report in the dropdown. Pick GFS or All Providers and drop it
again.

**The build failed.**
The review page shows the reason in plain words. Usually a source file changed
its columns; the message names the column.

**The page won't load.**
The server isn't running. See section 10.

**A number looks wrong.**
Nothing is lost. Open the review page, see exactly which files were read, and
compare with the `.bat` version — which still works and is still installed.

---

## 10. How we know the numbers are right

This was checked, not assumed.

Your `.bat` programs save their calculated tables to disk. The app was run on
the **same input files**, and every table compared against them.

```
GFS                                    All Providers
  raw_data          278,930  MATCHES     raw_data          468,267  MATCHES
  case_ar                 8  MATCHES     case_ar                34  MATCHES
  delta_comparison      666  MATCHES     delta_comparison      221  MATCHES
  collections            63  MATCHES     collections           226  MATCHES
                                         settlement grids     455   MATCHES
```

Two small allowances, both deliberate:

- **Row order isn't compared.** The software splits work across your processor's
  cores to go fast, so rows finish in a different order each run. Your own
  program does the same. A missing, extra or changed row still fails the check.
- **Money is compared to the cent.** Adding 278,930 numbers in a different order
  moves the answer in the fifteenth decimal place — the largest gap measured was
  **0.0000008 on a total of $299,693,534.89**. A one-cent difference still fails.

This check runs as an automatic test and can be re-run any time. **45 tests pass.**

One honest limit: this is proved on **Week 35 only**. Keep next Tuesday's
`marts\2026-W36\` folder after the `.bat` run and it can be checked against a
second, fresh week.

---

## 11. Starting and stopping it

Two windows. Leave both open while you're using it.

```
Window 1 — the engine
cd C:\dev\scorecard-platform\backend
..\.venv\Scripts\python -m uvicorn app.main:app

Window 2 — the screens
cd C:\dev\scorecard-platform\frontend
npm run dev
```

Then open **http://localhost:5173**.

Closing a window stops that half. Nothing is lost — the files and every past run
stay where they are.

---

## 12. What this is not, yet

Being straight about it:

- **It runs on your laptop.** For the client to use it, it needs to live on a
  server.
- **Anyone with an @appedology.com address can create an account.** There is no
  approval step and no admin who can remove someone. That is fine inside the
  company; it is not enough before an outside client is given a link.
- **Anyone signed in can delete a build, or take an approval back.** Both are
  recorded against the account that did it, but nothing stops anyone doing
  either. Accounts have no roles yet, which is what an "only an admin can
  delete" rule would need first.
- **The sign-in token is kept in the browser's storage.** Fine on one company
  network. Once this is on a real server it should move to a cookie that
  JavaScript cannot read at all.
- **Your `.bat` programs are untouched** and still run every week. Nothing here
  has replaced them yet — that's deliberate. Run both side by side for a few
  weeks until the numbers have been checked enough times to trust.
