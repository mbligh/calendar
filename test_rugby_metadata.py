"""Atlas-derived rugby fixture manifest and Plex NFO archive compatibility."""
import datetime as dt
import gzip
import hashlib
import io
import json
import pathlib
import tarfile
import tempfile
import unittest

import rugby_metadata as meta

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 21, 16, tzinfo=UTC)


def fixture(series="rugby-womens-wxv", episode=101, path=None):
    library = "Rugby_Womens_WXV"
    name = path or f"{library}/Season_2026/{library}-s2026e{episode:03d}-Canada_v_England_20261017.nfo"
    return {
        "_id": f"{series}:world-rugby-test@mbligh.github.io",
        "series_id": series, "season": 2026, "episode": episode,
        "scheduled": dt.datetime(2026, 10, 17, tzinfo=UTC),
        "round": 1, "home": "Canada", "away": "England",
        "showtitle": "Rugby Womens WXV", "nfo_path": name,
        "nfo": ("<episodedetails><showtitle>Rugby Womens WXV</showtitle>"
                f"<season>2026</season><episode>{episode}</episode>"
                "</episodedetails>"),
        "venue": "Example", "external_ids": {"rugbypass": "1011153"},
    }


def old_legacy_payload():
    item = {
        "id": "gallagher-prem:prem-123@mbligh.github.io",
        "competition": "gallagher-prem",
        "season": 2026, "episode": 101, "round": 1,
        "kickoff_utc": "2026-09-25T18:45:00+00:00",
        "home": "Harlequins", "away": "Bath Rugby", "venue": "Twickenham",
        "showtitle": "Gallagher PREM", "rugbypass_id": None,
        "nfo": "gallagher_prem/Season_2026/gallagher_prem-s2026e101-Harlequins_v_Bath_20260925.nfo"
    }
    manifest = {"schema_version": 2, "fixtures": [item], "files": {}}
    records = {
        item["nfo"]: b"<episodedetails/>",
        "gallagher_prem/tvshow.nfo": b"<tvshow/>"
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for path, data in records.items():
            record = tarfile.TarInfo(path)
            record.size = len(data)
            tar.addfile(record, io.BytesIO(data))
    return manifest, stream.getvalue()


class AtlasMetadataTests(unittest.TestCase):
    def test_new_wxv_is_in_manifest_and_archive_with_canonical_nfo(self):
        payload, archive, info = meta.build([fixture()], now=NOW)
        contents = json.loads(payload)
        self.assertEqual(contents["schema_version"], 2)
        self.assertEqual(len(contents["fixtures"]), 1)
        row = contents["fixtures"][0]
        self.assertEqual(row["competition"], "rugby-womens-wxv")
        self.assertEqual(row["episode"], 101)
        self.assertEqual(row["rugbypass_id"], "1011153")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            self.assertEqual(tar.extractfile(row["nfo"]).read(),
                             fixture()["nfo"].encode())
            self.assertEqual(json.loads(tar.extractfile("manifest.json").read()),
                             contents)
            self.assertIn("Rugby_Womens_WXV/tvshow.nfo", tar.getnames())
        self.assertEqual(contents["files"][row["nfo"]],
                         hashlib.sha256(fixture()["nfo"].encode()).hexdigest())
        self.assertEqual(info["numbered"], 1)

    def test_existing_wxv_legacy_intl_record_is_excluded(self):
        active = fixture()
        old = dict(active, _id="rugby-womens-intl:world-rugby-test@mbligh.github.io",
                   series_id="rugby-womens-intl", status="superseded")
        manifest, _, counts = meta.build([active, old], now=NOW)
        self.assertEqual(len(json.loads(manifest)["fixtures"]), 1)
        self.assertEqual(counts["legacy_only_retained"], 0)

    def test_legacy_only_prem_assets_are_carried_forward_unchanged(self):
        original, archive = old_legacy_payload()
        content, tarball, report = meta.build(
            [fixture()], now=NOW,
            fallback_manifest=original, fallback_archive=archive)
        manifest = json.loads(content)
        self.assertEqual(len(manifest["fixtures"]), 2)
        self.assertEqual(report["legacy_only_retained"], 1)
        names = {f["competition"] for f in manifest["fixtures"]}
        self.assertEqual(names, {"rugby-womens-wxv", "gallagher-prem"})
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            oldpath = original["fixtures"][0]["nfo"]
            self.assertEqual(tar.extractfile(oldpath).read(), b"<episodedetails/>")

    def test_reject_bad_paths_duplicate_identity_and_xml_mismatch(self):
        invalid = fixture(path="../../out.nfo")
        with self.assertRaisesRegex(ValueError, "unsafe canonical"):
            meta.build([invalid], now=NOW)
        with self.assertRaisesRegex(ValueError, "duplicate Atlas"):
            meta.build([fixture(), fixture()], now=NOW)
        bad = fixture()
        bad["nfo"] = bad["nfo"].replace("Rugby Womens WXV", "Rugby Womens Intl")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            meta.build([bad], now=NOW)

    def test_retains_unallocated_fixture_with_null_nfo(self):
        item = fixture()
        item["episode"] = None
        item["nfo"] = None
        item["nfo_path"] = None
        content, _, report = meta.build([item], now=NOW)
        self.assertIsNone(json.loads(content)["fixtures"][0]["nfo"])
        self.assertEqual(report["numbered"], 0)

    def test_outputs_are_written_without_partially_truncated_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp)
            manifest, tarball, _ = meta.build([fixture()], now=NOW)
            paths = meta.write(path, manifest, tarball)
            self.assertEqual(len(paths), 2)
            self.assertEqual(paths[0].read_bytes(), manifest)
            self.assertEqual(paths[1].read_bytes(), tarball)


if __name__ == "__main__":
    unittest.main()
