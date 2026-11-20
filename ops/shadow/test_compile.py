"""Contract tests for the offline Helm/dekube to Kingdom release compiler."""
import json
import tempfile
import unittest
from pathlib import Path

from compile import BundleError, compile_bundle, semantic_diff

DIGEST = "ghcr.io/dmitrichcom/remote-station@sha256:" + "a" * 64


def sample_deployment():
    return {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": "gateway"},
        "spec": {"replicas": 1, "template": {
            "spec": {
                "terminationGracePeriodSeconds": 15,
                "securityContext": {"runAsUser": 65532, "runAsGroup": 65532},
                "volumes": [
                    {"name": "state", "persistentVolumeClaim": {"claimName": "state"}},
                    {"name": "key", "secret": {"secretName": "router-public", "items": [{"key": "key", "path": "router-public"}]}},
                ],
                "containers": [{
                    "name": "gateway", "image": DIGEST,
                    "ports": [{"containerPort": 8090, "hostPort": 18082, "hostIP": "192.0.2.44"}],
                    "env": [{"name": "VALUE", "value": "abc"}, {"name": "MAX_UPLOAD_FILE_MIB", "value": "120"}],
                    "volumeMounts": [
                        {"name": "state", "mountPath": "/state"},
                        {"name": "key", "mountPath": "/secrets/router-public", "subPath": "router-public", "readOnly": True},
                    ],
                    "securityContext": {"readOnlyRootFilesystem": True,
                                        "allowPrivilegeEscalation": False,
                                        "capabilities": {"drop": ["ALL"]}},
                    "resources": {"limits": {"memory": "160M", "cpu": "250m"}},
                    "readinessProbe": {"exec": {"command": ["/gateway", "healthcheck"]},
                                       "periodSeconds": 30, "timeoutSeconds": 5,
                                       "initialDelaySeconds": 30, "failureThreshold": 3},
                }],
            },
            "metadata": {"annotations": {
                "kingdom.dmitrich.com/restart": "unless-stopped",
                "kingdom.dmitrich.com/pids-limit": "48",
                "kingdom.dmitrich.com/compose-env-defaults": json.dumps(["VALUE", "MAX_UPLOAD_FILE_MIB"]),
                "kingdom.dmitrich.com/logging": '{"driver":"json-file","options":{"max-size":"5m","max-file":"2"}}',
            }},
        }},
    }


def sample_manifest():
    return {"schema_version": 1, "stacks": [{
        "id": "stations-gateway", "compose_files": ["compose.yaml"],
        "runtime_files": [], "image_variables": {"STATIONS_GATEWAY_IMAGE": "ghcr.io/dmitrichcom/remote-station"},
        "secret_files": {"router_public": "secrets/router-public"},
        "secret_env": ["MAX_UPLOAD_FILE_MIB"], "persistent_dirs": ["state"]
    }]}


class CompileTests(unittest.TestCase):
    def compile(self, manifests=None, generated=None, descriptor=None):
        with tempfile.TemporaryDirectory() as td:
            result = compile_bundle(
                manifests=[sample_deployment()] if manifests is None else manifests,
                generated=generated if generated is not None else {"services": {"gateway": {"image": DIGEST, "restart": "always"}}},
                descriptor=descriptor if descriptor is not None else sample_manifest(),
                output=Path(td),
            )
            return result, sorted(str(p.relative_to(td)) for p in Path(td).rglob('*') if p.is_file())

    def test_reuses_generated_workload_and_preserves_full_compose_contract(self):
        compose, paths = self.compile()
        svc = compose["services"]["gateway"]
        self.assertEqual(svc["image"], DIGEST)
        self.assertEqual(svc["user"], "65532:65532")
        self.assertEqual(svc["cap_drop"], ["ALL"])
        self.assertTrue(svc["read_only"])
        self.assertEqual(svc["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(svc["pids_limit"], 48)
        self.assertEqual(svc["mem_limit"], "160m")
        self.assertEqual(svc["cpus"], 0.25)
        self.assertEqual(svc["stop_grace_period"], "15s")
        self.assertEqual(svc["ports"], [{"host_ip": "192.0.2.44", "mode": "ingress", "protocol": "tcp", "published": "18082", "target": 8090}])
        self.assertEqual(svc["environment"]["VALUE"], "${VALUE:-abc}")
        self.assertEqual(svc["restart"], "unless-stopped")
        self.assertEqual(svc["healthcheck"]["test"], ["CMD", "/gateway", "healthcheck"])
        self.assertEqual(svc["healthcheck"]["start_period"], "30s")
        self.assertEqual(len(svc["volumes"]), 2)
        self.assertIn("deploy/kingdom-runtime.json", paths)
        self.assertIn("stacks/stations-gateway/compose.yaml", paths)

    def test_unpinned_image_fails_closed(self):
        obj = sample_deployment()
        obj["spec"]["template"]["spec"]["containers"][0]["image"] = "nginx:latest"
        with self.assertRaisesRegex(BundleError, "digest"):
            self.compile(manifests=[obj])

    def test_absent_secret_contract_fails(self):
        with self.assertRaisesRegex(BundleError, "secret"):
            self.compile(descriptor={**sample_manifest(), "stacks": [{**sample_manifest()["stacks"][0], "secret_files": {}}]})

    def test_configmap_is_bundled_not_exposed_as_secret(self):
        dep = sample_deployment()
        spec = dep["spec"]["template"]["spec"]
        spec["volumes"].append({"name": "app-config", "configMap": {"name": "app-config"}})
        spec["containers"][0]["volumeMounts"].append({"name": "app-config", "mountPath": "/config"})
        cm = {"kind": "ConfigMap", "metadata": {"name": "app-config"}, "data": {"settings.json": '{"enabled":true}'}}
        with tempfile.TemporaryDirectory() as td:
            compose = compile_bundle(
                manifests=[dep, cm],
                generated={"services": {"gateway": {"image": DIGEST}}},
                descriptor=sample_manifest(), output=Path(td))
            self.assertEqual((Path(td) / "stacks/stations-gateway/files/configmaps/app-config/settings.json").read_text(), '{"enabled":true}')
            self.assertIn("${KINGDOM_RELEASE_ROOT:?}/files/configmaps/app-config", compose["services"]["gateway"]["volumes"][-1]["source"])

    def test_unknown_pod_volume_kind_fails(self):
        obj = sample_deployment()
        spec = obj["spec"]["template"]["spec"]
        spec["volumes"].append({"name": "unsupported", "hostPath": {"path": "/etc"}})
        spec["containers"][0]["volumeMounts"].append({"name": "unsupported", "mountPath": "/data"})
        with self.assertRaisesRegex(BundleError, "unsupported"):
            self.compile(manifests=[obj])

    def test_semantic_diff_detects_security_regression(self):
        first, _ = self.compile()
        second = json.loads(json.dumps(first))
        second["services"]["gateway"]["cap_drop"] = []
        self.assertIn("cap_drop", "\n".join(semantic_diff(first, second)))


if __name__ == '__main__':
    unittest.main()
