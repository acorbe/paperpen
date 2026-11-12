# Running paperpen

Running it out of its checkout, and putting the reader on the network for the tablet: the login, the second factor and the certificate. Back to the [README](../README.md).

## Running it

paperpen runs out of its checkout. `upstream/` is not a Python package, and
`paperpen/bind.py` looks for it beside the package directory, so a plain wheel
install puts the code in site-packages with no `upstream/` next to it and the
first import fails on `upstream/paper.py`. An editable install keeps the two
together, which is what `uv run` does without being asked.

```sh
uv run paperpen serve                  # in the checkout; uv builds the venv
uv run paperpen shelf
uv run python -m paperpen.cli serve    # the same, without the entry point
```

For a `paperpen` that works from any directory, install it editable:

```sh
uv tool install --editable .           # or, in a venv of your own:
pip install -e .
paperpen serve
```

`serve` binds 127.0.0.1:8770 and prints the shelf, the reader and the queue as
addresses to open. `--host` and `--port` change that. Any host that is not
loopback counts as the network, exactly as `--lan` does: it gets the login and
the certificate described below.

On loopback there is no login: a password on `http://127.0.0.1` protects
nothing the files on this machine do not already. What it does have, in every
mode, is a guard against the browser itself. Any web page you have open can
send requests to `127.0.0.1`, so the server answers only under its own name
(`localhost`, `127.0.0.1`, `::1`), which stops a page that points its own name
here, and refuses a write that comes from a page that is not its own.

### On the network, which is where the tablet is

The reader is for a tablet, and a tablet arrives over the network. `--lan`
binds every interface, and on a new machine `paperpen onboard` walks what that
needs, in order: the login, the certificate and a first paper. It passes over
whatever is already done and ends by saying what still is not;
`paperpen onboard --check` only says, and exits 1 until the login is decided.

```sh
paperpen onboard          # all of the basics, once
paperpen lan              # choose the login: password and app code, password, or none
paperpen tls              # a self-signed certificate for this machine
paperpen serve --lan      # 0.0.0.0, over https, behind the login
paperpen qr               # the address, to point the tablet's camera at
paperpen lan --no-login   # no login, for a network you trust
paperpen lan --clear      # forget the password and the second factor
```

`serve --lan` prints a QR code of its own address at start-up, because the
alternative is typing `https://198.51.100.24:8770/` on a glass keyboard and
getting it wrong once.

### The login

Onboarding and `paperpen lan` ask how the reader on the network lets people in:

1. **a password and six digits from an authenticator app**, which is the
   recommendation and the default;
2. **a password only**;
3. **no login.** Anyone who can reach the address can then read your papers and
   notes, change their sources and download all of it. That is a fair choice on
   a network that is yours, at home say, and the wrong one on conference or
   campus wifi. It has to be confirmed by typing `no login`, and `serve --lan`
   says so in a warning every time it starts. `paperpen lan --no-login` chooses
   it directly; `paperpen lan` turns a login back on.

`serve --lan` never starts unlocked by default: until one of the three is
chosen it asks, on a terminal, and refuses otherwise.

The second factor is TOTP, the six digits an authenticator app shows. Enrolling
draws a QR code in the terminal for the app to scan, as
`paperpen:<this machine>`; `--light` redraws it for a terminal with a light
background, and the same code is kept as a picture only you can read,
`second-factor.svg` beside the registry, until enrolment is over. The key is
printed too, for typing in. It then asks for a code, and saves nothing until
one matches: a second factor you cannot produce is a lock with no key, and the
door is the wrong place to find that out. The implementation is checked against
the RFC 6238 vectors, so the app and this agree. A code already used is refused
even while it is still valid, which closes a replay by anyone who sees it.

The password is scrypt-hashed with a fresh salt in `~/.config/paperpen/auth.json`,
mode 0600, beside the login choice. It is deliberately not in `papers.json`,
which goes into every bundle and can be downloaded from the shelf. Under https
the session cookie is marked secure, so it is never sent in the clear, and
after signing in the reader only ever returns to a page on itself.

`--debug` (Flask's debugger and reloader) is refused off loopback: its debugger
runs whatever is typed into it.

### The certificate

`paperpen tls` writes a self-signed certificate and key into
`~/.config/paperpen/tls/`, and `serve --lan` uses it. Without one the LAN is in
the clear; `serve --lan` says so and offers to make one, and `--no-tls` is
there for meaning it.

The names in it matter more than they look. A browser checks the address it
was given against the certificate's subjectAltName, and an IP typed into a
tablet has to be in there **as an IP**: a certificate carrying only a common
name has not been accepted by Chrome since 2017. So `localhost`, this
machine's hostname and its LAN address all go in, and the certificate has to
be made again when that address changes; `serve` checks and says so rather
than letting the tablet refuse it for a reason that reads like a bug. It is
good for 397 days, because Apple rejects a TLS certificate valid for more than
398 and an iPad is the reader this exists for.

It is signed by nobody, so the tablet has to be told once to trust it. Two
ways, and they are not equally good:

- **Install it.** Copy `cert.pem` to the tablet and open it. iOS puts it under
  Settings, then *Profile Downloaded*, and it has to be switched on again under
  *General > About > Certificate Trust Settings*; Android has it under
  *Security > Encryption > Install a certificate*. No warning afterwards.
- **Accept the browser's warning**, which comes back periodically. Only after
  checking the fingerprint on the tablet against the one `paperpen tls` prints.
  An unchecked "proceed anyway" on a network you do not control is exactly how
  somebody else ends up reading this.

What this does not give you is a padlock without being asked. That needs a
certificate authority the tablet already trusts, which means a real domain or
a local CA installed on every device, and neither is worth it for one reader
on one network.

### Where it is running

`paperpen shelf` is the same shelf in a terminal, and it ends by saying where
the browser one is: the port the server actually recorded, not the one in this
paragraph. When nothing is running it says so, and what to type:

```
in a browser: http://127.0.0.1:8770/
not serving. `paperpen serve` puts this shelf, and the reader, at http://127.0.0.1:8770/
```

The port is probed before it is offered, so a record left behind by a server
that was killed reads as not serving rather than as a link that fails once and
is never trusted again. `paperpen where` says the same thing among the rest.
