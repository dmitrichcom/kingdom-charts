"""Docker writable temporary directory behaviour from native Kubernetes emptyDir."""
import json
from pathlib import Path
import tempfile
import unittest

from compile import BundleError, compile_bundle
from test_compile import DIGEST, sample_deployment, sample_manifest


class EmptyDirContract(unittest.TestCase):
    def render(self, *, volume, mount):
        dep = sample_deployment()
        pod = dep['spec']['template']['spec']
        pod['volumes'].append(volume)
        pod['containers'][0]['volumeMounts'].append(mount)
        with tempfile.TemporaryDirectory() as td:
            return compile_bundle(manifests=[dep],
                                  generated={'services': {'gateway': {'image': DIGEST}}},
                                  descriptor=sample_manifest(), output=Path(td))

    def test_bounded_memory_emptydir_is_a_writable_docker_tmpfs(self):
        result = self.render(volume={'name': 'scratch', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '192Mi'}},
                             mount={'name': 'scratch', 'mountPath': '/tmp'})
        service = result['services']['gateway']
        self.assertTrue(service['read_only'])
        self.assertEqual(service['tmpfs'], ['/tmp:size=201326592,mode=1777,noexec,nosuid,nodev'])
        self.assertFalse(any('/tmp' == item['target'] for item in service['volumes']))

    def test_invalid_emptydir_rejected(self):
        for volume in ({'name': 'scratch', 'emptyDir': {'medium': 'Disk'}},
                       {'name': 'scratch', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '0Mi'}},
                       {'name': 'scratch', 'emptyDir': {}}):
            with self.subTest(volume=volume), self.assertRaises(BundleError):
                self.render(volume=volume, mount={'name': 'scratch', 'mountPath': '/tmp'})

    def test_emptydir_cannot_be_a_readonly_mount_or_subpath(self):
        volume = {'name': 'scratch', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '192Mi'}}
        for mount in ({'name': 'scratch', 'mountPath': '/tmp', 'subPath': 'sub'},
                      {'name': 'scratch', 'mountPath': '/tmp', 'readOnly': True}):
            with self.subTest(mount=mount), self.assertRaises(BundleError):
                self.render(volume=volume, mount=mount)
