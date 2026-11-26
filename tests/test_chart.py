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

    def test_workload_identity_needs_no_platform_annotations(self):
        for (kind, name), resource in self.resources.items():
            if kind in {"Deployment", "StatefulSet", "Job"}:
                with self.subTest(kind=kind, name=name):
                    self.assertNotIn("kingdom.dmitrich.com/stack", resource["metadata"].get("annotations", {}))
                    self.assertIn("kingdom.dmitrich.com/stack", resource["metadata"]["labels"])

    def test_service_and_configmap_remain_kubernetes_resources(self):
        service = self.resources["Service", "api"]
        self.assertEqual(service["spec"]["selector"], {"app.kubernetes.io/name": "api", "kingdom.dmitrich.com/stack": "example-app"})
        self.assertEqual(service["spec"]["ports"][0]["targetPort"], "http")
        self.assertEqual(self.resources["Service", "database"]["spec"]["clusterIP"], "None")
        self.assertIs(self.resources["Service", "database"]["spec"]["publishNotReadyAddresses"], True)
        self.assertEqual(self.resources["ConfigMap", "example-settings"]["data"]["settings.json"], '{"enabled":true}')

    def test_authored_native_policies_preserve_peer_selectors_and_namespace(self):
        policy = self.resources["NetworkPolicy", "worker-connectivity"]["spec"]
        self.assertEqual(policy["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["podSelector"], {"matchLabels": {"app.kubernetes.io/name": "worker", "kingdom.dmitrich.com/stack": "example-app"}})
        peer = {"podSelector": {"matchLabels": {"kingdom.dmitrich.com/stack": "example-app", "app.kubernetes.io/name": "api"}}}
        self.assertEqual(policy["ingress"], [{"from": [peer]}])
        self.assertEqual(policy["egress"], [{"to": [peer]}])
        self.assertEqual(self.resources["NetworkPolicy", "api-connectivity"]["spec"]["egress"], [{}])
        for name in ("worker-connectivity", "api-connectivity"):
            self.assertEqual(self.resources["NetworkPolicy", name]["metadata"]["namespace"], "test-environment")

    def test_native_policy_port_semantics_remain_an_adapter_decision(self):
        docs = self.render_telemetry("--set", "resources[0].spec.ingress[0].ports[0].port=8081",
                                     "--set", "resources[0].spec.ingress[0].ports[0].protocol=TCP")
        self.assertEqual(docs["NetworkPolicy", "worker-connectivity"]["spec"]["ingress"][0]["ports"],
                         [{"port": 8081, "protocol": "TCP"}])

    def render_telemetry(self, *overrides, success=True):
        command = ["helm", "template", "example", "charts/kingdom-workload", "-f", "tests/workloads.yaml", *overrides]
        result = subprocess.run(command, capture_output=True, text=True)
        if not success:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return {(doc["kind"], doc["metadata"]["name"]): doc for doc in yaml.safe_load_all(result.stdout) if doc}

    def test_trace_opt_in_adds_standard_environment_without_docker_annotations(self):
        docs = self.render_telemetry("--set", "workloads.api.telemetry.traces=true")
        pod = docs["Deployment", "api"]["spec"]["template"]
        env = {v["name"]: v["value"] for v in pod["spec"]["containers"][0]["env"]}
        self.assertEqual(env, {
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://otel.kingdom.internal:4318/v1/traces",
            "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
        })
        annotations = pod["metadata"]["annotations"]
        self.assertNotIn("kingdom.dmitrich.com/extra-hosts", annotations)
        worker = docs["Deployment", "worker"]["spec"]["template"]
        self.assertNotIn("env", worker["spec"]["containers"][0])
        self.assertNotIn("kingdom.dmitrich.com/extra-hosts", worker["metadata"]["annotations"])

    def test_trace_opt_in_keeps_policy_validation_in_the_runtime_adapter(self):
        docs = self.render_telemetry("--set", "workloads.worker.telemetry.traces=true")
        self.assertEqual(docs["NetworkPolicy", "worker-connectivity"]["spec"],
                         self.resources["NetworkPolicy", "worker-connectivity"]["spec"])
        self.assertIn("hostNetwork", self.render_telemetry("--set", "workloads.api.telemetry.traces=true", "--set", "workloads.api.podSpec.hostNetwork=true", success=False))

    def test_trace_opt_in_preserves_native_host_aliases(self):
        docs = self.render_telemetry("--set", "workloads.api.telemetry.traces=true",
                                     "--set", "workloads.api.podSpec.hostAliases[0].ip=192.0.2.10",
                                     "--set", "workloads.api.podSpec.hostAliases[0].hostnames[0]=database.example.test")
        pod = docs["Deployment", "api"]["spec"]["template"]
        self.assertEqual(pod["spec"]["hostAliases"], [{"ip": "192.0.2.10", "hostnames": ["database.example.test"]}])
        self.assertNotIn("kingdom.dmitrich.com/extra-hosts", pod["metadata"].get("annotations", {}))

    def test_trace_transport_cannot_conflict_with_product_environment(self):
        err = self.render_telemetry("--set", "workloads.api.telemetry.traces=true", "--set", "workloads.api.podSpec.containers[0].env[0].name=OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "--set", "workloads.api.podSpec.containers[0].env[0].value=https://wrong.example/v1/traces", success=False)
        self.assertIn("owns transport settings", err)

    def test_trace_opt_out_and_invalid_values(self):
        docs = self.render_telemetry("--set", "workloads.api.telemetry.traces=false")
        pod = docs["Deployment", "api"]["spec"]["template"]
        self.assertNotIn("env", pod["spec"]["containers"][0])
        self.assertNotIn("kingdom.dmitrich.com/extra-hosts", pod["metadata"]["annotations"])
        self.render_telemetry("--set-string", "workloads.api.telemetry.traces=true", success=False)

    def test_invalid_workload_kind_and_conflicting_service_selector_are_rejected(self):
        for args in (["--set", "workloads.api.kind=DaemonSet"], ["--set", "workloads.api.service.selector.app=foreign"]):
            result = subprocess.run(["helm", "template", "example", "charts/kingdom-workload", "-f", "tests/workloads.yaml", *args], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
