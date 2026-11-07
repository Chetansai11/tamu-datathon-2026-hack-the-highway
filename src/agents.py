"""One coordinator and three bounded specialists sharing an event-local policy engine."""
from __future__ import annotations

from .client import ClientError, UnknownOutcomeError
from .policy import PolicyEngine


class SupplyChainPlanner:
    name = 'Supply Chain Planner'
    responsibility = 'Graph impact, production slots, compatible transfers, shared disruption constraints.'

    def execute(self, engine, affected, release):
        before = len(engine.trace['actions'])
        PolicyEngine._move_orders(engine, affected, release)
        engine.steps.append({'agent': self.name, 'affected_orders': len(affected),
                             'actions': len(engine.trace['actions']) - before,
                             'decision': 'Use earliest feasible same-plant slot; transfer only when none exists.'})


class DealerNetworkCustomerCare:
    name = 'Dealer Network / Customer Care'
    responsibility = 'One notification per dealer, affected-order union, globally prioritized loaner allocation.'

    def execute(self, engine, affected):
        before = len(engine.trace['actions'])
        PolicyEngine._customer_care(engine, affected)
        engine.steps.append({'agent': self.name, 'affected_customer_orders': len(engine.graph.customer_orders_for(affected)),
                             'actions': len(engine.trace['actions']) - before,
                             'decision': 'Union compound orders by dealer; allocate Platinum, Gold, date, order ID.'})


class Quality:
    name = 'Quality'
    responsibility = 'Lot hold, graph-scoped vehicles, unsold stop sale, sold-owner notification.'

    def execute(self, engine, incidents):
        before = len(engine.trace['actions'])
        PolicyEngine._quality(engine, incidents)
        engine.steps.append({'agent': self.name, 'quality_incidents': len(incidents),
                             'actions': len(engine.trace['actions']) - before,
                             'decision': 'Validate lot, BOM, plant and window; split unsold vehicles from sold owners.'})


class _SpecialistPolicy(PolicyEngine):
    def __init__(self, graph, client, planner, care, quality):
        super().__init__(graph, client)
        self.planner, self.care, self.quality = planner, care, quality
        self.steps = []

    def _move_orders(self, affected, release):
        return self.planner.execute(self, affected, release)

    def _customer_care(self, affected):
        return self.care.execute(self, affected)

    def _quality(self, incidents):
        return self.quality.execute(self, incidents)


class Coordinator:
    name = 'Coordinator'

    def __init__(self, graph, client):
        self.graph, self.client = graph, client
        self.planner = SupplyChainPlanner()
        self.care = DealerNetworkCustomerCare()
        self.quality = Quality()

    def handle(self, event, parsed):
        if parsed.get('event_id') != event.get('event_id'):
            raise ValueError('Extraction event ID does not match source event')
        engine = _SpecialistPolicy(self.graph, self.client, self.planner, self.care, self.quality)
        try:
            trace = engine.handle(event['event_id'], parsed.get('incidents'))
        except ClientError as exc:
            trace = engine.trace
            trace['status'] = 'halted'
            trace['error'] = {'type': type(exc).__name__, 'message': str(exc),
                              'unknown_outcome': isinstance(exc, UnknownOutcomeError)}
            trace['recovery'] = 'Inspect authoritative server log. Do not retry a write with unknown outcome.'
        trace['event'] = event
        trace['extraction'] = parsed.get('provenance', {})
        trace['agent_steps'] = [{'agent': self.name, 'decision':
                                'Validate grounded extraction; combine confirmed incidents within one event world; dispatch bounded specialists.'},
                               *engine.steps]
        trace['architecture'] = {'coordinator': self.name, 'specialists': [
            {'name': specialist.name, 'responsibility': specialist.responsibility}
            for specialist in (self.planner, self.care, self.quality)]}
        return trace
