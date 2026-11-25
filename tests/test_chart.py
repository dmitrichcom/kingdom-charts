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
        self.assertEqual(service["spec"]["selector"], {"app.kubernetes.io/name": "api", "kingdom.dmitrich.com/stack": "example-app"})
        self.assertEqual(service["spec"]["ports"][0]["targetPort"], "http")
        self.assertEqual(self.resources["Service", "database"]["spec"]["clusterIP"], "None")
        self.assertEqual(self.resources["ConfigMap", "example-settings"]["data"]["settings.json"], '{"enabled":true}')

    def test_network_membership_is_native_policy_and_explicit_docker_input(self):
        policy = self.resources["NetworkPolicy", "worker-connectivity"]["spec"]
        self.assertEqual(policy["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["podSelector"], {"matchLabels": {"app.kubernetes.io/name": "worker", "kingdom.dmitrich.com/stack": "example-app"}})
        peer = {"podSelector": {"matchLabels": {"kingdom.dmitrich.com/stack": "example-app", "kingdom.dmitrich.com/network-code": "true"}}}
        self.assertEqual(policy["ingress"], [{"from": [peer]}])
        self.assertEqual(policy["egress"], [{"to": [peer]}])
        self.assertEqual(self.resources["NetworkPolicy", "api-connectivity"]["spec"]["egress"], [{}])
        template = self.resources["Deployment", "worker"]["spec"]["template"]
        self.assertEqual(template["metadata"]["labels"]["kingdom.dmitrich.com/network-code"], "true")
        self.assertEqual(json.loads(template["metadata"]["annotations"]["kingdom.dmitrich.com/compose-networks"]), {"code": {"internal": True}})

    def render_telemetry(self, *overrides, success=True):
        command = ["helm", "template", "example", "charts/kingdom-workload", "-f", "tests/workloads.yaml", *overrides]
        result = subprocess.run(command, capture_output=True, text=True)
        if not success:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return {(doc["kind"], doc["metadata"]["name"]): doc for doc in yaml.safe_load_all(result.stdout) if doc}

    def test_trace_opt_in_adds_only_endpoint_and_protocol_and_reuses_host_binding(self):
        docs = self.render_telemetry("--set", "workloads.api.telemetry.traces=true")
        pod = docs["Deployment", "api"]["spec"]["template"]
        env = {v["name"]: v["value"] for v in pod["spec"]["containers"][0]["env"]}
        self.assertEqual(env, {
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://otel.kingdom.internal:4318/v1/traces",
            "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
        })
        annotations = pod["metadata"]["annotations"]
        self.assertEqual(json.loads(annotations["kingdom.dmitrich.com/extra-hosts"]), ["otel.kingdom.internal=host-gateway"])
        self.assertEqual(json.loads(annotations["kingdom.dmitrich.com/compose-networks"]), {"backend": {"internal": True}, "code": {"internal": True}, "outbound": {"internal": False}})
        worker = docs["Deployment", "worker"]["spec"]["template"]
        self.assertNotIn("env", worker["spec"]["containers"][0])
        self.assertNotIn("kingdom.dmitrich.com/extra-hosts", worker["metadata"]["annotations"])

    def test_trace_opt_in_refuses_internal_only_and_host_network(self):
        self.assertIn("outbound", self.render_telemetry("--set", "workloads.worker.telemetry.traces=true", success=False))
        self.assertIn("hostNetwork", self.render_telemetry("--set", "workloads.api.telemetry.traces=true", "--set", "workloads.api.podSpec.hostNetwork=true", success=False))

    def test_trace_opt_in_preserves_existing_mapping_and_rejects_conflict(self):
        key = r"workloads.api.podAnnotations.kingdom\.dmitrich\.com/extra-hosts"
        docs = self.render_telemetry("--set", "workloads.api.telemetry.traces=true", "--set-string", key + r'=\{"existing.internal":"host-gateway"\}')
        hosts = json.loads(docs["Deployment", "api"]["spec"]["template"]["metadata"]["annotations"]["kingdom.dmitrich.com/extra-hosts"])
        self.assertEqual(set(hosts), {"existing.internal=host-gateway", "otel.kingdom.internal=host-gateway"})
        self.assertIn("telemetry", self.render_telemetry("--set", "workloads.api.telemetry.traces=true", "--set-string", key + r'=\{"otel.kingdom.internal":"192.0.2.1"\}', success=False))

    def test_bad_kind_and_undeclared_network_are_rejected(self):
        for args in (["--set", "workloads.api.kind=DaemonSet"], ["--set", "workloads.worker.networks[0]=missing"]):
            result = subprocess.run(["helm", "template", "example", "charts/kingdom-workload", "-f", "tests/workloads.yaml", *args], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
