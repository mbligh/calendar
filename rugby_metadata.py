"""Build legacy-compatible rugby NFO manifest/archive from canonical Atlas episodes.

The PVR scheduler owns the fixture IDs, round numbering, source data and NFO
XML. This module only packages the *stored* canonical metadata for consumers
that still read the calendar repository's old static manifest and tarball.
No fixture algorithms or source fetchers live here.
"""
import datetime as dt
import gzip
import hashlib
import io
import json
import json
import pathlib
import re
import tarfile
import xml.etree.ElementTree as ET

SAFE_PATH = re.compile(r"^[A-Za-z0-9_]+/Season_\d{4}/[A-Za-z0-9_\-]+\.nfo$")


def aware(value):
    if not isinstance(value, dt.datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def tvshow_xml(showtitle):
    root = ET.Element("tvshow")
    ET.SubElement(root, "title").text = showtitle
    ET.SubElement(root, "plot").text = "Spoiler-free rugby fixture metadata"
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def build(records, *, now=None, fallback_manifest=None, fallback_archive=None):
    """Return (manifest JSON bytes, tar.gz bytes, counts), all in memory.

    Unknown, cancelled or superseded fixtures never enter the published set.
    A canonical NFO file must have a safe path and matching identity.
    """
    now = aware(now) or dt.datetime.now(dt.timezone.utc)
    config = json.loads((pathlib.Path(__file__).parent / "calendars.json").read_text())
    old_to_new = {e["legacy_slug"]: e["slug"]
                  for e in config["calendars"] + config.get("plex_sources", [])
                  if e.get("legacy_slug")}
    rows = []
    blobs = {}
    ids = set()
    keys = set()
    canonical_series = set()
    carried_legacy = 0
    for ep in records:
        series = ep.get("series_id")
        if not isinstance(series, str) or not (
                series.startswith("Rugby_") or series == "Gallagher_PREM"):
            continue
        canonical_series.add(series)
        if ep.get("status") in ("superseded", "cancelled", "canceled"):
            continue
        eid = ep.get("_id")
        if not isinstance(eid, str) or not eid.startswith(series + ":") or eid in ids:
            raise ValueError(f"Invalid or duplicate Atlas rugby fixture ID: {eid}")
        ids.add(eid)
        kickoff = aware(ep.get("scheduled"))
        if kickoff is None:
            continue
        season = ep.get("season")
        number = ep.get("episode")
        if type(season) is not int or not 1900 <= season <= 2100:
            raise ValueError(f"Invalid season: {eid}")
        if number is not None and (type(number) is not int or number <= 0):
            raise ValueError(f"Invalid episode number: {eid}")
        home = ep.get("home")
        away = ep.get("away")
        if not home or not away:
            raise ValueError(f"Missing rugby fixture teams: {eid}")
        show = ep.get("showtitle") or series
        nfo_path = ep.get("nfo_path")
        nfo = ep.get("nfo")
        if number is not None:
            if not isinstance(nfo_path, str) or not SAFE_PATH.fullmatch(nfo_path):
                raise ValueError(f"Missing or unsafe canonical NFO path: {eid}")
            if not isinstance(nfo, str) or not nfo.strip():
                raise ValueError(f"Missing canonical NFO bytes: {eid}")
            if (season, number, series) in keys:
                raise ValueError(f"Duplicate canonical rugby episode number: {eid}")
            keys.add((season, number, series))
            xml = ET.fromstring(nfo)
            if (xml.findtext("showtitle") != show or
                    xml.findtext("season") != str(season) or
                    xml.findtext("episode") != str(number)):
                raise ValueError(f"Canonical NFO identity mismatch: {eid}")
            blobs[nfo_path] = nfo.encode("utf-8")
            lib = nfo_path.split("/", 1)[0]
            title_file = lib + "/tvshow.nfo"
            if title_file not in blobs:
                blobs[title_file] = tvshow_xml(show)
        else:
            nfo_path = None
        rows.append({
            "id": eid, "competition": series, "season": season,
            "round": ep.get("round"), "episode": number,
            "kickoff_utc": kickoff.astimezone(dt.timezone.utc).isoformat(),
            "home": str(home), "away": str(away),
            "venue": ep.get("venue") or "",
            "showtitle": show,
            "rugbypass_id": (ep.get("external_ids") or {}).get("rugbypass"),
            "nfo": nfo_path,
        })
    # Keep legacy-only canonical data for competitions not imported into
    # Atlas yet (currently Gallagher PREM from its authenticated API).
    # Never merge fallback fixtures for a series Atlas already owns, or the
    # previously mixed women's/WXV calendar would be silently revived.
    if fallback_manifest is not None:
        if fallback_archive is None or fallback_manifest.get("schema_version") != 2:
            raise ValueError("Legacy manifest/archive pair is incomplete")
        with tarfile.open(fileobj=io.BytesIO(fallback_archive), mode="r:gz") as old_tar:
            for item in fallback_manifest.get("fixtures", []):
                item = dict(item)
                comp = item.get("competition")
                if comp in old_to_new:
                    newer = old_to_new[comp]
                    item["competition"] = newer
                    item["id"] = newer + item["id"][len(comp):]
                    comp = newer
                if comp in canonical_series:
                    continue
                fid = item.get("id")
                if not isinstance(comp, str) or not isinstance(fid, str) or not fid.startswith(comp + ":"):
                    raise ValueError("Invalid legacy-only fixture ID")
                if fid in ids:
                    raise ValueError(f"Duplicate canonical and legacy fixture {fid}")
                ids.add(fid)
                nfo_path = item.get("nfo")
                if nfo_path is not None:
                    if not isinstance(nfo_path, str) or not SAFE_PATH.fullmatch(nfo_path):
                        raise ValueError(f"Unsafe legacy NFO path: {fid}")
                    try:
                        blobs[nfo_path] = old_tar.extractfile(nfo_path).read()
                        tvpath = nfo_path.split("/", 1)[0] + "/tvshow.nfo"
                        if tvpath not in blobs:
                            blobs[tvpath] = old_tar.extractfile(tvpath).read()
                    except (KeyError, AttributeError, OSError) as exc:
                        raise ValueError(f"Legacy NFO absent from published archive: {fid}") from exc
                rows.append(dict(item))
                carried_legacy += 1
    if not rows:
        raise ValueError("Refusing to publish empty Atlas rugby manifest")
    rows.sort(key=lambda x: (x["competition"], x["season"], x["kickoff_utc"], x["id"]))
    manifest = {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "fixtures": rows,
        "files": {path: hashlib.sha256(payload).hexdigest()
                  for path, payload in sorted(blobs.items())},
    }
    if (fallback_manifest and
            fallback_manifest.get("fixtures") == manifest["fixtures"] and
            fallback_manifest.get("files") == manifest["files"]):
        manifest["generated_at"] = fallback_manifest.get(
            "generated_at", manifest["generated_at"])
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True,
                                 ensure_ascii=False) + "\n").encode("utf-8")
    tar_data = io.BytesIO()
    with gzip.GzipFile(fileobj=tar_data, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w") as tar:
            for name, data in sorted({**blobs,
                                       "manifest.json": manifest_bytes}.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                tar.addfile(info, io.BytesIO(data))
    return manifest_bytes, tar_data.getvalue(), {
        "fixtures": len(rows), "nfos": len(blobs),
        "numbered": sum(x["nfo"] is not None for x in rows),
        "legacy_only_retained": carried_legacy,
    }


def write(output_dir, manifest_bytes, archive_bytes):
    """Atomically replace static files after all bytes have been validated."""
    import os
    import tempfile
    root = pathlib.Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in (
            ("rugby-metadata-manifest.json", manifest_bytes),
            ("rugby-metadata.tar.gz", archive_bytes)):
        target = root / name
        with tempfile.NamedTemporaryFile(dir=root, prefix=".rugby-metadata-",
                                         delete=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = pathlib.Path(handle.name)
        paths.append((temporary, target))
    try:
        for temp, dest in paths:
            os.replace(temp, dest)
    finally:
        for temp, dest in paths:
            temp.unlink(missing_ok=True)
    return [dest for _, dest in paths]
