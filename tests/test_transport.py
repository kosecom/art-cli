"""Synthetic transport regression coverage. Native acceptance is separate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from art_cli.api import dispatch
from art_cli.config import Store
from art_cli.rpc import Session,ACTIVE_SESSIONS

ROOT=Path(__file__).resolve().parents[1]
FAKE=[sys.executable,str(Path(__file__).with_name('fake_native.py'))]

class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.a=patch.object(Store,'command',return_value=FAKE);self.a.start()
        self.b=patch.object(Store,'identity',return_value={'fixture':True});self.b.start()
    def tearDown(self):self.b.stop();self.a.stop();self.tmp.cleanup()
    def run_steps(self,steps):return dispatch('batch',{'steps':steps},home=self.home)
    def step(self,tool,value=1):return {'app':'figcraft','tool':tool,'arguments':{'value':value}}
    def test_batch_reuses_process_and_then_closes(self):
        result=self.run_steps([self.step('echo',1),self.step('echo',2)])
        self.assertTrue(result['ok']);self.assertEqual(len(result['steps']),2)
        vals=[json.loads(x['result']['content'][0]['text']) for x in result['steps']]
        self.assertEqual(vals[0]['pid'],vals[1]['pid']);self.assertFalse(ACTIVE_SESSIONS)
    def test_native_error_stops_and_preserves(self):
        result=self.run_steps([self.step('echo'),self.step('fail'),self.step('echo')])
        self.assertFalse(result['ok']);self.assertEqual(len(result['steps']),2)
        self.assertTrue(result['steps'][1]['result']['isError'])
    def test_rpc_error_is_not_hidden(self):
        result=self.run_steps([self.step('rpcfail')]);self.assertEqual(result['error']['code'],-32042)
        self.assertEqual(result['error']['data'],{'source':'fixture'})
    def test_schema_hash_drift_refuses_before_dispatch(self):
        step=self.step('echo');step['schema_hash']='not-current'
        result=self.run_steps([step]);self.assertFalse(result['ok']);self.assertEqual(result['steps'],[])
        self.assertEqual(result['completion'],'not_dispatched')
    def test_unknown_second_step_prevents_first_mutation(self):
        result=self.run_steps([self.step('echo'),self.step('missing')]);self.assertFalse(result['ok']);self.assertEqual(result['steps'],[])
    def test_images_are_unchanged(self):
        result=self.run_steps([self.step('image')]);block=result['steps'][0]['result']['content'][0]
        self.assertEqual(block,{'type':'image','mimeType':'image/png','data':'SYNTHETIC_NOT_A_REAL_IMAGE'})
    def test_approval_callback_never_granted(self):
        result=self.run_steps([self.step('callback')]);reply=json.loads(result['steps'][0]['result']['content'][0]['text'])
        self.assertEqual(reply['error']['code'],-32601);self.assertNotIn('result',reply)
    def test_timeout_closes_owned_process(self):
        start=time.monotonic();result=dispatch('execute',{'app':'figcraft','tool':'slow','timeout':1},home=self.home)
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],-32012)
        self.assertLess(time.monotonic()-start,6);self.assertFalse(ACTIVE_SESSIONS)
    def test_result_binding(self):
        result=self.run_steps([self.step('echo',{'id':42}),self.step('echo',{'$art_ref':'0:/value/id'})])
        self.assertTrue(result['ok']);self.assertEqual(json.loads(result['steps'][1]['result']['content'][0]['text'])['value'],42)
    def test_invalid_forward_reference_cannot_dispatch(self):
        result=self.run_steps([self.step('echo',{'$art_ref':'1:/value'})]);self.assertFalse(result['ok']);self.assertEqual(result['steps'],[])

class WorkerTests(unittest.TestCase):
    def test_remote_worker_actual_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            command=[sys.executable,'-m','art_cli','--home',tmp,'worker']
            with Session('worker',command,5) as session:
                tools=session.collect('tools/list','tools');self.assertEqual(len(tools),1)
                result=session.rpc('art/dispatch',{'operation':'catalog','arguments':{}})
                self.assertTrue(result['ok']);self.assertEqual(result['count'],13)
                self.assertFalse(result['worker_started'])
            self.assertIsNotNone(session.child.process.poll())

if __name__=='__main__':unittest.main()
