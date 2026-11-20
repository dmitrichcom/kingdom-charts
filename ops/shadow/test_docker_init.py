"""A portable Docker init setting is declared as a typed Pod annotation."""
import tempfile
from pathlib import Path
import unittest
from compile import BundleError, compile_bundle
from test_compile import sample_deployment, sample_manifest, DIGEST

class DockerInitTests(unittest.TestCase):
    def make(self,value):
        d=sample_deployment()
        d['spec']['template']['metadata']['annotations']['kingdom.dmitrich.com/docker-init']=value
        with tempfile.TemporaryDirectory() as td:
            return compile_bundle(manifests=[d],generated={'services':{'gateway':{'image':DIGEST}}},
                                  descriptor=sample_manifest(),output=Path(td))['services']['gateway']
    def test_enabled_from_annotation(self):
        self.assertIs(self.make('true')['init'],True)
    def test_disabled_from_annotation(self):
        self.assertIs(self.make('false')['init'],False)
    def test_ambiguous_or_non_boolean_fails(self):
        for value in ('yes','True','1','none',''):
            with self.subTest(value=value),self.assertRaises(BundleError):self.make(value)

if __name__=='__main__':unittest.main()
