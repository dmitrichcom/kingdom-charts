"""Validate chart behavior using native Kubernetes output, not Compose goldens."""
import json
from pathlib import Path
import subprocess
import unittest

import yaml


class PortableWorkloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["helm", "lint", "charts/kingdom-workload", "-f", "tests/workloads.yaml"], check=True)
        output = subprocess.check_output(["helm", "template", "example", "charts/kingdom-workload", "--namespace", "test-environment", "-f", "tests/workloads.yaml"], text=True)
        cls.resources = {(doc["kind"], doc["metadata"]["name"]): doc for doc in yaml.safe_load_all(output) if doc}

    def test_workload_kinds_and_native_settings(self):
        api = self.resources["Deployment", "api"]
        self.assertEqual(api["spec"]["replicas"], 2)
        self.assertEqual(api["metadata"]["namespace"], "test-environment")
        self.assertEqual(api["spec"]["template"]["spec"]["containers"][0]["image"], "registry.example.test/team/api:v2.3.4")
        worker = self.resources["Deployment", "worker"]["spec"]["template"]["spec"]
        self.assertEqual(worker["runtimeClassName"], "runsc")
        self.assertEqual(worker["containers"][0]["image"], "ghcr.io/example/worker:independent-version")
        self.assertEqual(self.resources["StatefulSet", "database"]["spec"]["serviceName"], "database")
        self.assertEqual(self.resources["Job", "migrate"]["spec"]["backoffLimit"], 0)
        self.assertEqual(self.resources["Job", "migrate"]["spec"]["template"]["spec"]["restartPolicy"], "Never")

    def test_service_and_configmap_remain_kubernetes_resources(self):
        service = self.resources["Service", "api"]
        self.assertEqual(service["spec"]["selector"], {"app.kubernetes.io/name": "api"})
        self.assertEqual(service["spec"]["ports"][0]["targetPort"], "http")
        self.assertEqual(self.resources["Service", "database"]["spec"]["clusterIP"], "None")
        self.assertEqual(self.resources["ConfigMap", "example-settings"]["data"]["settings.json"], '{"enabled":true}')

    def test_network_membership_is_native_policy_and_explicit_docker_input(self):
        policy = self.resources["NetworkPolicy", "worker-connectivity"]["spec"]
        self.assertEqual(policy["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["podSelector"], {"matchLabels": {"app.kubernetes.io/name": "worker"}})
        self.assertEqual(policy["ingress"], [{"from": [{"podSelector": {"matchLabels": {"kingdom.dmitrich.com/network-code": "true"}}}]}])
        self.assertEqual(policy["egress"], [{"to": [{"podSelector": {"matchLabels": {"kingdom.dmitrich.com/network-code": "true"}}}]}])
        self.assertEqual(self.resources["NetworkPolicy", "api-connectivity"]["spec"]["egress"], [{}])
        template = self.resources["Deployment", "worker"]["spec"]["template"]
        self.assertEqual(template["metadata"]["labels"]["kingdom.dmitrich.com/network-code"], "true")
        self.assertEqual(json.loads(template["metadata"]["annotations"]["kingdom.dmitrich.com/compose-networks"]), {"code": {"internal": True}})

    def test_bad_kind_and_undeclared_network_are_rejected(self):
        for args in (["--set", "workloads.api.kind=DaemonSet"], ["--set", "workloads.worker.networks[0]=missing"]):
            result = subprocess.run(["helm", "template", "example", "charts/kingdom-workload", "-f", "tests/workloads.yaml", *args], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
