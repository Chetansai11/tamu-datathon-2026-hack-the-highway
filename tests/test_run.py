"""Reject altered or incomplete cached extraction before any server is started."""
import hashlib
import json
import unittest
from scripts.run import validate_cached_record
from src.parse import normalize_incidents


class CacheIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.event = {'event_id': 'SYNTHETIC', 'text': 'Where is the brochure?'}
        raw = {'incidents': [{'kind': 'noise', 'confirmed': True, 'reason': 'Brochure request.'}]}
        self.record = {'event_id': 'SYNTHETIC',
                       'text_sha256': hashlib.sha256(self.event['text'].encode()).hexdigest(),
                       'incidents': normalize_incidents(raw, self.event['text'], None),
                       'provenance': {'provider': 'gemini', 'finish_reason': 'STOP',
                                      'raw_output': json.dumps(raw), 'warnings': []}}

    def test_valid_actual_output_can_be_replayed(self):
        validate_cached_record(self.record, self.event, None)

    def test_modified_incidents_cannot_override_raw_model(self):
        self.record['incidents'][0]['kind'] = 'plant_outage'
        with self.assertRaisesRegex(ValueError, 'differ'):
            validate_cached_record(self.record, self.event, None)

    def test_incomplete_model_output_cannot_be_replayed(self):
        self.record['provenance']['finish_reason'] = 'MAX_TOKENS'
        with self.assertRaisesRegex(ValueError, 'complete normally'):
            validate_cached_record(self.record, self.event, None)

    def test_changed_source_invalidates_cached_extraction(self):
        self.event['text'] = 'Production stopped today.'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            validate_cached_record(self.record, self.event, None)
