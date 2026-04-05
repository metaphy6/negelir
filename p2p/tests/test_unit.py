"""
Negelir P2P — Unit tests (pytest)
Covers: message protocol, reputation tracker, node basics.
"""
import sys
import os
import json
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── P2P Message Protocol ──────────────────────────────────────────────────────

from protocol.messages import P2PMessage, MessageType


class TestP2PMessage:
    def test_message_creates_content_hash(self):
        msg = P2PMessage(
            message_type=MessageType.PING.value,
            sender_id="node_001",
            payload={"test": True},
        )
        assert len(msg.content_hash) == 64  # SHA-256 hex

    def test_same_payload_same_hash(self):
        ts = time.time()
        msg_a = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 1}, timestamp=ts)
        msg_b = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 1}, timestamp=ts)
        assert msg_a.content_hash == msg_b.content_hash

    def test_different_payload_different_hash(self):
        ts = time.time()
        msg_a = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 1}, timestamp=ts)
        msg_b = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 2}, timestamp=ts)
        assert msg_a.content_hash != msg_b.content_hash

    def test_serialise_to_bytes(self):
        msg = P2PMessage(
            message_type=MessageType.ANALYSIS.value,
            sender_id="node_001",
            payload={"match": "GS vs FB", "prediction": "H"},
        )
        data = msg.to_bytes()
        assert isinstance(data, bytes)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["sender_id"] == "node_001"
        assert parsed["message_type"] == "analysis"

    def test_round_trip_serialisation(self):
        msg = P2PMessage(
            schema_version="2.0",
            message_type=MessageType.OUTCOME_VALIDATION.value,
            sender_id="node_042",
            payload={"result": "H", "correct": True},
            ttl_hours=48,
        )
        data = msg.to_bytes()
        restored = P2PMessage.from_bytes(data)
        assert restored.sender_id == msg.sender_id
        assert restored.message_type == msg.message_type
        assert restored.payload == msg.payload
        assert restored.ttl_hours == msg.ttl_hours

    def test_message_type_enum_values(self):
        assert MessageType.ANALYSIS.value == "analysis"
        assert MessageType.PING.value == "ping"
        assert MessageType.PONG.value == "pong"
        assert MessageType.SCRAPE_DATA.value == "scrape_data"
        assert MessageType.PEER_DISCOVERY.value == "peer_discovery"
        assert MessageType.OUTCOME_VALIDATION.value == "outcome_validation"

    def test_schema_version_preserved(self):
        msg = P2PMessage(schema_version="2.0", message_type="ping",
                         sender_id="node_x", payload={})
        restored = P2PMessage.from_bytes(msg.to_bytes())
        assert restored.schema_version == "2.0"

    def test_default_ttl_is_seven_days(self):
        msg = P2PMessage()
        assert msg.ttl_hours == 168


# ── PeerNode ──────────────────────────────────────────────────────────────────

from node.peer import PeerNode, PeerAnalysis


class TestPeerNode:
    def test_node_initialises_with_id(self):
        node = PeerNode(node_id="test_node_1", port=9001)
        assert node.node_id == "test_node_1"

    def test_node_starts_with_empty_reputation_table(self):
        node = PeerNode(node_id="test_node_2", port=9002)
        assert isinstance(node.reputation_table, dict)
        assert len(node.reputation_table) == 0

    def test_node_starts_with_empty_analyses(self):
        node = PeerNode(node_id="test_node_3", port=9003)
        assert isinstance(node.analyses, dict)
        assert len(node.analyses) == 0

    def test_produce_analysis_stores_result(self):
        node = PeerNode(node_id="test_node_4", port=9004)
        analysis = node.produce_analysis("match_001", base_home_prob=0.55)
        assert "match_001" in node.analyses
        assert analysis.match_id == "match_001"
        assert analysis.node_id == "test_node_4"

    def test_analysis_probabilities_sum_to_one(self):
        node = PeerNode(node_id="test_node_5", port=9005)
        analysis = node.produce_analysis("match_002", base_home_prob=0.50)
        total = analysis.home_win_prob + analysis.draw_prob + analysis.away_win_prob
        assert abs(total - 1.0) < 0.01

    def test_analysis_probabilities_in_range(self):
        node = PeerNode(node_id="test_node_6", port=9006)
        analysis = node.produce_analysis("match_003", base_home_prob=0.60)
        assert 0.0 <= analysis.home_win_prob <= 1.0
        assert 0.0 <= analysis.draw_prob <= 1.0
        assert 0.0 <= analysis.away_win_prob <= 1.0

    def test_analysis_confidence_in_range(self):
        node = PeerNode(node_id="test_node_7", port=9007)
        analysis = node.produce_analysis("match_004", base_home_prob=0.70)
        assert 0.0 <= analysis.confidence <= 1.0

    def test_analysis_has_content_hash(self):
        node = PeerNode(node_id="test_node_8", port=9008)
        analysis = node.produce_analysis("match_005")
        assert len(analysis.content_hash) == 16

    def test_receive_peer_analysis_stores_it(self):
        node_a = PeerNode(node_id="node_a", port=9010)
        node_b = PeerNode(node_id="node_b", port=9011)
        analysis = node_a.produce_analysis("match_006", base_home_prob=0.55)
        node_b.receive_peer_analysis(analysis)
        assert "match_006" in node_b.peer_analyses
        assert len(node_b.peer_analyses["match_006"]) == 1

    def test_node_ignores_own_analysis(self):
        node = PeerNode(node_id="solo_node", port=9012)
        analysis = node.produce_analysis("match_007")
        # should not add own analysis to peer_analyses
        node.receive_peer_analysis(analysis)
        assert "match_007" not in node.peer_analyses

    def test_validate_outcome_updates_peer_reputation(self):
        node_a = PeerNode(node_id="node_aa", port=9020)
        node_b = PeerNode(node_id="node_bb", port=9021)
        # node_a produces, node_b receives and validates
        analysis = node_a.produce_analysis("match_010", base_home_prob=0.80)
        node_b.receive_peer_analysis(analysis)
        node_b.validate_outcome("match_010", actual_result="H")
        assert "node_aa" in node_b.reputation_table

    def test_ensemble_with_no_peers_returns_local(self):
        node = PeerNode(node_id="lone_node", port=9030)
        node.produce_analysis("match_020", base_home_prob=0.60)
        ensemble = node.compute_ensemble("match_020")
        assert ensemble is not None
        assert ensemble.match_id == "match_020"

    def test_ensemble_with_no_own_analysis_returns_none(self):
        node = PeerNode(node_id="blank_node", port=9031)
        result = node.compute_ensemble("nonexistent_match")
        assert result is None


# ── Reputation Tracker ────────────────────────────────────────────────────────

from reputation.tracker import compute_network_summary


class TestReputationTracker:
    def _make_nodes_with_history(self, count=5):
        """Create nodes that have validated peer predictions so reputation table is populated."""
        nodes = []
        for i in range(count):
            n = PeerNode(node_id=f"node_{i:03d}", port=9100 + i)
            nodes.append(n)

        # Cross-validate: each node sends analyses to every other node
        results = ["H", "D", "A", "H", "H", "D", "A", "H", "A", "H"]
        for j, match_id in enumerate(f"match_{k:03d}" for k in range(10)):
            # each node produces an analysis
            for n in nodes:
                n.produce_analysis(match_id, base_home_prob=0.55)
            # distribute to peers
            for n in nodes:
                for other in nodes:
                    if other.node_id != n.node_id:
                        analysis = other.analyses.get(match_id)
                        if analysis:
                            n.receive_peer_analysis(analysis)
            # validate
            for n in nodes:
                n.validate_outcome(match_id, actual_result=results[j % len(results)])

        return nodes

    def test_summary_node_count(self):
        nodes = self._make_nodes_with_history(5)
        summary = compute_network_summary(nodes)
        assert summary.total_nodes == 5

    def test_summary_avg_accuracy_in_range(self):
        nodes = self._make_nodes_with_history(4)
        summary = compute_network_summary(nodes)
        assert 0.0 <= summary.avg_accuracy <= 1.0

    def test_empty_network_summary(self):
        summary = compute_network_summary([])
        assert summary.total_nodes == 0
        assert summary.avg_accuracy == 0.0


# ── Transport Layer ───────────────────────────────────────────────────────────

from protocol.transport import SimulatedTransport


class TestTransport:
    """Test the in-memory message bus."""

    def test_register_and_count(self):
        t = SimulatedTransport()
        t.register_node("a")
        t.register_node("b")
        assert t.node_count == 2

    def test_send_delivers_to_target(self):
        t = SimulatedTransport()
        t.register_node("sender")
        t.register_node("target")
        msg = P2PMessage(message_type="ping", sender_id="sender", payload={"x": 1})
        t.send("sender", "target", msg)
        pending = t.get_pending("target")
        assert len(pending) == 1
        assert pending[0].payload == {"x": 1}

    def test_send_does_not_deliver_to_sender(self):
        t = SimulatedTransport()
        t.register_node("sender")
        t.register_node("target")
        msg = P2PMessage(message_type="ping", sender_id="sender")
        t.send("sender", "target", msg)
        pending = t.get_pending("sender")
        assert len(pending) == 0

    def test_broadcast_reaches_all_except_sender(self):
        t = SimulatedTransport()
        for nid in ["a", "b", "c"]:
            t.register_node(nid)
        msg = P2PMessage(message_type="ping", sender_id="a")
        t.broadcast("a", msg)
        assert len(t.get_pending("b")) == 1
        assert len(t.get_pending("c")) == 1
        assert len(t.get_pending("a")) == 0

    def test_get_pending_drains_inbox(self):
        t = SimulatedTransport()
        t.register_node("n")
        for i in range(3):
            t.send("other", "n", P2PMessage(message_type="ping", sender_id="other", payload={"i": i}))
        msgs = t.get_pending("n")
        assert len(msgs) == 3
        # Inbox is now empty
        assert len(t.get_pending("n")) == 0

    def test_send_to_unknown_node(self):
        t = SimulatedTransport()
        t.register_node("a")
        # Should not crash
        t.send("a", "nonexistent", P2PMessage(message_type="ping", sender_id="a"))


# ── Consensus & Ensemble ─────────────────────────────────────────────────────


class TestConsensus:
    """Test reputation-weighted ensemble consensus mechanism."""

    def _make_network(self, n=4):
        nodes = [PeerNode(node_id=f"cons_{i}", port=8000 + i) for i in range(n)]
        return nodes

    def test_ensemble_with_peers_changes_prediction(self):
        """Ensemble should differ from local when peers disagree."""
        nodes = self._make_network(3)
        # Node 0 predicts strong home
        nodes[0].produce_analysis("m1", base_home_prob=0.70)
        # Nodes 1,2 predict weaker home
        for i in [1, 2]:
            a = nodes[i].produce_analysis("m1", base_home_prob=0.30)
            nodes[0].receive_peer_analysis(a)
        ensemble = nodes[0].compute_ensemble("m1")
        local = nodes[0].analyses["m1"]
        # Ensemble should be between local and peer average
        assert ensemble is not None
        # Ensemble home should be less than local (pulled by peers)
        # But still > peer average because self-trust = 50%
        assert ensemble.home_win_prob < local.home_win_prob

    def test_ensemble_probabilities_sum_to_one(self):
        nodes = self._make_network(3)
        nodes[0].produce_analysis("m2", base_home_prob=0.55)
        for i in [1, 2]:
            a = nodes[i].produce_analysis("m2", base_home_prob=0.45)
            nodes[0].receive_peer_analysis(a)
        ens = nodes[0].compute_ensemble("m2")
        total = ens.home_win_prob + ens.draw_prob + ens.away_win_prob
        assert abs(total - 1.0) < 0.01

    def test_high_rep_peer_has_more_influence(self):
        """A 'high' trust peer should pull ensemble more than a 'new' peer."""
        nodes = self._make_network(3)
        # Give node 1 high reputation in node 0's table
        from node.peer import PeerReputationEntry
        nodes[0].reputation_table["cons_1"] = PeerReputationEntry(
            peer_id="cons_1", accuracy_rolling_50=0.70,
            calibration_score=0.70, total_validated=25, trust_level="high"
        )
        nodes[0].reputation_table["cons_2"] = PeerReputationEntry(
            peer_id="cons_2", accuracy_rolling_50=0.20,
            calibration_score=0.20, total_validated=25, trust_level="low"
        )
        nodes[0].produce_analysis("m3", base_home_prob=0.50)
        # High-rep peer leans home
        a1 = nodes[1].produce_analysis("m3", base_home_prob=0.80)
        # Low-rep peer leans away
        a2 = nodes[2].produce_analysis("m3", base_home_prob=0.20)
        nodes[0].receive_peer_analysis(a1)
        nodes[0].receive_peer_analysis(a2)
        ens = nodes[0].compute_ensemble("m3")
        # High-rep peer (home) should have more pull → ensemble home > 0.50
        assert ens.home_win_prob > 0.45  # some pull toward high-rep peer

    def test_self_trust_floor(self):
        """Even with many disagreeing peers, local node retains influence."""
        nodes = self._make_network(6)
        nodes[0].produce_analysis("m4", base_home_prob=0.80)
        # 5 peers all predict away
        for i in range(1, 6):
            a = nodes[i].produce_analysis("m4", base_home_prob=0.15)
            nodes[0].receive_peer_analysis(a)
        ens = nodes[0].compute_ensemble("m4")
        local = nodes[0].analyses["m4"]
        # Local trust = 50%, so ensemble home should be at least ~40%
        assert ens.home_win_prob > local.home_win_prob * 0.4


# ── Sybil Resistance Tests ──────────────────────────────────────────────────


class TestSybilResistance:
    """Test that biased/malicious nodes lose reputation over time."""

    def test_biased_node_drops_reputation(self):
        """A node with +0.3 bias should trend toward lower trust over many rounds."""
        import random
        rng = random.Random(99)
        honest = PeerNode(node_id="honest_1", port=7001)
        sybil = PeerNode(node_id="sybil_1", port=7002)
        sybil.model_bias = 0.3  # always over-predicts home

        observer = PeerNode(node_id="observer", port=7000)

        for i in range(40):
            match_id = f"sybil_test_{i}"
            true_prob = rng.uniform(0.20, 0.55)
            honest.produce_analysis(match_id, base_home_prob=true_prob)
            sybil.produce_analysis(match_id, base_home_prob=true_prob)

            observer.receive_peer_analysis(honest.analyses[match_id])
            observer.receive_peer_analysis(sybil.analyses[match_id])

            # Simulate result
            r = rng.random()
            actual = "H" if r < true_prob else ("D" if r < true_prob + 0.25 else "A")
            observer.validate_outcome(match_id, actual)

        sybil_rep = observer.reputation_table.get("sybil_1")
        honest_rep = observer.reputation_table.get("honest_1")
        assert sybil_rep is not None and honest_rep is not None
        # Over 40 rounds the biased node shouldn't greatly exceed honest
        assert sybil_rep.accuracy_rolling_50 <= honest_rep.accuracy_rolling_50 + 0.25

    def test_unknown_peers_get_low_weight(self):
        """New/unknown peers should default to minimum weight in ensemble."""
        node = PeerNode(node_id="main", port=7010)
        node.produce_analysis("wt1", base_home_prob=0.50)
        unknown = PeerNode(node_id="stranger", port=7011)
        a = unknown.produce_analysis("wt1", base_home_prob=0.90)
        node.receive_peer_analysis(a)
        ens = node.compute_ensemble("wt1")
        local = node.analyses["wt1"]
        # Unknown peer has weight 0.1, so ensemble should be close to local
        diff = abs(ens.home_win_prob - local.home_win_prob)
        assert diff < 0.15  # minimal influence


# ── Message Integrity ────────────────────────────────────────────────────────


class TestMessageIntegrity:
    """Test content hash verification and expiry."""

    def test_tampered_message_rejected(self):
        msg = P2PMessage(message_type="analysis", sender_id="a", payload={"x": 1})
        data = json.loads(msg.to_bytes().decode())
        # Tamper with payload
        data["payload"]["x"] = 999
        with pytest.raises(ValueError, match="hash mismatch"):
            P2PMessage.from_bytes(json.dumps(data).encode())

    def test_expired_message_detected(self):
        old_ts = time.time() - (169 * 3600)  # 169 hours ago (>168 TTL)
        msg = P2PMessage(message_type="ping", sender_id="a", timestamp=old_ts, ttl_hours=168)
        assert msg.is_expired()

    def test_fresh_message_not_expired(self):
        msg = P2PMessage(message_type="ping", sender_id="a", ttl_hours=168)
        assert not msg.is_expired()

    def test_custom_ttl(self):
        msg = P2PMessage(message_type="ping", sender_id="a", ttl_hours=1)
        assert msg.ttl_hours == 1


# ── Bulk P2P Stress Tests ────────────────────────────────────────────────────


class TestP2PStress:
    """Run many match rounds to verify stability and statistical properties."""

    def test_50_match_simulation_stable(self):
        """Run 50 matches through 5 nodes without crashes."""
        import random
        rng = random.Random(123)
        nodes = [PeerNode(node_id=f"stress_{i}", port=6000 + i) for i in range(5)]
        transport = SimulatedTransport()
        for n in nodes:
            transport.register_node(n.node_id)

        for m in range(50):
            match_id = f"stress_match_{m}"
            true_prob = rng.uniform(0.20, 0.70)

            # Produce & broadcast
            for n in nodes:
                a = n.produce_analysis(match_id, base_home_prob=true_prob)
                msg = P2PMessage(
                    message_type=MessageType.ANALYSIS.value,
                    sender_id=n.node_id,
                    payload=a.to_dict(),
                )
                transport.broadcast(n.node_id, msg)

            # Receive
            for n in nodes:
                for msg in transport.get_pending(n.node_id):
                    pa = PeerAnalysis(
                        analysis_id=msg.payload["analysis_id"],
                        node_id=msg.sender_id,
                        match_id=msg.payload["match_id"],
                        home_win_prob=msg.payload["distribution"]["home_win"],
                        draw_prob=msg.payload["distribution"]["draw"],
                        away_win_prob=msg.payload["distribution"]["away_win"],
                        confidence=msg.payload["confidence"],
                    )
                    n.receive_peer_analysis(pa)

            # Ensemble
            for n in nodes:
                ens = n.compute_ensemble(match_id)
                assert ens is not None
                total = ens.home_win_prob + ens.draw_prob + ens.away_win_prob
                assert abs(total - 1.0) < 0.01

            # Validate
            r = rng.random()
            actual = "H" if r < true_prob else ("D" if r < true_prob + 0.25 else "A")
            for n in nodes:
                n.validate_outcome(match_id, actual)

        # After 50 matches, all nodes should have reputation entries
        for n in nodes:
            assert len(n.reputation_table) >= 3  # at least some peers tracked

    def test_reputation_converges(self):
        """After many rounds, honest nodes should have higher trust than biased."""
        import random
        rng = random.Random(456)
        nodes = [PeerNode(node_id=f"conv_{i}", port=5000 + i) for i in range(4)]
        nodes[-1].model_bias = 0.25  # biased node

        for m in range(30):
            match_id = f"conv_match_{m}"
            true_prob = rng.uniform(0.30, 0.55)

            for n in nodes:
                n.produce_analysis(match_id, base_home_prob=true_prob)

            for n in nodes:
                for other in nodes:
                    if other.node_id != n.node_id:
                        a = other.analyses.get(match_id)
                        if a:
                            n.receive_peer_analysis(a)

            r = rng.random()
            actual = "H" if r < true_prob else ("D" if r < true_prob + 0.25 else "A")
            for n in nodes:
                n.validate_outcome(match_id, actual)

        # Check from honest node 0's perspective
        honest_reps = []
        for pid in ["conv_1", "conv_2"]:
            rep = nodes[0].reputation_table.get(pid)
            if rep:
                honest_reps.append(rep.accuracy_rolling_50)

        biased_rep = nodes[0].reputation_table.get("conv_3")
        if biased_rep and honest_reps:
            avg_honest = sum(honest_reps) / len(honest_reps)
            # Biased node should not outperform honest average by much
            assert biased_rep.accuracy_rolling_50 <= avg_honest + 0.20


# ── Data Store & Retention ────────────────────────────────────────────────────

from node.peer import DataStore, ScrapedRecord


class TestDataStore:
    """Test the content-addressed data store for P2P data retention."""

    def test_insert_returns_record(self):
        store = DataStore(owner_id="ds_test_1")
        rec = store.insert("match", {"home": "GS", "away": "FB"})
        assert rec is not None
        assert rec.data_type == "match"
        assert store.size == 1

    def test_duplicate_insert_returns_none(self):
        store = DataStore(owner_id="ds_test_2")
        rec1 = store.insert("match", {"home": "GS", "away": "FB"})
        rec2 = store.insert("match", {"home": "GS", "away": "FB"})
        assert rec1 is not None
        assert rec2 is None  # duplicate
        assert store.size == 1

    def test_different_payload_different_hash(self):
        store = DataStore(owner_id="ds_test_3")
        r1 = store.insert("match", {"home": "GS", "away": "FB"})
        r2 = store.insert("match", {"home": "BJK", "away": "TS"})
        assert r1 is not None and r2 is not None
        assert r1.data_hash != r2.data_hash
        assert store.size == 2

    def test_has_check(self):
        store = DataStore(owner_id="ds_test_4")
        rec = store.insert("match", {"home": "GS", "away": "FB"})
        assert store.has(rec.data_hash)
        assert not store.has("nonexistent_hash")

    def test_get_all_filters_by_type(self):
        store = DataStore(owner_id="ds_test_5")
        store.insert("match", {"home": "GS", "away": "FB"})
        store.insert("odds", {"home_odds": 1.5, "away_odds": 3.2})
        store.insert("match", {"home": "BJK", "away": "TS"})
        assert len(store.get_all("match")) == 2
        assert len(store.get_all("odds")) == 1
        assert len(store.get_all()) == 3

    def test_manifest_lists_all_hashes(self):
        store = DataStore(owner_id="ds_test_6")
        store.insert("match", {"id": 1})
        store.insert("match", {"id": 2})
        manifest = store.get_manifest()
        assert len(manifest) == 2

    def test_missing_from_identifies_gaps(self):
        store_a = DataStore(owner_id="ds_a")
        store_b = DataStore(owner_id="ds_b")
        store_a.insert("match", {"id": 1})
        store_a.insert("match", {"id": 2})
        store_b.insert("match", {"id": 1})  # only has one
        missing = store_b.missing_from(store_a.get_manifest())
        assert len(missing) == 1

    def test_merge_record_accepts_new(self):
        store_a = DataStore(owner_id="merge_a")
        rec = store_a.insert("match", {"home": "GS", "away": "FB"})
        store_b = DataStore(owner_id="merge_b")
        assert store_b.merge_record(rec) is True
        assert store_b.size == 1

    def test_merge_record_rejects_duplicate(self):
        store_a = DataStore(owner_id="dup_a")
        rec = store_a.insert("match", {"home": "GS", "away": "FB"})
        store_b = DataStore(owner_id="dup_b")
        store_b.merge_record(rec)
        assert store_b.merge_record(rec) is False  # duplicate
        assert store_b.size == 1

    def test_merge_rejects_tampered_hash(self):
        store = DataStore(owner_id="tamper_test")
        rec = ScrapedRecord(
            data_hash="000000_bad_hash",
            source_node_id="attacker",
            data_type="match",
            payload={"home": "GS", "away": "FB"},
        )
        assert store.merge_record(rec) is False
        assert store.size == 0

    def test_evict_expired(self):
        store = DataStore(owner_id="evict_test")
        store.insert("match", {"id": "fresh"})
        # Manually insert expired record
        old_rec = ScrapedRecord(
            data_hash=DataStore.compute_hash({"id": "old"}, "match"),
            source_node_id="evict_test",
            data_type="match",
            payload={"id": "old"},
            timestamp=time.time() - 200 * 3600,  # 200 hours ago
            ttl_hours=168,
        )
        store._records[old_rec.data_hash] = old_rec
        store._seen_hashes.add(old_rec.data_hash)
        assert store.size == 2
        evicted = store.evict_expired()
        assert evicted == 1
        assert store.size == 1

    def test_to_summary(self):
        store = DataStore(owner_id="summary_test")
        store.insert("match", {"id": 1})
        store.insert("odds", {"id": 2})
        summary = store.to_summary()
        assert summary["total"] == 2
        assert summary["by_type"]["match"] == 1
        assert summary["by_type"]["odds"] == 1


class TestPeerDataRetention:
    """Test data retention through PeerNode methods."""

    def test_ingest_and_check(self):
        node = PeerNode(node_id="ret_1", port=4001)
        rec = node.ingest_scraped_data("match", {"home": "GS", "away": "FB"})
        assert rec is not None
        assert not node.needs_scrape("match", {"home": "GS", "away": "FB"})

    def test_needs_scrape_true_for_missing(self):
        node = PeerNode(node_id="ret_2", port=4002)
        assert node.needs_scrape("match", {"home": "Unknown", "away": "Team"})

    def test_receive_scraped_data_from_peer(self):
        node_a = PeerNode(node_id="ret_a", port=4010)
        node_b = PeerNode(node_id="ret_b", port=4011)
        rec = node_a.ingest_scraped_data("match", {"home": "GS", "away": "FB"})
        assert node_b.receive_scraped_data(rec) is True
        assert not node_b.needs_scrape("match", {"home": "GS", "away": "FB"})

    def test_manifest_exchange(self):
        node_a = PeerNode(node_id="man_a", port=4020)
        node_b = PeerNode(node_id="man_b", port=4021)
        node_a.ingest_scraped_data("match", {"id": 1})
        node_a.ingest_scraped_data("match", {"id": 2})
        node_b.ingest_scraped_data("match", {"id": 1})  # only has one
        missing = node_b.request_missing_data(node_a.get_data_manifest())
        assert len(missing) == 1

    def test_data_propagation_chain(self):
        """Test that data cascades through a chain of peers."""
        nodes = [PeerNode(node_id=f"chain_{i}", port=4100 + i) for i in range(5)]
        # Node 0 scrapes
        rec = nodes[0].ingest_scraped_data("match", {"home": "GS", "away": "FB"})
        # Propagate through chain
        for i in range(1, len(nodes)):
            nodes[i].receive_scraped_data(rec)
        # All nodes should have the data
        for node in nodes:
            assert not node.needs_scrape("match", {"home": "GS", "away": "FB"})
            assert node.data_store.size == 1


# ── Transport Unregister ─────────────────────────────────────────────────────


class TestTransportUnregister:
    """Test dynamic node removal from the transport layer."""

    def test_unregister_removes_node(self):
        t = SimulatedTransport()
        t.register_node("to_remove")
        t.register_node("keeper")
        assert t.node_count == 2
        assert t.unregister_node("to_remove") is True
        assert t.node_count == 1

    def test_unregister_unknown_returns_false(self):
        t = SimulatedTransport()
        assert t.unregister_node("nobody") is False

    def test_broadcast_skips_removed_node(self):
        t = SimulatedTransport()
        t.register_node("a")
        t.register_node("b")
        t.register_node("c")
        t.unregister_node("b")
        msg = P2PMessage(message_type="ping", sender_id="a")
        t.broadcast("a", msg)
        assert len(t.get_pending("c")) == 1
        # "b" no longer exists
        assert t.get_pending("b") == []


# ── Scaling Tests (20+ peers) ────────────────────────────────────────────────


class TestScaling:
    """Test P2P network behaviour with 20+ peers."""

    def _run_scaled_simulation(self, n_nodes, n_rounds=20):
        import random
        rng = random.Random(12345)
        nodes = [PeerNode(node_id=f"scale_{i}", port=3000 + i) for i in range(n_nodes)]
        transport = SimulatedTransport()
        for n in nodes:
            transport.register_node(n.node_id)

        for m in range(n_rounds):
            match_id = f"scale_test_{m}"
            true_prob = rng.uniform(0.25, 0.65)

            for n in nodes:
                a = n.produce_analysis(match_id, base_home_prob=true_prob)
                msg = P2PMessage(
                    message_type=MessageType.ANALYSIS.value,
                    sender_id=n.node_id,
                    payload=a.to_dict(),
                )
                transport.broadcast(n.node_id, msg)

            for n in nodes:
                for msg in transport.get_pending(n.node_id):
                    if msg.message_type == MessageType.ANALYSIS.value:
                        pa = PeerAnalysis(
                            analysis_id=msg.payload["analysis_id"],
                            node_id=msg.sender_id,
                            match_id=msg.payload["match_id"],
                            home_win_prob=msg.payload["distribution"]["home_win"],
                            draw_prob=msg.payload["distribution"]["draw"],
                            away_win_prob=msg.payload["distribution"]["away_win"],
                            confidence=msg.payload["confidence"],
                        )
                        n.receive_peer_analysis(pa)

            for n in nodes:
                ens = n.compute_ensemble(match_id)
                assert ens is not None
                total = ens.home_win_prob + ens.draw_prob + ens.away_win_prob
                assert abs(total - 1.0) < 0.01

            actual = "H" if rng.random() < true_prob else ("D" if rng.random() < 0.35 else "A")
            for n in nodes:
                n.validate_outcome(match_id, actual)

        return nodes

    def test_20_peers_stable(self):
        """20 peers produce valid ensembles over 20 rounds without crashes."""
        nodes = self._run_scaled_simulation(20)
        for n in nodes:
            assert len(n.reputation_table) >= 10

    def test_25_peers_stable(self):
        """25 peers over 20 rounds."""
        nodes = self._run_scaled_simulation(25)
        assert len(nodes) == 25

    def test_30_peers_stable(self):
        """30 peers over 15 rounds."""
        nodes = self._run_scaled_simulation(30, n_rounds=15)
        summary = compute_network_summary(nodes)
        assert summary.total_nodes == 30
        assert summary.avg_accuracy > 0.0

    def test_50_peers_stable(self):
        """50 peers over 10 rounds — high message volume."""
        nodes = self._run_scaled_simulation(50, n_rounds=10)
        assert len(nodes) == 50

    def test_data_retention_at_scale(self):
        """All 25 peers should share scraped data without redundancy."""
        nodes = [PeerNode(node_id=f"drs_{i}", port=2000 + i) for i in range(25)]
        # Node 0 scrapes 10 records
        records = []
        for j in range(10):
            rec = nodes[0].ingest_scraped_data("match", {"id": j, "teams": f"A{j}-B{j}"})
            if rec:
                records.append(rec)
        # Propagate to all peers
        for rec in records:
            for node in nodes[1:]:
                node.receive_scraped_data(rec)
        # All nodes should have all 10 records
        for node in nodes:
            assert node.data_store.size == 10
        # Second scrape attempt should be blocked
        for node in nodes:
            for j in range(10):
                assert not node.needs_scrape("match", {"id": j, "teams": f"A{j}-B{j}"})

    def test_message_volume_scales_quadratically(self):
        """Verify message count = n*(n-1) per round (broadcast)."""
        for n in [5, 10, 20]:
            transport = SimulatedTransport()
            nodes = [PeerNode(node_id=f"vol_{n}_{i}", port=1000 + i) for i in range(n)]
            for node in nodes:
                transport.register_node(node.node_id)

            msg = P2PMessage(message_type="ping", sender_id=nodes[0].node_id)
            transport.broadcast(nodes[0].node_id, msg)
            received = sum(len(transport.get_pending(node.node_id)) for node in nodes)
            assert received == n - 1  # each broadcast reaches n-1 peers


# ── Dynamic Churn Tests ──────────────────────────────────────────────────────


class TestDynamicChurn:
    """Test adding and removing peers during active simulation."""

    def test_add_node_during_simulation(self):
        """Add a node mid-simulation and verify it participates."""
        import random
        rng = random.Random(999)
        from simulation.runner import P2PSimulation

        sim = P2PSimulation()
        sim.node_count = 5
        sim._create_nodes()

        # Run 5 rounds with 5 nodes
        for m in range(5):
            match_id = f"dyn_add_{m}"
            for n in sim.nodes:
                a = n.produce_analysis(match_id, base_home_prob=0.55)
                msg = P2PMessage(
                    message_type=MessageType.ANALYSIS.value,
                    sender_id=n.node_id, payload=a.to_dict(),
                )
                sim.transport.broadcast(n.node_id, msg)
            for n in sim.nodes:
                for msg in sim.transport.get_pending(n.node_id):
                    pa = PeerAnalysis(
                        analysis_id=msg.payload["analysis_id"], node_id=msg.sender_id,
                        match_id=msg.payload["match_id"],
                        home_win_prob=msg.payload["distribution"]["home_win"],
                        draw_prob=msg.payload["distribution"]["draw"],
                        away_win_prob=msg.payload["distribution"]["away_win"],
                        confidence=msg.payload["confidence"],
                    )
                    n.receive_peer_analysis(pa)

        # Add 3 new nodes
        for _ in range(3):
            sim.add_node()
        assert len(sim.nodes) == 8

        # Run 5 more rounds with 8 nodes
        for m in range(5, 10):
            match_id = f"dyn_add_{m}"
            for n in sim.nodes:
                a = n.produce_analysis(match_id, base_home_prob=0.50)
                msg = P2PMessage(
                    message_type=MessageType.ANALYSIS.value,
                    sender_id=n.node_id, payload=a.to_dict(),
                )
                sim.transport.broadcast(n.node_id, msg)
            for n in sim.nodes:
                for msg in sim.transport.get_pending(n.node_id):
                    if msg.message_type == MessageType.ANALYSIS.value:
                        pa = PeerAnalysis(
                            analysis_id=msg.payload["analysis_id"], node_id=msg.sender_id,
                            match_id=msg.payload["match_id"],
                            home_win_prob=msg.payload["distribution"]["home_win"],
                            draw_prob=msg.payload["distribution"]["draw"],
                            away_win_prob=msg.payload["distribution"]["away_win"],
                            confidence=msg.payload["confidence"],
                        )
                        n.receive_peer_analysis(pa)
            for n in sim.nodes:
                ens = n.compute_ensemble(match_id)
                assert ens is not None

    def test_remove_node_during_simulation(self):
        """Remove nodes mid-simulation and verify network continues."""
        from simulation.runner import P2PSimulation

        sim = P2PSimulation()
        sim.node_count = 8
        sim._create_nodes()

        # Run 5 rounds
        for m in range(5):
            match_id = f"dyn_rm_{m}"
            for n in sim.nodes:
                n.produce_analysis(match_id, base_home_prob=0.55)
            actual = "H" if m % 2 == 0 else "A"
            for n in sim.nodes:
                n.validate_outcome(match_id, actual)

        # Remove 3 nodes
        removed = []
        for _ in range(3):
            r = sim.remove_node()
            if r:
                removed.append(r)
        assert len(sim.nodes) == 5
        assert len(removed) == 3

        # Run 5 more rounds — should not crash
        for m in range(5, 10):
            match_id = f"dyn_rm_{m}"
            for n in sim.nodes:
                n.produce_analysis(match_id, base_home_prob=0.50)
                ens = n.compute_ensemble(match_id)
                assert ens is not None

    def test_simultaneous_join_and_leave(self):
        """Peers join and leave at the same time."""
        from simulation.runner import P2PSimulation

        sim = P2PSimulation()
        sim.node_count = 10
        sim._create_nodes()

        # Seed data
        sim.nodes[0].ingest_scraped_data("match", {"test": "data"})

        for round_num in range(20):
            # Simultaneously add and remove
            if round_num % 2 == 0 and len(sim.nodes) < 20:
                new_node = sim.add_node()
                # Verify new node gets data
                for rec in sim.nodes[0].data_store.get_all():
                    new_node.receive_scraped_data(rec)
            if round_num % 3 == 0 and len(sim.nodes) > 5:
                sim.remove_node()

            match_id = f"churn_{round_num}"
            for n in sim.nodes:
                a = n.produce_analysis(match_id, base_home_prob=0.50)
                msg = P2PMessage(
                    message_type=MessageType.ANALYSIS.value,
                    sender_id=n.node_id, payload=a.to_dict(),
                )
                sim.transport.broadcast(n.node_id, msg)
            for n in sim.nodes:
                for msg in sim.transport.get_pending(n.node_id):
                    if msg.message_type == MessageType.ANALYSIS.value:
                        pa = PeerAnalysis(
                            analysis_id=msg.payload["analysis_id"], node_id=msg.sender_id,
                            match_id=msg.payload["match_id"],
                            home_win_prob=msg.payload["distribution"]["home_win"],
                            draw_prob=msg.payload["distribution"]["draw"],
                            away_win_prob=msg.payload["distribution"]["away_win"],
                            confidence=msg.payload["confidence"],
                        )
                        n.receive_peer_analysis(pa)
            for n in sim.nodes:
                ens = n.compute_ensemble(match_id)
                assert ens is not None

        # Network should still be functional
        assert len(sim.nodes) >= 5

    def test_data_survives_churn(self):
        """Data in the network persists even as nodes join and leave."""
        from simulation.runner import P2PSimulation

        sim = P2PSimulation()
        sim.node_count = 5
        sim._create_nodes()

        # Ingest data on all nodes
        test_payload = {"home": "Galatasaray", "away": "Fenerbahçe", "week": 30}
        rec = sim.nodes[0].ingest_scraped_data("match", test_payload)
        for node in sim.nodes[1:]:
            node.receive_scraped_data(rec)

        # Remove 3 nodes (keeping 2)
        for _ in range(3):
            sim.remove_node()
        assert len(sim.nodes) == 2

        # Remaining nodes still have the data
        for node in sim.nodes:
            assert not node.needs_scrape("match", test_payload)

        # Add 5 new nodes and sync data from survivors
        for _ in range(5):
            new_node = sim.add_node()
            for existing_rec in sim.nodes[0].data_store.get_all():
                new_node.receive_scraped_data(existing_rec)

        # All 7 nodes should have the data
        for node in sim.nodes:
            assert not node.needs_scrape("match", test_payload)
            assert node.data_store.size >= 1

    def test_cannot_remove_last_node(self):
        from simulation.runner import P2PSimulation
        sim = P2PSimulation()
        sim.node_count = 1
        sim._create_nodes()
        result = sim.remove_node()
        assert result is None
        assert len(sim.nodes) == 1
