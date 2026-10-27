# Public calendar publishing

## Requirements
- Publish public ICS subscriptions via GitHub Pages from `docs/`.
- Rugby calendars prevent score spoilers by freezing accepted events at kickoff.
- Generate Plex rugby NFO metadata from neutral fixture details.
- Mirror New Jersey hunter paces from Find a Hunter Pace daily, updating only
  when event data changes. Include locations, organizer links and contacts;
  handle duplicate entries, reschedules, cancellations and source removals.
- Preserve published feeds on fetch/parse failure. Google Calendar controls
  subscription refresh latency.

## Implementation
`calendars.json` configures rugby adapters used by `filter.py`; `plex_nfo.py`
builds metadata. The existing hourly workflow commits generated snapshots.
`hunter_paces` independently parses dated two-cell rows in the source page's
content area using BeautifulSoup and emits all-day events with `icalendar`.
Dreamweaver library identifiers plus year supply stable event UIDs; exact
duplicates collapse and conflicting duplicates fail validation. Every dated
source listing is included, including older years. Event timestamps and
sequences change only when event properties change. Invalid or empty pages
fail before writing. The dedicated daily workflow commits changed ICS and
explicitly deploys all of `docs/` using Pages Actions. Both workflows share a
concurrency group. `test_hunter_paces` checks parsing and snapshot semantics.
No database is needed: committed ICS files are the persistent state.

The Gallagher PREM Plex source uses the Cortex/InCrowd RugbyViz match API.
The updater accepts optional `PREM_APP_ID`, `PREM_API_KEY`, and `PREM_REALM`
environment variables, passed from GitHub Actions secrets of the same names.
Cortex now requires authenticated requests; use credentials issued for this
integration, not credentials copied from a third-party website. A failed Plex
fetch never replaces the previously published metadata. The hourly workflow
still commits successfully updated ICS calendars, but finishes red if Plex
generation fails so the failure remains visible.

## Rugby calendar source migrations

The committed `docs/*.ics` snapshots are persistent state for spoiler protection.
The normal updater retains events after kickoff even if they disappear from the
source. Consequently, switching providers without cleaning the snapshot can
create duplicate fixtures with different UIDs.

Use an explicit, one-off migration for each affected calendar:

1. Back up the existing ICS snapshot and fetch/validate the replacement source
   before modifying published output. Check that its fixtures, dates, and
   coverage are plausible; abort on empty, malformed, or unexpectedly sparse data.
2. Preserve old-source events whose **last accepted kickoff has passed**. These
   remain frozen to prevent retrospective score or result changes.
3. Remove **future** old-source events from the snapshot, then import future
   events from the new source with their new stable UIDs. Do not import past
   events from the new source, since their content may contain spoilers.
4. Check for duplicates, missing fixtures, and unexpected changes; review the
   diff before committing the updated snapshot and source configuration.
5. Resume the normal updater. The retired source must no longer be configured,
   so its removed events cannot be reintroduced.

Different UIDs may temporarily appear as separate events in subscribers until
calendar clients refresh. Keep this migration procedure separate from routine
merging; do not add broad fuzzy deduplication to `filter.py`.
