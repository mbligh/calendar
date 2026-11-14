# Public calendar publishing

## Requirements
- Publish public ICS subscriptions via GitHub Pages from `docs/`.
- Rugby calendars prevent score spoilers by freezing accepted events at kickoff.
- Generate Plex rugby NFO metadata from neutral fixture details.
- Mirror New Jersey hunter paces from Find a Hunter Pace daily, updating only
  when event data changes. Include locations, organizer links and contacts;
  handle duplicate entries, reschedules, cancellations and source removals.
- Remove fixtures only when World Rugby explicitly marks their match ID cancelled; retain merely missing fixtures. Cancelled matches do not enter published feeds, and previously published cancellations are removed even after kickoff (no result data is imported).\n- Preserve published feeds on fetch/parse failure. Google Calendar controls
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

## RugbyPass episode metadata
The authenticated RugbyPass catalogue is exported on `slagg` using
`rugbypass --export-catalog FILE --calendar-repo PATH`, which commits
`data/rugbypass.json` into this repository. This file is source observation
data only, never credentials or media URLs.

`plex_nfo.py` reconciles Nations Championship full-match replay titles,
rounds, teams and publication dates against score-free ICS fixtures, with
one-day calendar tolerance. Ambiguous observations do not produce associations.
The canonical `docs/rugby-metadata-manifest.json` has schema version 2:
season is calendar year, episode is round * 100 + the stable ordinal within
that round, and NFO paths use the same convention as media downloads.
The prior schema 2 manifest is reused to keep assigned episode numbers stable.

`mbligh/tools/rugbypass` uses the published fixture manifest to choose
`/data/sports/<Show>/Season_<Year>/<Show>-s<Year>e<Episode>-...`,
writes sibling NFO files after successful downloads, and supports standalone
NFO creation by fixture ID. The legacy tarball remains published for
compatibility; generating local NFOs does not depend on it.
