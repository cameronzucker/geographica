"""Tests for the natural language intent parser and category extraction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from spatial import parse_intent


class TestPlainIntent:
    def test_place_name(self):
        result = parse_intent("Phoenix", has_position=True, has_route=False)
        assert result["intent"] == "plain"
        assert result["category"] is None

    def test_unknown_text(self):
        result = parse_intent("asdfghjkl", has_position=False, has_route=False)
        assert result["intent"] == "plain"


class TestProximityIntent:
    def test_nearest(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"
        assert result["search_text"] == "gas station"

    def test_closest(self):
        result = parse_intent("closest hospital", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "hospital"

    def test_near_me(self):
        result = parse_intent("hospitals near me", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "hospital"

    def test_near_here(self):
        result = parse_intent("gas near here", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_nearby(self):
        result = parse_intent("nearby restaurants", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "restaurant"

    def test_within_miles(self):
        result = parse_intent("gas stations within 10 miles", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"
        assert result["radius_m"] is not None
        assert abs(result["radius_m"] - 16093) < 100  # 10 miles

    def test_within_km(self):
        result = parse_intent("hospitals within 5 km", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["radius_m"] is not None
        assert abs(result["radius_m"] - 5000) < 100


class TestCorridorIntent:
    def test_along_my_route(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "gas station"

    def test_along_route(self):
        result = parse_intent("restaurants along route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "restaurant"

    def test_on_my_route(self):
        result = parse_intent("hotels on my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "hotel"

    def test_every_n_miles(self):
        result = parse_intent("gas stations every 50 miles along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "gas station"
        assert result["interval_m"] is not None
        assert abs(result["interval_m"] - 80467) < 100  # 50 miles


class TestFallbackChain:
    def test_corridor_falls_back_to_proximity_without_route(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["original_intent"] == "route_corridor"
        assert result["fallback_reason"] == "no_route"

    def test_corridor_falls_back_to_plain_without_anything(self):
        result = parse_intent("gas stations along my route", has_position=False, has_route=False)
        assert result["intent"] == "plain"
        assert result["original_intent"] == "route_corridor"
        assert result["fallback_reason"] == "no_position"

    def test_proximity_falls_back_to_plain_without_position(self):
        result = parse_intent("nearest hospital", has_position=False, has_route=False)
        assert result["intent"] == "plain"
        assert result["original_intent"] == "proximity"
        assert result["fallback_reason"] == "no_position"


class TestCategoryExtraction:
    def test_filler_words_stripped(self):
        result = parse_intent("find the nearest gas station", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_plural_normalization(self):
        result = parse_intent("nearest hospitals", has_position=True, has_route=False)
        assert result["category"] == "hospital"

    def test_plural_gas_stations(self):
        result = parse_intent("nearest gas stations", has_position=True, has_route=False)
        assert result["category"] == "gas station"

    def test_unrecognized_business_name(self):
        result = parse_intent("Filibertos near me", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] is None
        assert "filibertos" in result["search_text"].lower()

    def test_route_66_not_confused_with_corridor(self):
        """'Route 66' should NOT trigger corridor intent."""
        result = parse_intent("Route 66 near me", has_position=True, has_route=True)
        assert result["intent"] == "proximity"
        assert "route 66" in result["search_text"].lower()


class TestImplicitProximity:
    def test_bare_category_with_position(self):
        result = parse_intent("gas", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_bare_category_without_position(self):
        result = parse_intent("gas", has_position=False, has_route=False)
        assert result["intent"] == "plain"

    def test_bare_summit(self):
        result = parse_intent("summit", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "summit"
        assert result["gnis_class"] == "Summit"


class TestGNISClasses:
    def test_hospital_has_gnis_class(self):
        result = parse_intent("nearest hospital", has_position=True, has_route=False)
        assert result["gnis_class"] == "Hospital"

    def test_gas_station_has_no_gnis_class(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["gnis_class"] is None

    def test_dam_has_gnis_class(self):
        result = parse_intent("nearest dam", has_position=True, has_route=False)
        assert result["gnis_class"] == "Dam"


class TestCityPlaceExtraction:
    def test_category_in_city(self):
        result = parse_intent("gas stations in flagstaff", has_position=False, has_route=False)
        assert result["place_name"] == "flagstaff"
        assert result["category"] == "gas station"
        assert result["intent"] == "city_proximity"

    def test_category_in_city_uppercase(self):
        result = parse_intent("Gas Stations In Flagstaff", has_position=False, has_route=False)
        assert result["place_name"] == "Flagstaff"
        assert result["category"] == "gas station"
        assert result["intent"] == "city_proximity"

    def test_multi_word_city(self):
        result = parse_intent("restaurants in las vegas", has_position=False, has_route=False)
        assert result["place_name"] == "las vegas"
        assert result["category"] == "restaurant"

    def test_city_with_state_suffix(self):
        result = parse_intent("gas stations in phoenix, az", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix, az"
        assert result["category"] == "gas station"

    def test_trailing_punctuation_stripped(self):
        result = parse_intent("gas stations in phoenix!", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"

    def test_trailing_period_stripped(self):
        result = parse_intent("gas stations in phoenix.", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"

    def test_zip_code_as_place(self):
        result = parse_intent("gas stations in 85001", has_position=False, has_route=False)
        assert result["place_name"] == "85001"
        assert result["category"] == "gas station"

    def test_no_place_after_in(self):
        result = parse_intent("gas stations in", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_empty_before_in(self):
        result = parse_intent("in flagstaff", has_position=True, has_route=False)
        assert result["place_name"] is None
        assert result["intent"] == "plain"

    def test_in_inside_word_not_matched(self):
        result = parse_intent("drinking water in phoenix", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"
        assert result["category"] == "water"


class TestCompoundInPhrases:
    def test_drive_in_hyphenated_no_second_in(self):
        result = parse_intent("drive-in theater", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_drive_in_hyphenated_with_city(self):
        result = parse_intent("drive-in restaurants in phoenix", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"
        assert result["category"] == "restaurant"

    def test_drive_in_unhyphenated_with_city(self):
        result = parse_intent("drive in restaurants in phoenix", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"
        assert result["category"] == "restaurant"

    def test_walk_in_clinic_no_city(self):
        result = parse_intent("walk-in clinic", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_dine_in_with_city(self):
        result = parse_intent("dine in restaurants in mesa", has_position=False, has_route=False)
        assert result["place_name"] == "mesa"
        assert result["category"] == "restaurant"


class TestApproachCFallback:
    def test_brand_in_city(self):
        result = parse_intent("shell in tucson", has_position=False, has_route=False)
        assert result["place_name"] == "tucson"
        assert result["category"] is None
        assert result["search_text"] == "shell"
        assert result["intent"] == "city_proximity"

    def test_unknown_business_in_city(self):
        result = parse_intent("filibertos in mesa", has_position=False, has_route=False)
        assert result["place_name"] == "mesa"
        assert result["category"] is None
        assert "filibertos" in result["search_text"].lower()


class TestExistingIntentsRegression:
    def test_plain_has_no_place(self):
        result = parse_intent("Phoenix", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_proximity_has_no_place(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_corridor_has_no_place(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=True)
        assert result["place_name"] is None

    def test_fallback_has_no_place(self):
        result = parse_intent("nearest hospital", has_position=False, has_route=False)
        assert result["place_name"] is None

    def test_implicit_proximity_has_no_place(self):
        result = parse_intent("gas", has_position=True, has_route=False)
        assert result["place_name"] is None


class TestCityCorridorIntent:
    def test_city_corridor_with_route(self):
        result = parse_intent("gas stations in flagstaff along my route",
                              has_position=True, has_route=True)
        assert result["intent"] == "city_corridor"
        assert result["place_name"] == "flagstaff"
        assert result["category"] == "gas station"

    def test_city_corridor_on_route(self):
        result = parse_intent("restaurants in phoenix on my route",
                              has_position=True, has_route=True)
        assert result["intent"] == "city_corridor"
        assert result["place_name"] == "phoenix"
        assert result["category"] == "restaurant"

    def test_city_corridor_every_n_miles(self):
        result = parse_intent("gas stations in flagstaff every 50 miles",
                              has_position=True, has_route=True)
        assert result["intent"] == "city_corridor"
        assert result["place_name"] == "flagstaff"
        assert result["interval_m"] is not None

    def test_city_corridor_falls_back_without_route(self):
        result = parse_intent("gas stations in flagstaff along my route",
                              has_position=True, has_route=False)
        assert result["intent"] == "city_proximity"
        assert result["original_intent"] == "city_corridor"
        assert result["fallback_reason"] == "no_route"
        assert result["place_name"] == "flagstaff"

    def test_city_corridor_falls_back_without_anything(self):
        result = parse_intent("gas stations in flagstaff along my route",
                              has_position=False, has_route=False)
        assert result["intent"] == "city_proximity"
        assert result["original_intent"] == "city_corridor"
        assert result["fallback_reason"] == "no_route"
