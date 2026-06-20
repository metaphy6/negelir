"""CI lint gate for promotion pre-flight requirements."""
from __future__ import annotations
from typing import Dict, Any


class PromotionPreflightLint:
    """Enforces preflight requirements for tier-flip PRs."""
    
    def check_pr_tier_change(
        self,
        league_id: str,
        new_tier: str,
        has_passing_preflight: bool = False,
    ) -> Dict[str, Any]:
        """Check if a tier change is allowed based on preflight status.
        
        Args:
            league_id: The league being promoted
            new_tier: Target tier (T2, T1)
            has_passing_preflight: Whether a recent passing preflight exists
        
        Returns:
            Dict with 'allowed' (bool) and 'reason' (str)
        """
        if new_tier != "T2" and new_tier != "T1":
            return {"allowed": False, "reason": "Invalid target tier"}
        
        # Tier change (from T3 to T2/T1) requires preflight
        if not has_passing_preflight:
            return {
                "allowed": False,
                "reason": f"Tier change to {new_tier} requires a passing preflight report"
            }
        
        return {"allowed": True, "reason": "Preflight passed"}
