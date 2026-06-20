"""Phase 21.1 §21.1 — Suspension lifecycle tests.

Tests for suspension expiration logic:
  - Active suspensions while matches_remaining > 0
  - Decrement matches_remaining after relevant post-match event
  - Expiration requires both: matches_remaining = 0 AND match ID resolved
  - Competition-scoped: other competitions don't decrement
  - Expiration reasons and status queries

Per ROADMAP §21.1 bullet 7 and ENRICHMENT_DATA.md §2.1.
Minimum 8 tests including ≥ 2 adversarial.
"""

from __future__ import annotations

import pytest

from ai.scraper.suspension_lifecycle import (
    should_expire,
    decrement_matches_remaining,
    is_active,
    get_expiration_reason,
)


class TestSuspensionExpiration:
    """Tests for suspension expiration conditions."""
    
    def test_active_when_matches_remaining(self) -> None:
        """Suspension should be active while matches_remaining > 0."""
        is_exp = should_expire(
            matches_remaining=3,
            expires_after_match_id="M_001",
            resolved_match_id=None,
        )
        assert is_exp is False
    
    def test_active_when_matches_exactly_one(self) -> None:
        """Suspension should be active with exactly 1 match remaining."""
        is_exp = should_expire(
            matches_remaining=1,
            expires_after_match_id="M_001",
            resolved_match_id=None,
        )
        assert is_exp is False
    
    def test_expires_when_no_trigger_match(self) -> None:
        """Suspension expires immediately when matches_remaining=0 and no trigger match."""
        is_exp = should_expire(
            matches_remaining=0,
            expires_after_match_id=None,
            resolved_match_id=None,
        )
        assert is_exp is True
    
    def test_active_when_trigger_not_resolved(self) -> None:
        """Suspension stays active if trigger match not yet resolved."""
        is_exp = should_expire(
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id=None,
        )
        assert is_exp is False
    
    def test_expires_when_trigger_resolved(self) -> None:
        """Suspension expires when matches_remaining=0 and trigger match resolved."""
        is_exp = should_expire(
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id="M_100",
        )
        assert is_exp is True
    
    def test_expires_when_resolved_after_trigger(self) -> None:
        """Suspension expires if resolved match ID is after trigger."""
        is_exp = should_expire(
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id="M_101",
        )
        assert is_exp is True


class TestMatchesRemainingDecrement:
    """Tests for matches_remaining decrement logic."""
    
    def test_decrement_relevant_match(self) -> None:
        """Post-match in same competition should decrement."""
        result = decrement_matches_remaining(
            current_matches_remaining=3,
            post_match_is_relevant=True,
        )
        assert result == 2
    
    def test_no_decrement_irrelevant_match(self) -> None:
        """Post-match in different competition should not decrement."""
        result = decrement_matches_remaining(
            current_matches_remaining=3,
            post_match_is_relevant=False,
        )
        assert result == 3
    
    def test_decrement_to_zero(self) -> None:
        """Decrement should reach zero."""
        result = decrement_matches_remaining(
            current_matches_remaining=1,
            post_match_is_relevant=True,
        )
        assert result == 0
    
    def test_no_negative_decrement(self) -> None:
        """Should not decrement below zero."""
        result = decrement_matches_remaining(
            current_matches_remaining=0,
            post_match_is_relevant=True,
        )
        assert result == 0


class TestSuspensionActiveQuery:
    """Tests for is_active() convenience function."""
    
    def test_is_active_true_with_matches(self) -> None:
        """is_active should be True while matches_remaining > 0."""
        active = is_active(
            matches_remaining=2,
            expires_after_match_id="M_001",
            resolved_match_id=None,
        )
        assert active is True
    
    def test_is_active_false_when_expired(self) -> None:
        """is_active should be False when suspension expired."""
        active = is_active(
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id="M_100",
        )
        assert active is False


class TestExpirationReason:
    """Tests for human-readable expiration reasons."""
    
    def test_reason_matches_remaining(self) -> None:
        """Reason should show remaining matches."""
        reason = get_expiration_reason(
            should_expire_bool=False,
            matches_remaining=3,
            expires_after_match_id=None,
        )
        assert "3" in reason and "match" in reason
    
    def test_reason_pending_match(self) -> None:
        """Reason should mention pending match when not resolved."""
        reason = get_expiration_reason(
            should_expire_bool=False,
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id=None,
        )
        assert "M_100" in reason
    
    def test_reason_expired(self) -> None:
        """Reason should indicate expiration."""
        reason = get_expiration_reason(
            should_expire_bool=True,
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id="M_100",
        )
        assert "Expired" in reason


class TestSuspensionLifecycleWorkflow:
    """Integration tests — realistic suspension lifecycle."""
    
    def test_workflow_accumulation_to_expiration(self) -> None:
        """Test complete suspension lifecycle: accumulation → decrement → expiration."""
        # Step 1: Player receives 3-match suspension after match M_001
        matches_rem = 3
        trigger_match = "M_100"  # Match after which suspension expires
        assert is_active(matches_rem, trigger_match, None) is True
        
        # Step 2: First relevant match played — decrement
        matches_rem = decrement_matches_remaining(matches_rem, post_match_is_relevant=True)
        assert matches_rem == 2
        assert is_active(matches_rem, trigger_match, None) is True
        
        # Step 3: Second match played
        matches_rem = decrement_matches_remaining(matches_rem, post_match_is_relevant=True)
        assert matches_rem == 1
        assert is_active(matches_rem, trigger_match, None) is True
        
        # Step 4: Third match played
        matches_rem = decrement_matches_remaining(matches_rem, post_match_is_relevant=True)
        assert matches_rem == 0
        # Trigger match not yet resolved — still active
        assert is_active(matches_rem, trigger_match, None) is True
        
        # Step 5: Trigger match is resolved (or any match after it)
        resolved = "M_100"
        assert is_active(matches_rem, trigger_match, resolved) is False
    
    def test_workflow_different_competitions(self) -> None:
        """Suspensions should not decrement for matches in different competitions."""
        # 2-match suspension in La Liga
        matches_rem = 2
        trigger_match = "LIGA_500"
        
        # Match in other competition (e.g., Copa del Rey) should not affect
        matches_rem = decrement_matches_remaining(matches_rem, post_match_is_relevant=False)
        assert matches_rem == 2  # No decrement
        
        # La Liga match should decrement
        matches_rem = decrement_matches_remaining(matches_rem, post_match_is_relevant=True)
        assert matches_rem == 1
    
    def test_workflow_indefinite_suspension(self) -> None:
        """Indefinite suspension (no expires_after_match_id) expires when matches_remaining=0."""
        # Indefinite doping suspension: 5 matches, no specific trigger
        matches_rem = 5
        assert is_active(matches_rem, None, None) is True
        
        # Decrement through all matches
        for _ in range(5):
            matches_rem = decrement_matches_remaining(matches_rem, post_match_is_relevant=True)
        
        # When matches_remaining=0 and no trigger, suspension expires immediately
        assert matches_rem == 0
        assert is_active(matches_rem, None, None) is False


class TestSuspensionEdgeCases:
    """Adversarial tests — edge cases and boundary conditions."""
    
    def test_zero_matches_starting_point(self) -> None:
        """Suspension with 0 matches_remaining (edge case)."""
        result = decrement_matches_remaining(
            current_matches_remaining=0,
            post_match_is_relevant=True,
        )
        assert result == 0
    
    def test_negative_matches_prevented(self) -> None:
        """Should never go negative."""
        result = decrement_matches_remaining(
            current_matches_remaining=-1,
            post_match_is_relevant=True,
        )
        assert result == 0
    
    def test_match_id_comparison_lexicographic(self) -> None:
        """Match ID comparison should work lexicographically."""
        # M_101 > M_100 lexicographically
        is_exp_after = should_expire(
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id="M_101",
        )
        assert is_exp_after is True
        
        # M_099 < M_100 lexicographically
        is_exp_before = should_expire(
            matches_remaining=0,
            expires_after_match_id="M_100",
            resolved_match_id="M_099",
        )
        assert is_exp_before is False
