

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

**Delete** removes the run and cascades to its inputs, notes, figures and
tables. Two things it does not touch:

  * uploads, which belong to the week and to the other report as well;
  * a result parquet another run also produced. Results are content-addressed,
    so two identical builds share one file; the blob is removed only once no
    `RunTable` row points at the hash.

A `pending` or `running` build cannot be deleted out from under the worker.

Both actions are open to anyone signed in. An admin-only rule needs a role on
the account first, which does not exist yet.

## Run history is bounded by weeks, not rows

`GET /api/runs?weeks=12`. A row limit cuts in the wrong place: rebuild one week
four times and a limit of 20 rows silently drops three older weeks off a list
that still calls itself a history.
