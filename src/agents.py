"""One coordinator and three bounded specialists.

Each agent acts only through its own scoped client: a tool outside the agent's
allowlist is refused in-process, before any HTTP request, so it can never become
a failed (penalized) enterprise call. Agents exchange typed handoff messages that
are recorded in the event trace; the Dealer Network specialist works from the
Supply Chain Planner's handoff, not from the coordinator's original order set.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from .client import ClientError, UnknownOutcomeError
from .policy import PolicyEngine

MOVE_TOOLS = ('mes.reschedule', 'mes.transfer')


class ScopeViolation(ClientError):
    """An agent attempted a tool outside its allowlist. Nothing was sent."""


class ScopedClient:
    """Client view for one agent: allowlisted tools pass through, others are refused."""

    def __init__(self, base, agent, allowed):
        self.base, self.agent, self.allowed = base, agent, frozenset(allowed)

    def act(self, event_id, tool, args):
        if tool not in self.allowed:
            raise ScopeViolation(f'{self.agent} is not permitted to call {tool}; '
                                 f'allowed: {sorted(self.allowed)}')
        return self.base.act(event_id, tool, args)

    def __getattr__(self, name):
        return getattr(self.base, name)


# ---- typed handoff messages -------------------------------------------------

@dataclass
class WorkOrder:
    """Coordinator -> Supply Chain Planner: builds that confirmed incidents block."""
    affected_production_orders: list
    release_dates: dict


@dataclass
class ProductionChanges:
    """Supply Chain Planner -> Dealer Network / Customer Care."""
    affected_production_orders: list
    moved: dict = field(default_factory=dict)
    unresolved: list = field(default_factory=list)


@dataclass
class CustomerCareReport:
    """Dealer Network / Customer Care -> Coordinator."""
    dealers_notified: list
    loaners_assigned: list
    loaner_shortfall: list


@dataclass
class QualityOrder:
    """Coordinator -> Quality: confirmed defective lots."""
    lot_ids: list


@dataclass
class QualityReport:
    """Quality -> Coordinator."""
    lots_held: list
    vehicles_stopped: int
    owners_contacted: int


# ---- agents -----------------------------------------------------------------

class _Agent:
    name = ''
    responsibility = ''
    allowed_tools = frozenset()

    def scoped(self, client):
        return ScopedClient(client, self.name, self.allowed_tools)

    def describe(self):
        return {'name': self.name, 'responsibility': self.responsibility,
                'allowed_tools': sorted(self.allowed_tools)}


class SupplyChainPlanner(_Agent):
    name = 'Supply Chain Planner'
    responsibility = 'Graph impact, production slots, compatible transfers, shared disruption constraints.'
    allowed_tools = frozenset({'mes.get_schedule', 'mes.reschedule', 'mes.transfer', 'escalate'})

    def execute(self, engine, order: WorkOrder) -> ProductionChanges:
        before = len(engine.trace['actions'])
        with engine.acting(self):
            PolicyEngine._move_orders(engine, set(order.affected_production_orders), order.release_dates)
        moved = {a['args']['production_order_id']: {'tool': a['tool'], 'date': a['args']['new_date'],
                                                     'plant_id': a['args'].get('to_plant_id')}
                 for a in engine.trace['actions'][before:] if a['tool'] in MOVE_TOOLS}
        report = ProductionChanges(sorted(order.affected_production_orders), moved,
                                   sorted(engine.trace['unresolved']))
        engine.steps.append({'agent': self.name, 'affected_orders': len(order.affected_production_orders),
                             'actions': len(engine.trace['actions']) - before,
                             'decision': 'Use earliest feasible same-plant slot; transfer only when none exists.'})
        return report


class DealerNetworkCustomerCare(_Agent):
    name = 'Dealer Network / Customer Care'
    responsibility = 'One notification per dealer, affected-order union, globally prioritized loaner allocation.'
    allowed_tools = frozenset({'crm.loaner_availability', 'dealer.notify', 'crm.assign_loaner'})

    def execute(self, engine, changes: ProductionChanges) -> CustomerCareReport:
        handled = set(changes.moved) | set(changes.unresolved)
        if handled != set(changes.affected_production_orders):
            raise ValueError('Planner handoff is inconsistent: every affected build must be moved or unresolved')
        before = len(engine.trace['actions'])
        with engine.acting(self):
            PolicyEngine._customer_care(engine, set(changes.affected_production_orders))
        done = engine.trace['actions'][before:]
        report = CustomerCareReport(
            sorted(a['args']['dealer_id'] for a in done if a['tool'] == 'dealer.notify'),
            sorted(a['args']['customer_order_id'] for a in done if a['tool'] == 'crm.assign_loaner'),
            sorted(engine.trace.get('loaner_shortfall', [])))
        engine.steps.append({'agent': self.name,
                             'affected_customer_orders': len(engine.graph.customer_orders_for(handled)),
                             'actions': len(done),
                             'decision': 'Union compound orders by dealer; allocate Platinum, Gold, date, order ID.'})
        return report


class Quality(_Agent):
    name = 'Quality'
    responsibility = 'Lot hold, graph-scoped vehicles, unsold stop sale, sold-owner notification.'
    allowed_tools = frozenset({'quality.hold_lot', 'dealer.stop_sale', 'crm.notify_customer'})

    def execute(self, engine, order: QualityOrder, incidents) -> QualityReport:
        before = len(engine.trace['actions'])
        with engine.acting(self):
            PolicyEngine._quality(engine, incidents)
        done = engine.trace['actions'][before:]
        report = QualityReport(
            sorted(a['args']['lot_id'] for a in done if a['tool'] == 'quality.hold_lot'),
            sum(len(a['args']['vins']) for a in done if a['tool'] == 'dealer.stop_sale'),
            sum(a['tool'] == 'crm.notify_customer' for a in done))
        if set(report.lots_held) != set(order.lot_ids):
            raise ValueError('Quality did not hold exactly the ordered lots')
        engine.steps.append({'agent': self.name, 'quality_incidents': len(incidents),
                             'actions': len(done),
                             'decision': 'Validate lot, BOM, plant and window; split unsold vehicles from sold owners.'})
        return report


class _SpecialistPolicy(PolicyEngine):
    """Handbook engine whose three action phases are delegated to specialists."""

    def __init__(self, graph, client, coordinator, planner, care, quality):
        self.base_client = client
        super().__init__(graph, coordinator.scoped(client))
        self.coordinator, self.planner, self.care, self.quality = coordinator, planner, care, quality
        self.active_agent = coordinator.name
        self.steps, self.handoffs = [], []
        self.production_changes = None
        self.failed_agent = None

    @contextmanager
    def acting(self, agent):
        previous = self.client, self.active_agent
        self.client, self.active_agent = agent.scoped(self.base_client), agent.name
        try:
            yield
        except BaseException:
            self.failed_agent = self.failed_agent or agent.name
            raise
        finally:
            self.client, self.active_agent = previous

    def _call(self, tool, args, reason):
        result = super()._call(tool, args, reason)
        self.trace['calls'][-1]['role'] = self.active_agent
        return result

    def _handoff(self, sender, receiver, message):
        self.handoffs.append({'from': sender, 'to': receiver, 'type': type(message).__name__,
                              'payload': asdict(message)})
        return message

    def _move_orders(self, affected, release):
        if not affected:
            self.production_changes = ProductionChanges([])
            return
        order = self._handoff(self.coordinator.name, self.planner.name,
                              WorkOrder(sorted(affected), {po: release[po] for po in sorted(affected)}))
        self.production_changes = self._handoff(self.planner.name, self.care.name,
                                                self.planner.execute(self, order))

    def _customer_care(self, affected):
        if not affected:
            return
        changes = self.production_changes
        if changes is None or set(changes.affected_production_orders) != set(affected):
            raise ValueError('Customer care requires the planner handoff for exactly the affected builds')
        self._handoff(self.care.name, self.coordinator.name, self.care.execute(self, changes))

    def _quality(self, incidents):
        if not incidents:
            return
        order = self._handoff(self.coordinator.name, self.quality.name,
                              QualityOrder(sorted({i['lot_id'] for i in incidents})))
        self._handoff(self.quality.name, self.coordinator.name, self.quality.execute(self, order, incidents))


class Coordinator(_Agent):
    name = 'Coordinator'
    responsibility = 'Validate grounded extraction, classify noise/rumor/incident, escalate, dispatch specialists.'
    allowed_tools = frozenset({'escalate'})

    def __init__(self, graph, client):
        self.graph, self.client = graph, client
        self.planner = SupplyChainPlanner()
        self.care = DealerNetworkCustomerCare()
        self.quality = Quality()

    def handle(self, event, parsed):
        if parsed.get('event_id') != event.get('event_id'):
            raise ValueError('Extraction event ID does not match source event')
        engine = _SpecialistPolicy(self.graph, self.client, self, self.planner, self.care, self.quality)
        try:
            trace = engine.handle(event['event_id'], parsed.get('incidents'))
        except ClientError as exc:
            trace = engine.trace
            trace['status'] = 'halted'
            trace['error'] = {'type': type(exc).__name__, 'message': str(exc),
                              'unknown_outcome': isinstance(exc, UnknownOutcomeError),
                              'scope_violation': isinstance(exc, ScopeViolation),
                              'agent': engine.failed_agent or engine.active_agent}
            trace['recovery'] = ('Refused in-process before any HTTP request; fix the agent boundary.'
                                 if isinstance(exc, ScopeViolation) else
                                 'Inspect authoritative server log. Do not retry a write with unknown outcome.')
        trace['event'] = event
        trace['extraction'] = parsed.get('provenance', {})
        dispatched = [step['agent'] for step in engine.steps]
        trace['agent_steps'] = [{'agent': self.name, 'dispatched': dispatched, 'decision':
                                 'Validate grounded extraction; combine confirmed incidents within one event world; '
                                 + ('dispatch ' + ', '.join(dispatched) + '.' if dispatched else
                                    'no specialist has work (noise, rumor or escalation only).')},
                                *engine.steps]
        trace['handoffs'] = engine.handoffs
        trace['architecture'] = {'coordinator': self.name, 'coordinator_allowed_tools': sorted(self.allowed_tools),
                                 'specialists': [s.describe() for s in (self.planner, self.care, self.quality)]}
        return trace
