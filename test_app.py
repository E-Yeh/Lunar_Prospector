# GENERATED FROM MoonScout.ipynb. Edit the notebook, not this file.
# MoonScout.ipynb cell 17
# export: test_app.py
"""Tests use publisher data or a network failure, never generated measurements."""
import unittest
from unittest.mock import patch
from core import DEFAULT, plan_query
from rasters import load_sources
from streamlit.testing.v1 import AppTest



# MoonScout.ipynb cell 18
# export: test_app.py
class AutomaticSourceTests(unittest.TestCase):
    def test_followup(self):
        p=plan_query('top 5',plan_query('highest TiO2',DEFAULT))
        self.assertEqual(p['top_n'],5)
        self.assertEqual(p['priority'],'tio2')
    def test_sources_and_cache(self):
        data,provenance=load_sources()
        self.assertGreater(len(data),100)
        self.assertTrue(data.tio2.between(0,15).all())
        self.assertEqual(len([p for p in provenance if 'sha256' in p]),9)
        again,_=load_sources()
        self.assertTrue(data.equals(again))
    def test_automatic_app(self):
        at=AppTest.from_file(str(__import__('pathlib').Path(__file__).with_name('app.py')),default_timeout=120).run()
        self.assertFalse(at.exception)
        self.assertIsNotNone(at.session_state['data'])
        self.assertEqual(at.sidebar.radio[0].options,['Explore','Methods & project'])
        self.assertEqual(len(at.get('file_uploader')),0)
        at.text_area[0].set_value('highest TiO2')
        [b for b in at.button if b.label=='Find candidates'][0].click()
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['plan']['priority'],'tio2')
        at.sidebar.radio[0].set_value('Methods & project').run()
        self.assertFalse(at.exception)
    def test_source_failure_has_no_fallback(self):
        with patch('rasters.load_sources',side_effect=ConnectionError('Source unavailable')):
            at=AppTest.from_file(str(__import__('pathlib').Path(__file__).with_name('app.py')),default_timeout=120).run()
        self.assertFalse(at.exception)
        self.assertIsNone(at.session_state['data'])
        self.assertEqual(len(at.dataframe),0)
        self.assertTrue(any('could not be loaded' in e.value for e in at.error))
        self.assertTrue(any(b.label=='Retry source loading' for b in at.button))



# MoonScout.ipynb cell 19
# export: test_app.py
if __name__=='__main__': unittest.main()

