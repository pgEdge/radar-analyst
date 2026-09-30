# Examples

`compose.env` is a commented `.env` file for `docker compose up -d`.
Copy it to `.env` beside `docker-compose.yml` and uncomment what you
need. Every setting in it is optional.

`walkthrough/guide.sh` is a guided first look. It starts the analyst
with the `docker-compose.yml` at the repository root, opens the
console in the browser, and walks through taking a radar collection
and assessing it. It never stops an analyst it finds already running;
`guide.sh --down` is the one way it removes anything, and that takes
the volumes too, after asking. It needs only Docker. It pulls the
published image; set `WALKTHROUGH_BUILD=1` to build the analyst from
the checkout instead. `docs/walkthrough.md` is the same tour by hand.
