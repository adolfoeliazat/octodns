#
#
#

from __future__ import absolute_import, division, print_function, \
    unicode_literals

from logging import getLogger
from nsone import NSONE
from nsone.rest.errors import ResourceException

from ..record import Record
from .base import BaseProvider


class Ns1Provider(BaseProvider):
    '''
    Ns1 provider

    nsone:
        class: octodns.provider.nsone.Ns1Provider
        api_key: env/NS1_API_KEY
    '''
    SUPPORTS_GEO = False
    ZONE_NOT_FOUND_MESSAGE = 'server error: zone not found'

    def __init__(self, id, api_key, *args, **kwargs):
        self.log = getLogger('Ns1Provider[{}]'.format(id))
        self.log.debug('__init__: id=%s, api_key=***', id)
        super(Ns1Provider, self).__init__(id, *args, **kwargs)
        self._client = NSONE(apiKey=api_key)

    def _data_for_A(self, _type, record):
        return {
            'ttl': record['ttl'],
            'type': _type,
            'values': record['short_answers'],
        }

    _data_for_AAAA = _data_for_A
    _data_for_SPF = _data_for_A
    _data_for_TXT = _data_for_A

    def _data_for_CNAME(self, _type, record):
        return {
            'ttl': record['ttl'],
            'type': _type,
            'value': record['short_answers'][0],
        }

    _data_for_PTR = _data_for_CNAME

    def _data_for_MX(self, _type, record):
        values = []
        for answer in record['short_answers']:
            priority, value = answer.split(' ', 1)
            values.append({
                'priority': priority,
                'value': value,
            })
        return {
            'ttl': record['ttl'],
            'type': _type,
            'values': values,
        }

    def _data_for_NAPTR(self, _type, record):
        values = []
        for answer in record['short_answers']:
            order, preference, flags, service, regexp, replacement = \
                answer.split(' ', 5)
            values.append({
                'flags': flags,
                'order': order,
                'preference': preference,
                'regexp': regexp,
                'replacement': replacement,
                'service': service,
            })
        return {
            'ttl': record['ttl'],
            'type': _type,
            'values': values,
        }

    def _data_for_NS(self, _type, record):
        return {
            'ttl': record['ttl'],
            'type': _type,
            'values': [a if a.endswith('.') else '{}.'.format(a)
                       for a in record['short_answers']],
        }

    def _data_for_SRV(self, _type, record):
        values = []
        for answer in record['short_answers']:
            priority, weight, port, target = answer.split(' ', 3)
            values.append({
                'priority': priority,
                'weight': weight,
                'port': port,
                'target': target,
            })
        return {
            'ttl': record['ttl'],
            'type': _type,
            'values': values,
        }

    def populate(self, zone, target=False):
        self.log.debug('populate: name=%s', zone.name)

        try:
            nsone_zone = self._client.loadZone(zone.name[:-1])
            records = nsone_zone.data['records']
        except ResourceException as e:
            if e.message != self.ZONE_NOT_FOUND_MESSAGE:
                raise
            records = []

        before = len(zone.records)
        for record in records:
            _type = record['type']
            data_for = getattr(self, '_data_for_{}'.format(_type))
            name = zone.hostname_from_fqdn(record['domain'])
            record = Record.new(zone, name, data_for(_type, record))
            zone.add_record(record)

        self.log.info('populate:   found %s records',
                      len(zone.records) - before)

    def _params_for_A(self, record):
        return {'answers': record.values, 'ttl': record.ttl}

    _params_for_AAAA = _params_for_A
    _params_for_NS = _params_for_A
    _params_for_SPF = _params_for_A
    _params_for_TXT = _params_for_A

    def _params_for_CNAME(self, record):
        return {'answers': [record.value], 'ttl': record.ttl}

    _params_for_PTR = _params_for_CNAME

    def _params_for_MX(self, record):
        values = [(v.priority, v.value) for v in record.values]
        return {'answers': values, 'ttl': record.ttl}

    def _params_for_NAPTR(self, record):
        values = [(v.order, v.preference, v.flags, v.service, v.regexp,
                   v.replacement) for v in record.values]
        return {'answers': values, 'ttl': record.ttl}

    def _params_for_SRV(self, record):
        values = [(v.priority, v.weight, v.port, v.target)
                  for v in record.values]
        return {'answers': values, 'ttl': record.ttl}

    def _get_name(self, record):
        return record.fqdn[:-1] if record.name == '' else record.name

    def _apply_Create(self, nsone_zone, change):
        new = change.new
        name = self._get_name(new)
        _type = new._type
        params = getattr(self, '_params_for_{}'.format(_type))(new)
        getattr(nsone_zone, 'add_{}'.format(_type))(name, **params)

    def _apply_Update(self, nsone_zone, change):
        existing = change.existing
        name = self._get_name(existing)
        _type = existing._type
        record = nsone_zone.loadRecord(name, _type)
        new = change.new
        params = getattr(self, '_params_for_{}'.format(_type))(new)
        record.update(**params)

    def _apply_Delete(self, nsone_zone, change):
        existing = change.existing
        name = self._get_name(existing)
        _type = existing._type
        record = nsone_zone.loadRecord(name, _type)
        record.delete()

    def _apply(self, plan):
        desired = plan.desired
        changes = plan.changes
        self.log.debug('_apply: zone=%s, len(changes)=%d', desired.name,
                       len(changes))

        domain_name = desired.name[:-1]
        try:
            nsone_zone = self._client.loadZone(domain_name)
        except ResourceException as e:
            if e.message != self.ZONE_NOT_FOUND_MESSAGE:
                raise
            self.log.debug('_apply:   no matching zone, creating')
            nsone_zone = self._client.createZone(domain_name)

        for change in changes:
            class_name = change.__class__.__name__
            getattr(self, '_apply_{}'.format(class_name))(nsone_zone, change)
