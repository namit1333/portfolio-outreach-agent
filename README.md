# Portfolio Outreach Agent

Turn a portfolio support request into an **evidence-grounded prospect list and
ready-to-send outreach drafts** — end to end.

You type a request like:

> "One of my companies is doing robotics deployments in the supply chain and
> they want to meet more general contractor and construction businesses."

The tool spins up a team of agents that:

1. **Plan** — decompose the request into a research plan (target profile, fit
   criteria, 5–8 search queries, message goal, sender identity).
2. **Scout** (parallel) — one agent per query, canvassing the web for real
   businesses or professionals that fit, each with verbatim evidence + source URLs.
3. **Curate** — dedupe, enforce the sourcing policy, score fit 0–100, rank.
4. **Write** (parallel) — one agent per kept candidate, drafting a short,
   personalized message grounded strictly in the collected evidence.
5. **Assemble** — write `prospects.csv`, `outreach.md`, and per-contact drafts
   (`.eml` files you can open and send immediately).

The second use case works the same way: ask for "a specific type of systems
engineer" and it switches to **talent mode** — surfacing professionals and the
companies that employ them, with personalized messages ready to send.

## Quickstart (no API keys needed)

Python 3.10+, zero dependencies. From this directory:

```bash
python -m outreach_agent run \
  "One of my companies is doing robotics deployments in the supply chain and
   they want to meet more general contractor and construction businesses" \
  --sender-name "Namit" --sender-role "Platform team"
```

With no API keys configured the tool runs on **mock providers**: deterministic,
offline demo data on reserved `.example` domains (RFC 2606) so nothing can be
mistaken for a real finding. Full artifact structure is identical to a live run.
See committed examples in [`examples/sample_runs/`](examples/sample_runs).

## Live mode (real research)

Copy `.env.example` to `.env` and fill in at least one LLM key:

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic Messages API (built-in web search tool) |
| `ANTHROPIC_MODEL` | default `claude-opus-5-5` |
| `OPENAI_API_KEY` | OpenAI Responses API (built-in `web_search` tool) |
| `OPENAI_MODEL` | default `gpt-5.1` |
| `TAVILY_API_KEY` | optional dedicated search API |
| `SERPER_API_KEY` | optional dedicated Google search API |

Provider selection is automatic: Anthropic > OpenAI > mock. Research uses the
LLM provider's built-in web search (with citations) unless you point it at a
search API with `--search tavily` or `--search serper`, in which case scouts
extract candidates from those results instead.

```bash
python -m outreach_agent providers        # show what's configured
python -m outreach_agent plan "..."       # preview the research plan only
python -m outreach_agent run "..." --limit 15 --concurrency 6 --min-score 40
```

### Talent sourcing

```bash
python -m outreach_agent run \
  "They need a specific type of systems engineer — canvass for companies that
   would have engineers like that and surface profiles with a personalized message" \
  --kind talent --sender-name "Namit"
```

`--kind` is optional; it's inferred from the request ("businesses/contractors"
→ business, "engineer/profiles/hire" → talent).

## Output

Each run writes `runs/<timestamp>-<slug>/` (or `--out DIR --run-name NAME`):

| Artifact | Contents |
| --- | --- |
| `outreach.md` | the send-ready package: every candidate with fit rationale, evidence links, and the full draft |
| `prospects.csv` | one row per candidate (Excel-friendly UTF-8 BOM) — import into a sheet/CRM |
| `drafts/NN-name.eml` | pre-filled email (To/Subject/body) — open in your mail client and hit send |
| `drafts/NN-name.txt` | for candidates with no verified email: the note + send-via (LinkedIn / contact form) |
| `plan.json` | the research plan the agents executed |
| `run.json` | full trace: candidates, evidence, agent events, timings, warnings |

## Sourcing policy (enforced in code, not just prompt)

Modeled on the Sable lead-sourcing brief rules:

- **Never invent contact data.** No guessed email patterns (`info@`,
  `first.last@`), no inferred phones, no placeholders. A blank field is always
  acceptable — and stays blank.
- **Evidence or it doesn't ship.** Every contact field must literally appear in
  a verbatim quote with its source URL. Unsupported fields are blanked and the
  reason is recorded in `warnings`.
- **An aggregator page is never a website.** Yelp/Angi/BBB/social/job-board
  pages count as evidence (flagged `directory`/`social`) but `website` only
  accepts the entity's own domain.
- **Source quality is tracked** (`own_site > press > social > directory`) and
  feeds both scoring and the output's provenance columns.

Fit score (0–100): up to 60 for criteria coverage, up to 20 for source quality,
up to 20 for contactability (verified email / named contact / phone), up to 5
for a verified own website. `--min-score` filters, output is sorted by score.

## CLI reference

```
outreach run REQUEST [--kind auto|business|talent] [--limit N] [--concurrency N]
                     [--min-score F] [--out DIR] [--run-name NAME]
                     [--provider auto|anthropic|openai|mock]
                     [--search auto|tavily|serper|none]
                     [--sender-name N] [--sender-role R] [--sender-org O] [--quiet]
outreach plan REQUEST   # research plan JSON only
outreach providers      # resolved provider/key status
```

Installed console script: `pip install -e .` gives you `outreach ...`;
`python -m outreach_agent ...` works without installing.

## Architecture

```
outreach_agent/
  cli.py            run / plan / providers commands
  pipeline.py       orchestrator: fans out scouts + writers concurrently
  agents.py         planner, scout, writer agents + prompt contracts
  policy.py         evidence-only sourcing rules, dedupe, scoring
  output.py         CSV / Markdown / .eml / JSON assembly
  providers/        anthropic, openai, tavily/serper, mock
tests/              35 tests: policy, curation, pipeline, output, CLI
```

Agents degrade gracefully: a failed scout or writer is recorded as an event and
warning, and the run continues. Everything runs on the Python standard library —
no third-party packages.

Run the tests:

```bash
python -m unittest discover -s tests
```

## Before you send

The tool drafts; you decide. Verify each contact against its cited source, keep
the personalization honest, and follow CAN-SPAM/GDPR and platform rules for cold
outreach — including honoring opt-outs. Don't use it with bought lists or
scraped contact databases.
