import copy
import unittest
from qnaplibrary.research_selection import snapshot,select
from qnaplibrary.store import StoreError


class SelectionTests(unittest.TestCase):
    def record(self,n=1,**values):
        return dict(dict(publication='EP%07dA1'%n,language='en',family=None,title='Example',sources=['epo'],cells=['inverter']),**values)
    def test_dedup_is_order_independent_without_collapsing_family_versions(self):
        rows=[self.record(),self.record(title='Other title',sources=['ops']),self.record(2,family='docdb:1')]
        a=snapshot(rows);b=snapshot(list(reversed(rows)))
        self.assertEqual(a,b);self.assertEqual(a['unique_publications'],2)
        self.assertEqual(a['items'][0]['sources'],['epo','ops'])
        bad=copy.deepcopy(rows);bad[0]['family']='x';bad[1]['family']='y'
        with self.assertRaises(StoreError):snapshot(bad)
    def test_cross_classification_masks_and_pins_are_reversible(self):
        s=snapshot([self.record(cells=['inverter','semiconductor']),self.record(2,cells=[])]);rev=s['revision']
        first=s['items'][0]['id']
        p=select(s,rev,['inverter'],[first],[],1)
        self.assertEqual(p['visible_count'],2);self.assertTrue(p['count_budget_ok'])
        p=select(s,rev,['inverter','semiconductor'],[first],[],1)
        self.assertEqual(p['conflicts'],[first]);self.assertFalse(p['count_budget_ok'])
        self.assertEqual(select(s,rev,[],[first],[],1)['hidden'],[])
        self.assertIn('unclassified',p['cells']);self.assertFalse(p['download_ready'])
    def test_budget_uses_publications_not_families_and_never_trims(self):
        s=snapshot([self.record(1,family='same'),self.record(2,family='same')]);ids=[r['id'] for r in s['items']]
        p=select(s,s['revision'],[],[],ids,1)
        self.assertEqual(p['selected_count'],2);self.assertEqual(p['selected_families'],1)
        self.assertIn('count_limit_exceeded',p['blocking_reasons'])
        self.assertEqual(p['selected'],ids)
        with self.assertRaises(StoreError):select(s,'old',[],[],ids)
        with self.assertRaises(StoreError):select(s,s['revision'],[],[],['missing'])
        with self.assertRaises(StoreError):select(s,s['revision'],[],[],ids,True)
