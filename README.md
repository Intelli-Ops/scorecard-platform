

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
