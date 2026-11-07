"""Deterministic handbook execution. No event-ID branches or LLM-written actions."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

TODAY = date(2027, 3, 8)
LAST_DAY = date(2027, 4, 2)
READS = {'mes.get_schedule', 'crm.loaner_availability'}
ROLES = {
    'mes.get_schedule': 'Supply Chain Planner', 'mes.reschedule': 'Supply Chain Planner',
    'mes.transfer': 'Supply Chain Planner', 'dealer.notify': 'Dealer Network / Customer Care',
    'crm.loaner_availability': 'Dealer Network / Customer Care',
    'crm.assign_loaner': 'Dealer Network / Customer Care',
    'quality.hold_lot': 'Quality', 'dealer.stop_sale': 'Quality',
    'crm.notify_customer': 'Quality', 'escalate': 'Coordinator',
}


def working_days(start=TODAY, end=LAST_DAY):
    current = max(date.fromisoformat(start) if isinstance(start, str) else start, TODAY)
    while current <= end:
        if current.weekday() < 5:
            yield current.isoformat()
        current += timedelta(days=1)


class PolicyEngine:
    def __init__(self, graph, client):
        self.graph, self.client = graph, client
        self.index = graph.indexes

    def _call(self, tool, args, reason):
        result = self.client.act(self.event_id, tool, args)
        record = {'tool': tool, 'args': args, 'result': result,
                  'role': ROLES[tool], 'reason': reason, 'ok': True}
        self.trace['calls'].append(record)
        if tool not in READS:
            self.trace['actions'].append(record)
        return result

    def _validate(self, incident):
        kind = incident['kind']
        if kind in ('noise', 'unconfirmed') or incident.get('confirmed') is not True:
            return
        if kind == 'supplier_delay':
            shipment = self.index['inbound_shipments'][incident['shipment_id']]
            eta = date.fromisoformat(incident['new_eta'])
            if eta <= date.fromisoformat(shipment['eta_date']):
                raise ValueError('New ETA must follow the shipment original ETA')
            for field in ('plant_id', 'part_id', 'supplier_id'):
                if incident.get(field) and incident[field] != shipment[field]:
                    raise ValueError(f'Shipment contradicts {field}')
        elif kind == 'plant_outage':
            self.index['plants'][incident['plant_id']]
            start = date.fromisoformat(incident['start_date'])
            end = date.fromisoformat(incident['end_date'])
            if end < start:
                raise ValueError('Outage end precedes start')
        elif kind == 'quality_hold':
            lot = self.index['part_lots'][incident['lot_id']]
            for field in ('plant_id', 'part_id', 'supplier_id'):
                if incident.get(field) and incident[field] != lot[field]:
                    raise ValueError(f'Lot contradicts {field}')
        else:
            raise ValueError(f'Unsupported incident kind {kind!r}')

    def _blocked(self, plant_id, model, day):
        for incident in self.real:
            if incident['kind'] == 'plant_outage':
                if (plant_id == incident['plant_id'] and
                        incident['start_date'] <= day <= incident['end_date']):
                    return True
            elif incident['kind'] == 'supplier_delay':
                shipment = self.index['inbound_shipments'][incident['shipment_id']]
                if (plant_id == shipment['plant_id'] and
                        shipment['part_id'] in self.graph.parts_by_model[model] and
                        shipment['eta_date'] <= day < incident['new_eta']):
                    return True
        return False

    def _slot(self, plant_id, model, start):
        for day in working_days(start):
            if self._blocked(plant_id, model, day):
                continue
            key = (plant_id, day)
            # A full day stays full until one of our own moves frees it. A free
            # candidate is always read live immediately before the write.
            if self.full_days.get(key):
                continue
            schedule = self._call('mes.get_schedule', {'plant_id': plant_id, 'date': day},
                                  'Read live destination capacity before a possible move (rule 3).')
            if schedule['free_slots'] > 0:
                return day, schedule['free_slots']
            self.full_days[key] = True
        return None

    def _move_orders(self, affected, release):
        orders = self.index['production_orders']
        for po in sorted(affected, key=lambda p: (orders[p]['build_date'], p)):
            order = orders[po]
            plant, model = order['plant_id'], order['model']
            candidate = self._slot(plant, model, release[po])
            destination = plant
            if candidate is None:
                alternatives = sorted(row['plant_id'] for row in self.graph.tables['plant_models']
                                      if row['model'] == model and row['plant_id'] != plant)
                # Transfers may use ANY working day under rule 3. Search date
                # first, plant ID second, after exhausting the original plant.
                for day in working_days():
                    for other in alternatives:
                        if self._blocked(other, model, day) or self.full_days.get((other, day)):
                            continue
                        schedule = self._call('mes.get_schedule', {'plant_id': other, 'date': day},
                                              'Original plant has no feasible slot; verify compatible transfer capacity.')
                        if schedule['free_slots'] > 0:
                            candidate, destination = (day, schedule['free_slots']), other
                            break
                        self.full_days[(other, day)] = True
                    if candidate:
                        break
            if candidate is None:
                self._call('escalate', {'reason': f'No feasible planning-window slot for {po}.'},
                           'No valid move exists; do not manufacture a failed write.')
                self.trace['unresolved'].append(po)
                continue
            day, available = candidate
            args = {'production_order_id': po, 'new_date': day}
            tool = 'mes.reschedule'
            if destination != plant:
                tool = 'mes.transfer'
                args['to_plant_id'] = destination
            self._call(tool, args,
                       f'{po} is affected by confirmed incident(s); earliest feasible '
                       f'{"same-plant" if destination == plant else "compatible transfer"} slot is {destination} {day}.')
            self.full_days.pop((plant, order['build_date']), None)
            if available == 1:
                self.full_days[(destination, day)] = True

    def _customer_care(self, affected):
        by_dealer = defaultdict(list)
        for co in self.graph.customer_orders_for(affected):
            by_dealer[self.index['customer_orders'][co]['dealer_id']].append(co)
        for dealer, ids in sorted(by_dealer.items()):
            # Read the dealer's live resource state; static graph membership
            # proves the notification contains only this dealer's affected IDs.
            self._call('crm.loaner_availability', {'dealer_id': dealer},
                       'Read dealer state before customer-care writes.')
            self._call('dealer.notify', {'dealer_id': dealer, 'customer_order_ids': sorted(ids),
                       'message': 'Confirmed disruption affects these orders: ' + ', '.join(sorted(ids)) +
                       '. Production changes follow the earliest feasible slot policy.'},
                       'Exactly one notification per affected dealer for the whole event (rule 4).')
            eligible = []
            for co in ids:
                row = self.index['customer_orders'][co]
                tier = self.index['customers'][row['customer_id']]['tier']
                if tier in ('Platinum', 'Gold'):
                    eligible.append((0 if tier == 'Platinum' else 1, row['promised_date'], co))
            for _, _, co in sorted(eligible):
                pool = self._call('crm.loaner_availability', {'dealer_id': dealer},
                                  'Read remaining pool immediately before assignment (rule 5).')
                if pool['available'] <= 0:
                    break
                self._call('crm.assign_loaner', {'customer_order_id': co},
                           'Affected entitled order selected by tier, promised date, then order ID.')

    def _quality(self, incidents):
        affected_vins, lot_ids = set(), set()
        for incident in incidents:
            lot_ids.add(incident['lot_id'])
            affected_vins.update(self.graph.affected_quality(incident['lot_id']))
        for lot in sorted(lot_ids):
            self._call('quality.hold_lot', {'lot_id': lot},
                       'Read and validate named lot in graph; confirmed quality defect (rule 6).')
        unsold, sold = defaultdict(list), defaultdict(list)
        for vin in sorted(affected_vins):
            vehicle = self.index['finished_vehicles'][vin]
            if vehicle['status'] == 'in_stock':
                unsold[vehicle['dealer_id']].append(vin)
            elif vehicle['status'] == 'sold':
                sold[vehicle['customer_id']].append(vin)
        for dealer, vins in sorted(unsold.items()):
            self._call('dealer.stop_sale', {'dealer_id': dealer, 'vins': vins},
                       'Graph reads verify lot window, BOM, plant, unsold status and dealer ownership.')
        for customer, vins in sorted(sold.items()):
            self._call('crm.notify_customer', {'customer_id': customer,
                       'message': 'Confirmed quality hold affects your vehicle(s): ' + ', '.join(vins) +
                       '. Please contact your dealer for guidance.'},
                       'Graph reads verify sold status and owner; notify each affected owner once.')

    def handle(self, event_id, incidents):
        self.event_id = event_id
        self.trace = {'event_id': event_id, 'incidents': [], 'actions': [], 'calls': [],
                      'unresolved': [], 'status': 'complete', 'policy_version': 'handbook-1-10'}
        self.full_days = {}
        if not isinstance(incidents, list) or not incidents:
            incidents = [{'kind': 'unconfirmed', 'confirmed': False, 'reason': 'No structured incident.'}]
        try:
            for incident in incidents:
                self._validate(incident)
        except (KeyError, ValueError, TypeError) as exc:
            self._call('escalate', {'reason': f'Incident validation failed: {exc}'},
                       'Missing, contradictory or invalid data: no operational writes (rule 8).')
            self.trace['status'] = 'escalated'
            self.trace['validation_error'] = str(exc)
            return self.trace
        self.real = [i for i in incidents if i.get('confirmed') is True and
                     i['kind'] not in ('noise', 'unconfirmed')]
        unclear = [i for i in incidents if i['kind'] == 'unconfirmed' or i.get('confirmed') is not True]
        if unclear:
            self._call('escalate', {'reason': '; '.join(i.get('reason', 'Unconfirmed operational report') for i in unclear)},
                       'Report lacks confirmation or specificity; no operational action for these incidents (rule 8).')
        affected, release = set(), {}
        for incident in incidents:
            detail = {**incident, 'affected_production_orders': [], 'affected_vehicles': [], 'graph_paths': []}
            kind = incident['kind']
            if incident not in self.real:
                detail['reason'] = incident.get('reason', 'No confirmed operational disruption; no write justified.')
            elif kind == 'supplier_delay':
                ids = self.graph.affected_delay(incident['shipment_id'], incident['new_eta'])
                detail['affected_production_orders'] = ids
                detail['graph_paths'] = self.graph.paths_for_delay(incident['shipment_id'], ids)
                detail['reason'] = 'BOM-dependent orders at receiving plant in [original ETA, new ETA).'
                end = incident['new_eta']
            elif kind == 'plant_outage':
                ids = self.graph.affected_outage(incident['plant_id'], incident['start_date'], incident['end_date'])
                detail['affected_production_orders'] = ids
                detail['graph_paths'] = self.graph.paths_for_outage(incident['plant_id'], ids)
                detail['reason'] = 'All orders at outage plant during inclusive date interval.'
                end = (date.fromisoformat(incident['end_date']) + timedelta(days=1)).isoformat()
            elif kind == 'quality_hold':
                detail['affected_vehicles'] = self.graph.affected_quality(incident['lot_id'])
                detail['graph_paths'] = self.graph.paths_for_quality(incident['lot_id'])
                detail['reason'] = 'Lot -> BOM/window/plant-scoped orders -> vehicles -> dealer or owner.'
            if detail['affected_production_orders']:
                for po in detail['affected_production_orders']:
                    affected.add(po)
                    release[po] = max(release.get(po, TODAY.isoformat()), end)
            self.trace['incidents'].append(detail)
        self._move_orders(affected, release)
        self._customer_care(affected)
        self._quality([i for i in self.real if i['kind'] == 'quality_hold'])
        for detail in self.trace['incidents']:
            po_set = set(detail['affected_production_orders'])
            co_set = set(self.graph.customer_orders_for(po_set))
            vins = set(detail['affected_vehicles'])
            owners = {self.index['finished_vehicles'][v]['customer_id'] for v in vins
                      if self.index['finished_vehicles'][v]['status'] == 'sold'}
            kinds = set()
            for action in self.trace['actions']:
                args = action['args']
                if (args.get('production_order_id') in po_set or args.get('customer_order_id') in co_set or
                        co_set.intersection(args.get('customer_order_ids', [])) or
                        args.get('lot_id') == detail.get('lot_id') and 'lot_id' in args or
                        vins.intersection(args.get('vins', [])) or args.get('customer_id') in owners):
                    kinds.add(action['tool'])
            detail['action_kinds'] = sorted(kinds)
            detail['completeness'] = len(kinds) >= 3 if detail in self.real else None
            if detail.get('confirmed') and detail['kind'] not in ('noise', 'unconfirmed'):
                detail['completeness'] = len(kinds) >= 3
                if len(kinds) < 3:
                    detail['completeness_note'] = 'Fewer than three valid kinds available; rule 10 forbids invented writes.'
        self.trace['affected_production_orders'] = sorted(affected)
        self.trace['write_count'] = sum(a['tool'] != 'escalate' for a in self.trace['actions'])
        self.trace['read_count'] = sum(a['tool'] in READS for a in self.trace['calls'])
        if self.trace['unresolved']:
            self.trace['status'] = 'needs_review'
        elif unclear and not self.real:
            self.trace['status'] = 'escalated'
        elif not self.real:
            self.trace['status'] = 'no_action'
        return self.trace
