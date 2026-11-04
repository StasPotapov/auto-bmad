import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_schedule as schedule


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.data = {'plan': {'parallel': 'conservative', 'parallel_width': 3},
                     'schedule_required': True,
                     'stories': {s: {'status': 'pending', 'agents': {}} for s in ('1-1', '1-2', '1-3', '1-4')}}
        self.request = {'host_limit': 4, 'waves': [
            {'stories': ['1-1', '1-2', '1-3'], 'reason': 'Distinct modules; no shared entities.'},
            {'stories': ['1-4'], 'reason': 'Consumes contracts from 1-1 and 1-3.'}]}

    def start(self, story, identity, role):
        schedule.agent(self.data, story, identity, role, 'running')
        self.data['stories'][story]['agents'][identity] = {'role': role, 'status': 'running'}

    def test_three_parallel_roles_fit_four_slot_host_without_controllers(self):
        self.data['schedule'] = schedule.prepare(self.data, self.request)
        self.assertEqual(self.data['schedule']['capacity'], 3)
        for s in ('1-1', '1-2', '1-3'):
            self.start(s, 'plan-' + s, 'story-runner')
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.start('1-1', 'worker', 'implementer')
        for s in ('1-1', '1-2', '1-3'):
            self.data['stories'][s]['agents']['plan-' + s]['status'] = 'completed'
            self.start(s, 'dev-' + s, 'implementer')
        self.assertEqual(sum(a['status'] == 'running' for r in self.data['stories'].values()
                             for a in r['agents'].values()), 3)

    def test_dependency_barrier_and_missing_schedule(self):
        with self.assertRaisesRegex(ValueError, 'schedule'):
            schedule.admission(self.data, '1-1')
        self.data['schedule'] = schedule.prepare(self.data, self.request)
        with self.assertRaisesRegex(ValueError, 'previous wave'):
            schedule.admission(self.data, '1-4')
        for s in ('1-1', '1-2', '1-3'):
            self.data['stories'][s]['status'] = 'verified'
        with self.assertRaises(ValueError):
            schedule.admission(self.data, '1-4')
        for s in ('1-1', '1-2', '1-3'):
            self.data['stories'][s]['status'] = 'completed'
        schedule.admission(self.data, '1-4')

    def test_no_silent_reordering_reduction_or_oversubscription(self):
        for mutation in ('order', 'missing', 'width', 'reason', 'slots', 'disabled'):
            with self.subTest(mutation=mutation):
                req, data = copy.deepcopy(self.request), copy.deepcopy(self.data)
                if mutation == 'order': req['waves'][0]['stories'].reverse()
                if mutation == 'missing': req['waves'].pop()
                if mutation == 'width': data['plan']['parallel_width'] = 2
                if mutation == 'reason': req['waves'][1]['reason'] = ''
                if mutation == 'slots': req['host_limit'] = 3
                if mutation == 'disabled': data['plan']['parallel'] = 'off'
                with self.assertRaises(ValueError): schedule.prepare(data, req)

    def test_waiting_controllers_and_writers_do_not_overlap_own_roles(self):
        self.data['schedule'] = schedule.prepare(self.data, self.request)
        self.start('1-1', 'controller', 'story-runner')
        self.data['stories']['1-1']['agents']['controller']['status'] = 'waiting'
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            self.start('1-1', 'worker', 'implementer')
        self.data['stories']['1-1']['agents']['controller']['status'] = 'completed'
        self.start('1-1', 'worker', 'implementer')
        with self.assertRaisesRegex(ValueError, 'implementer'):
            self.start('1-1', 'reviewer', 'blind-hunter')
        with self.assertRaisesRegex(ValueError, 'exactly one story'):
            self.start('1-2', 'worker', 'implementer')
        with self.assertRaisesRegex(ValueError, 'before starting'):
            schedule.prepare(self.data, self.request)

    def test_legacy_journal_does_not_acquire_new_requirements(self):
        self.data.pop('schedule_required')
        schedule.admission(self.data, '1-1')
        schedule.agent(self.data, '1-1', 'legacy', 'story-runner', 'running')


if __name__ == '__main__': unittest.main()
