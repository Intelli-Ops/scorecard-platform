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

Then an admin has to approve the account. You will see *"Account created. An
admin has to approve it"*. Once they have, sign in with the same email and
password. The admin does this on the **Users** screen.

**Forgot your password?** Ask an admin. They give you a temporary one, and
the app asks you to choose your own as soon as you sign in with it.

Two things it will not accept:

```
someone@gmail.com    ->  Use your Appedology email - it must end @appedology.com.
APD-123              ->  The APD ID looks like APD-1234 - four digits.
```

Small kindnesses: the email is not case-sensitive, and if you type just `1234`
it fills in the `APD-` for you.

**After that.** Sign in with your email and password. You stay signed in
while you are using the app; after an hour of doing nothing in it (or twelve
hours in all) you are asked to sign in again. **Sign out** is at the bottom of
the sidebar, next to your email and APD ID.

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

This is the "things worth your eyes" step, with somewhere to live. It shows
only what you have to check before the report goes out - nothing routine.

Four figures across the top:

```
Needs attention     New providers     No data     Duplicate case IDs
      Yes                 2              1                0
```

Then three sections:

```
NEW PROVIDERS
ACTION    New provider in KPI DOR: 'Dorian Chiropractic' has 1 and had no
          row - added as its own row and counted in the DOR total
WARNING   Provider(s) in the KPI-numbers file but not in the Supporting
          File - their figures are not counted: Azizi One & Only Chiro

NO DATA FOR THE WEEK
ACTION    No data for KPI 10635 (DDEL) this week - no column for it in the
          KPI-numbers file
WARNING   No data for KPI Enforcement Of Agreement in September 2026 -
          every provider is 0

DUPLICATE CASE IDS
WARNING   2 duplicate case id(s) in Delta Comparison: 81234, 90211
```

Rows dropped by the routine filters (inactive providers, closed files, no
Case AR match) are not listed. They happen every week and are the filters
doing their job.

| | What it means |
|---|---|
| **ACTION** | A number the client will look at is missing, or a new provider's row was added. Check it before sending. |
| **WARNING** | Worth a look: a provider whose figures could not be counted, a block that came to nothing, a duplicate case. |

From the second week onwards, each item says whether it is new:

- **new this week** - the one that deserves attention
- **changed** - with the before and after
- **same as last week** - you have seen it before
- **resolved since last week** - it used to show, now it doesn't

A new provider is new once. From the next week it reads "same as last week".


## 8. Questions you can now answer

Things that were hard or impossible before:

| Question | Where to look |
|---|---|
| Which file produced this number? | The Files page, with fingerprints |
| Did anyone approve last week's report? | Run history → Approved by |
| Is this provider new? | Review page → New providers, marked "new this week" |
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
- **Anyone signed in can take an approval back.** It is recorded in the
  activity log against the person who did it, but it is not limited to
  admins. Deleting *is* limited to admins.
- **Password resets go through an admin.** There is no email server, so the
  app cannot send a reset link.
- **The sign-in token is kept in the browser's storage.** Fine on one company
  network. Once this is on a real server it should move to a cookie that
  JavaScript cannot read at all.
- **Your `.bat` programs are untouched** and still run every week. Nothing here
  has replaced them yet — that's deliberate. Run both side by side for a few
  weeks until the numbers have been checked enough times to trust.
