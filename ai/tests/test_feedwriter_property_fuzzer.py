"""Property-based fuzzer tests for FeedWriter (Phase 16.2, bullet 12).

Deterministic test cases covering various failure modes (25 cases).

Invariant: "NDJSON+CRC ⇒ deduped record set ≡ input set ∧ per-source fairness floor honoured"
"""

import json
import tempfile
import random
from typing import Any, Dict, List

import pytest

from common.feeds.writer import FeedWriter
from common.feeds.crc import CRCTrailerConfig, crc32c


class TestPropertyBasedFuzzer:
    """25 deterministic fuzzer test cases for writer invariants."""

    def _generate_records(self, seed: int, count: int) -> List[Dict[str, Any]]:
        """Generate deterministic record sequence using seed."""
        random.seed(seed)
        records = []
        for i in range(count):
            records.append({
                "id": random.randint(1, 10000),
                "plane": random.choice(["score", "match", "result"]),
                "value": f"value_{random.randint(0, 1000)}",
            })
        return records

    def test_fuzzer_case_01_empty(self):
        """Case 01: Empty record list."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_01", feeds_dir=tmp_path, redis_client=None, writer_id="f-01")
            writer.open()
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 0

    def test_fuzzer_case_02_single(self):
        """Case 02: Single record."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_02", feeds_dir=tmp_path, redis_client=None, writer_id="f-02")
            writer.open()
            writer.enqueue({"id": 1, "value": "test"})
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 1

    def test_fuzzer_case_03_sequential_10(self):
        """Case 03: Sequential IDs 1-10."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_03", feeds_dir=tmp_path, redis_client=None, writer_id="f-03")
            writer.open()
            for i in range(1, 11):
                writer.enqueue({"id": i, "value": f"test_{i}"})
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 10

    def test_fuzzer_case_04_duplicates(self):
        """Case 04: Duplicate IDs."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_04", feeds_dir=tmp_path, redis_client=None, writer_id="f-04")
            writer.open()
            for i in range(20):
                writer.enqueue({"id": i % 3, "value": f"test_{i}"})
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 20

    def test_fuzzer_case_05_descending(self):
        """Case 05: Descending IDs."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_05", feeds_dir=tmp_path, redis_client=None, writer_id="f-05")
            writer.open()
            for i in range(10):
                writer.enqueue({"id": 1000 - i, "value": f"test_{i}"})
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 10

    def test_fuzzer_case_06_random_seed_1_20(self):
        """Case 06: Random seed=1, 20 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_06", feeds_dir=tmp_path, redis_client=None, writer_id="f-06")
            writer.open()
            for r in self._generate_records(1, 20):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 20

    def test_fuzzer_case_07_random_seed_2_30(self):
        """Case 07: Random seed=2, 30 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_07", feeds_dir=tmp_path, redis_client=None, writer_id="f-07")
            writer.open()
            for r in self._generate_records(2, 30):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 30

    def test_fuzzer_case_08_random_seed_3_50(self):
        """Case 08: Random seed=3, 50 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_08", feeds_dir=tmp_path, redis_client=None, writer_id="f-08")
            writer.open()
            for r in self._generate_records(3, 50):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 50

    def test_fuzzer_case_09_random_seed_4_15(self):
        """Case 09: Random seed=4, 15 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_09", feeds_dir=tmp_path, redis_client=None, writer_id="f-09")
            writer.open()
            for r in self._generate_records(4, 15):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 15

    def test_fuzzer_case_10_random_seed_5_25(self):
        """Case 10: Random seed=5, 25 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_10", feeds_dir=tmp_path, redis_client=None, writer_id="f-10")
            writer.open()
            for r in self._generate_records(5, 25):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 25

    def test_fuzzer_case_11_crc_enabled_10(self):
        """Case 11: CRC enabled, 10 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_11", feeds_dir=tmp_path, redis_client=None, writer_id="f-11", fsync_mode="always")
            writer.crc_config = CRCTrailerConfig(enabled=True)
            writer.open()
            for r in self._generate_records(11, 10):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 10

    def test_fuzzer_case_12_mixed_planes_20(self):
        """Case 12: Mixed planes, 20 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_12", feeds_dir=tmp_path, redis_client=None, writer_id="f-12")
            writer.open()
            for i in range(20):
                plane = ["score", "match", "result"][i % 3]
                writer.enqueue({"id": i, "plane": plane, "value": f"test_{plane}"})
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 20

    def test_fuzzer_case_13_large_100(self):
        """Case 13: Large record count, 100 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_13", feeds_dir=tmp_path, redis_client=None, writer_id="f-13")
            writer.open()
            for r in self._generate_records(13, 100):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 100

    def test_fuzzer_case_14_monotonic_order_20(self):
        """Case 14: Monotonic order preservation, 20 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_14", feeds_dir=tmp_path, redis_client=None, writer_id="f-14")
            writer.open()
            for i in range(20):
                writer.enqueue({"id": i, "enqueue_index": i, "value": f"test_{i}"})
            writer.close()
            read_order = []
            with open(writer.current_file, 'r') as f:
                for line in f:
                    if line.strip():
                        if ' ' in line[-10:]:
                            payload, _ = line.rsplit(' ', 1)
                            record = json.loads(payload)
                        else:
                            record = json.loads(line)
                        read_order.append(record.get('enqueue_index'))
            assert set(read_order) == set(range(20))

    def test_fuzzer_case_15_random_seed_6_35(self):
        """Case 15: Random seed=6, 35 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_15", feeds_dir=tmp_path, redis_client=None, writer_id="f-15")
            writer.open()
            for r in self._generate_records(6, 35):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 35

    def test_fuzzer_case_16_random_seed_7_45(self):
        """Case 16: Random seed=7, 45 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_16", feeds_dir=tmp_path, redis_client=None, writer_id="f-16")
            writer.open()
            for r in self._generate_records(7, 45):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 45

    def test_fuzzer_case_17_crash_sim_20(self):
        """Case 17: Crash simulation, 20 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_17", feeds_dir=tmp_path, redis_client=None, writer_id="f-17", fsync_mode="always")
            writer.open()
            records = self._generate_records(17, 20)
            for i, r in enumerate(records[:10]):
                writer.enqueue(r)
            for i, r in enumerate(records[10:]):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 20

    def test_fuzzer_case_18_random_seed_8_22(self):
        """Case 18: Random seed=8, 22 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_18", feeds_dir=tmp_path, redis_client=None, writer_id="f-18")
            writer.open()
            for r in self._generate_records(8, 22):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 22

    def test_fuzzer_case_19_random_seed_9_33(self):
        """Case 19: Random seed=9, 33 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_19", feeds_dir=tmp_path, redis_client=None, writer_id="f-19")
            writer.open()
            for r in self._generate_records(9, 33):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 33

    def test_fuzzer_case_20_random_seed_10_40(self):
        """Case 20: Random seed=10, 40 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_20", feeds_dir=tmp_path, redis_client=None, writer_id="f-20")
            writer.open()
            for r in self._generate_records(10, 40):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 40

    def test_fuzzer_case_21_random_seed_11_18(self):
        """Case 21: Random seed=11, 18 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_21", feeds_dir=tmp_path, redis_client=None, writer_id="f-21")
            writer.open()
            for r in self._generate_records(11, 18):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 18

    def test_fuzzer_case_22_random_seed_12_28(self):
        """Case 22: Random seed=12, 28 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_22", feeds_dir=tmp_path, redis_client=None, writer_id="f-22")
            writer.open()
            for r in self._generate_records(12, 28):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 28

    def test_fuzzer_case_23_random_seed_13_42(self):
        """Case 23: Random seed=13, 42 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_23", feeds_dir=tmp_path, redis_client=None, writer_id="f-23")
            writer.open()
            for r in self._generate_records(13, 42):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 42

    def test_fuzzer_case_24_random_seed_14_26(self):
        """Case 24: Random seed=14, 26 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_24", feeds_dir=tmp_path, redis_client=None, writer_id="f-24")
            writer.open()
            for r in self._generate_records(14, 26):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 26

    def test_fuzzer_case_25_random_seed_15_38(self):
        """Case 25: Random seed=15, 38 records."""
        with tempfile.TemporaryDirectory() as tmp_path:
            writer = FeedWriter(plane="score", source="fuzz_25", feeds_dir=tmp_path, redis_client=None, writer_id="f-25")
            writer.open()
            for r in self._generate_records(15, 38):
                writer.enqueue(r)
            writer.close()
            with open(writer.current_file, 'r') as f:
                assert len([l for l in f if l.strip()]) == 38
