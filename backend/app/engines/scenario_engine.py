"""Trade scenario engine (section 19).

Builds entry zone / preferred entry / invalidation / resistance scenarios
purely from actual technical levels already computed by technical_engine.py.
No guaranteed targets -- only "scenario" / "potential objective" framing.
"""

from app.engines.technical_engine import TechnicalResult
from app.schemas.common import ScenarioLevels


def build_scenarios(last_close: float, technical: TechnicalResult) -> ScenarioLevels:
    support = technical.support_level if technical.support_level is not None else last_close * 0.95
    resistance = technical.resistance_level if technical.resistance_level is not None else last_close * 1.05
    atr = technical.atr_14 if technical.atr_14 is not None else last_close * 0.02

    entry_zone_low = round(min(last_close, support + atr * 0.25), 2)
    entry_zone_high = round(max(last_close, support + atr * 0.75), 2)
    preferred_entry = round(last_close, 2)
    invalidation = round(support - atr * 0.25, 2)

    resistance_1 = round(resistance, 2)
    resistance_2 = round(resistance + atr * 2, 2)

    return ScenarioLevels(
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        preferred_entry=preferred_entry,
        invalidation=invalidation,
        resistance_scenario_1=resistance_1,
        resistance_scenario_1_label="Potential objective (near-term resistance)",
        resistance_scenario_2=resistance_2,
        resistance_scenario_2_label="Potential objective (extended scenario)",
    )
