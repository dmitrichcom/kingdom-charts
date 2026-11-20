"""Behavioral contract of tag resolution for single- and multi-image releases."""
import unittest
from pin_images import pin


class PinImagesTests(unittest.TestCase):
    def test_pins_all_images_at_one_version(self):
        docs=[{'kind':'Deployment','spec':{'template':{'spec':{'containers':[
            {'image':'ghcr.io/a/primary:v1.2.3'},
            {'image':'ghcr.io/a/worker:v1.2.3'},
        ]}}}}]
        calls=[]
        def resolve(ref):
            calls.append(ref)
            return 'sha256:'+'a'*64
        result,refs=pin(docs,'v1.2.3',resolve)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(refs),2)
        self.assertTrue(result[0]['spec']['template']['spec']['containers'][1]['image'].endswith('@sha256:'+'a'*64))

    def test_mixed_versions_and_mutable_tags_fail_without_registry_call(self):
        for ref in ['ghcr.io/a/x:latest','ghcr.io/a/x:v1.2.4','registry.org/a/x:v1.2.3','ghcr.io/a/x@sha256:'+'a'*64]:
            with self.subTest(ref=ref):
                docs=[{'kind':'Deployment','spec':{'template':{'spec':{'containers':[{'image':ref}]}}}}]
                with self.assertRaises(ValueError):pin(docs,'v1.2.3',lambda _:self.fail('unexpected registry call'))

    def test_empty_workload_and_invalid_digest_fail(self):
        with self.assertRaises(ValueError):pin([{'kind':'ConfigMap'}],'v1.2.3',lambda _:self.fail('unexpected'))
        with self.assertRaises(ValueError):pin([{'kind':'Pod','spec':{'containers':[{'image':'ghcr.io/a/x:v1.2.3'}]}}],'v1.2.3',lambda _:'bad')


if __name__ == '__main__':
    unittest.main()
