from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from routing.services.corridor import CandidateStation
from routing.services.errors import (
    INFEASIBLE_PLAN_DETAIL,
    ORIGIN_CATCHMENT_MISSING_DETAIL,
    NoFeasiblePlanError,
)

COST_MODEL = 'segment_consumption_priced_at_departure_stop'

QUANT_GAL = Decimal('0.0001')
QUANT_DOL = Decimal('0.01')
QUANT_MI = Decimal('0.001')


@dataclass
class StationInfo:
    opis_truckstop_id: int
    truckstop_name: str
    address: str
    city: str
    state: str
    rack_id: str
    retail_price: Decimal
    latitude: Decimal
    longitude: Decimal
    natural_key_hash: str


@dataclass
class FuelStopPlanEntry:
    is_origin_catchment_entry: bool
    station: StationInfo
    route_mileage_at_departure: Decimal
    next_stop_route_mileage: Decimal
    segment_miles: Decimal
    segment_gallons_consumed: Decimal
    segment_cost: Decimal
    distance_from_route_poly_miles: Decimal


@dataclass
class FuelOptimizerPlan:
    cost_model: str = COST_MODEL
    stops: list[FuelStopPlanEntry] = field(default_factory=list)
    total_gallons_consumed: Decimal = Decimal('0')
    total_cost: Decimal = Decimal('0')
    total_stops: int = 0
    origin_fueled_at_stop_index: int | None = None
    origin_catchment_radius_miles_used: Decimal = Decimal('0')
    origin_catchment_station: StationInfo | None = None


class _MilestoneNode:
    def __init__(
        self,
        node_id: int,
        route_mileage: Decimal,
        retail_price: Decimal | None,
        candidate: CandidateStation | None,
        is_origin_catchment: bool = False,
        is_destination: bool = False,
    ):
        self.node_id = node_id
        self.route_mileage = route_mileage
        self.retail_price = retail_price
        self.candidate = candidate
        self.is_origin_catchment = is_origin_catchment
        self.is_destination = is_destination


def _q(value: Decimal | int | float, quant: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def _build_station_info(cand: CandidateStation) -> StationInfo:
    return StationInfo(
        opis_truckstop_id=cand.opis_truckstop_id,
        truckstop_name=cand.truckstop_name,
        address=cand.record.address,
        city=cand.city,
        state=cand.state,
        rack_id=cand.record.rack_id,
        retail_price=cand.retail_price,
        latitude=cand.latitude,
        longitude=cand.longitude,
        natural_key_hash=cand.natural_key_hash,
    )


def _tiebreak_key(
    total_cost: Decimal,
    num_stops: int,
    node_ids: list[int],
    nodes: list[_MilestoneNode],
) -> tuple[Decimal, int, tuple[float, ...], tuple[str, ...]]:
    route_positions: tuple[float, ...] = tuple(
        float(nodes[nid].route_mileage) for nid in node_ids if not nodes[nid].is_destination
    )
    near_scores: list[float] = []
    keys: list[str] = []
    for nid in node_ids:
        n = nodes[nid]
        if n.is_destination or n.candidate is None:
            near_scores.append(0.0)
            keys.append('')
        else:
            near_scores.append(float(n.candidate.distance_from_route_poly_miles))
            keys.append(str(n.candidate.natural_key_hash))
    return (total_cost, num_stops, tuple(sorted(near_scores)) + route_positions, tuple(sorted(keys)))


def compute_optimized_fuel_plan(
    origin_catchment_station: CandidateStation | None,
    corridor_candidates: list[CandidateStation],
    total_route_distance_miles: Decimal,
    max_range_miles: Decimal,
    miles_per_gallon: Decimal,
    origin_catchment_radius_miles_used: Decimal | None = None,
) -> FuelOptimizerPlan:
    if origin_catchment_station is None:
        raise NoFeasiblePlanError(ORIGIN_CATCHMENT_MISSING_DETAIL)

    if miles_per_gallon <= 0:
        raise NoFeasiblePlanError('miles_per_gallon must be positive')
    if max_range_miles <= 0:
        raise NoFeasiblePlanError('max_range_miles must be positive')
    if total_route_distance_miles < 0:
        raise NoFeasiblePlanError('total_route_distance_miles must be non-negative')

    mpg_d = Decimal(str(miles_per_gallon))
    range_d = Decimal(str(max_range_miles))
    total_dist_d = Decimal(str(total_route_distance_miles))

    origin_key = origin_catchment_station.natural_key_hash
    origin_milestone_mileage = Decimal('0')

    nodes: list[_MilestoneNode] = []
    node_idx = 0
    origin_node = _MilestoneNode(
        node_id=node_idx,
        route_mileage=origin_milestone_mileage,
        retail_price=origin_catchment_station.retail_price,
        candidate=origin_catchment_station,
        is_origin_catchment=True,
    )
    nodes.append(origin_node)
    node_idx += 1

    for cand in corridor_candidates:
        if cand.natural_key_hash == origin_key:
            continue
        if cand.route_mileage <= 0.0:
            continue
        if float(total_dist_d) - cand.route_mileage < -1e-6:
            continue
        nodes.append(
            _MilestoneNode(
                node_id=node_idx,
                route_mileage=Decimal(str(cand.route_mileage)),
                retail_price=cand.retail_price,
                candidate=cand,
            )
        )
        node_idx += 1

    nodes.sort(key=lambda n: (float(n.route_mileage), n.is_destination, n.node_id))
    for i, n in enumerate(nodes):
        n.node_id = i

    destination_node = _MilestoneNode(
        node_id=len(nodes),
        route_mileage=total_dist_d,
        retail_price=None,
        candidate=None,
        is_destination=True,
    )
    nodes.append(destination_node)
    n_nodes = len(nodes)

    if float(total_dist_d) - 0.0 <= float(range_d) + 1e-9:
        pass

    INFINITY_COST = Decimal('1e30')
    dp_cost: list[Decimal] = [INFINITY_COST] * n_nodes
    dp_prev: list[int | None] = [None] * n_nodes
    dp_stops: list[int] = [0] * n_nodes
    dp_cost[0] = Decimal('0')

    for i in range(n_nodes):
        if dp_cost[i] == INFINITY_COST:
            continue
        ni = nodes[i]
        for j in range(i + 1, n_nodes):
            nj = nodes[j]
            seg_miles = nj.route_mileage - ni.route_mileage
            if seg_miles < 0:
                continue
            if seg_miles > range_d:
                if not nj.is_destination:
                    continue
                if seg_miles > range_d:
                    continue
            if ni.retail_price is None and not ni.is_origin_catchment:
                continue
            price = ni.retail_price
            if price is None:
                continue
            gallons = seg_miles / mpg_d
            edge_cost = gallons * price
            new_total = dp_cost[i] + edge_cost
            stops_added = 0 if nj.is_destination else 1
            new_stops = dp_stops[i] + stops_added
            is_better = False
            if new_total < dp_cost[j] - Decimal('1e-12'):
                is_better = True
            elif abs(new_total - dp_cost[j]) < Decimal('1e-9'):
                if new_stops < dp_stops[j]:
                    is_better = True
                elif new_stops == dp_stops[j] and dp_prev[j] is not None:
                    cur_path_ids: list[int] = []
                    p: int | None = j
                    while p is not None:
                        cur_path_ids.append(p)
                        p = dp_prev[p]
                    cur_path_ids.reverse()
                    new_path_ids: list[int] = []
                    p2: int | None = j
                    p2_over = i
                    while p2 is not None:
                        new_path_ids.append(p2)
                        if p2 == j:
                            p2 = p2_over
                        else:
                            p2 = dp_prev[p2]
                    new_path_ids.reverse()
                    cur_key = _tiebreak_key(dp_cost[j], dp_stops[j], cur_path_ids, nodes)
                    new_key = _tiebreak_key(new_total, new_stops, new_path_ids, nodes)
                    if new_key < cur_key:
                        is_better = True
            if is_better:
                dp_cost[j] = new_total
                dp_prev[j] = i if dp_prev[j] != i else (i if True else dp_prev[j])
                dp_prev[j] = i
                dp_stops[j] = new_stops

    dest_idx = n_nodes - 1
    if dp_cost[dest_idx] == INFINITY_COST:
        raise NoFeasiblePlanError(INFEASIBLE_PLAN_DETAIL)

    path: list[int] = []
    cur: int | None = dest_idx
    while cur is not None:
        path.append(cur)
        cur = dp_prev[cur]
    path.reverse()

    stops: list[FuelStopPlanEntry] = []
    total_gallons = Decimal('0')
    total_cost_d = Decimal('0')
    non_origin_stop_count = 0
    origin_station_info: StationInfo | None = None

    for k in range(len(path) - 1):
        i_nid = path[k]
        j_nid = path[k + 1]
        ni = nodes[i_nid]
        nj = nodes[j_nid]
        if ni.candidate is None or ni.retail_price is None:
            continue
        station_info = _build_station_info(ni.candidate)
        is_origin = ni.is_origin_catchment
        seg_miles = nj.route_mileage - ni.route_mileage
        seg_gallons = seg_miles / mpg_d
        seg_cost = seg_gallons * ni.retail_price
        entry = FuelStopPlanEntry(
            is_origin_catchment_entry=is_origin,
            station=station_info,
            route_mileage_at_departure=_q(ni.route_mileage, QUANT_MI),
            next_stop_route_mileage=_q(nj.route_mileage, QUANT_MI),
            segment_miles=_q(seg_miles, QUANT_MI),
            segment_gallons_consumed=_q(seg_gallons, QUANT_GAL),
            segment_cost=_q(seg_cost, QUANT_DOL),
            distance_from_route_poly_miles=_q(
                Decimal(str(ni.candidate.distance_from_route_poly_miles)),
                QUANT_MI,
            ),
        )
        stops.append(entry)
        total_gallons += seg_gallons
        total_cost_d += seg_cost
        if not is_origin:
            non_origin_stop_count += 1
        if is_origin:
            origin_station_info = station_info

    origin_radius_used = Decimal(
        str(
            origin_catchment_radius_miles_used
            if origin_catchment_radius_miles_used is not None
            else settings.ORIGIN_CATCHMENT_RADIUS_MILES
        )
    )

    return FuelOptimizerPlan(
        cost_model=COST_MODEL,
        stops=stops,
        total_gallons_consumed=_q(total_gallons, QUANT_GAL),
        total_cost=_q(total_cost_d, QUANT_DOL),
        total_stops=non_origin_stop_count,
        origin_fueled_at_stop_index=None,
        origin_catchment_radius_miles_used=_q(origin_radius_used, QUANT_MI),
        origin_catchment_station=origin_station_info,
    )
