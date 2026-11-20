#!/usr/bin/env python3
"""Compile an already rendered Kubernetes + dekube Compose model to a Kingdom OCI runtime bundle.

All rendering/conversion is performed in GitHub Actions. No Kubernetes, Helm,
Python, or converter runs during VPS activation. Secrets are *references only*:
actual values remain in Kingdom's existing age-encrypted secret envelope.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

PREFIX = "kingdom.dmitrich.com/"
PINNED_IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")
SAFE_REL = re.compile(r"^[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALLOWED_KINDS = {"Deployment", "Service", "PersistentVolumeClaim", "ConfigMap", "Namespace"}


class BundleError(ValueError):
    """Fail-closed Kubernetes -> Docker compatibility or bundle validation error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleError(message)


def namespaced_path(value: str) -> str:
    require(isinstance(value, str) and bool(SAFE_REL.fullmatch(value)) and
            all(p not in {".", ".."} for p in value.split("/")),
            f"unsafe relative path: {value!r}")
    require(not any(part.startswith(".env") or part.endswith((".pem", ".key", ".p12", ".pfx"))
                    for part in value.split("/")), f"forbidden runtime file path: {value!r}")
    return value


def _annotations(deployment: dict) -> dict:
    return (((deployment.get("spec") or {}).get("template") or {}).get("metadata") or {}).get("annotations") or {}


def _annotation_json(annotations: dict, name: str, default):
    value = annotations.get(PREFIX + name)
    if value is None:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError) as exc:
        raise BundleError(f"invalid annotation {name}: {exc}") from exc


def _int_annotation(annotations: dict, name: str) -> int | None:
    value = annotations.get(PREFIX + name)
    if value is None:
        return None
    require(re.fullmatch(r"[1-9][0-9]*", str(value)) is not None, f"invalid {name}")
    return int(value)


def _k8s_cpu(raw) -> float:
    require(isinstance(raw, str), "CPU limit must be a Kubernetes quantity string")
    try:
        cpus = Decimal(raw[:-1]) / 1000 if raw.endswith("m") else Decimal(raw)
    except InvalidOperation as exc:
        raise BundleError(f"invalid CPU limit: {raw!r}") from exc
    require(cpus > 0 and cpus <= 128, "CPU limit out of range")
    return float(cpus)


def _k8s_memory(raw) -> str:
    require(isinstance(raw, str), "memory limit must be a Kubernetes quantity string")
    # Docker Compose's 'm' suffix means decimal MB. Kubernetes's 'M' is
    # decimal too, whereas 'Mi' is binary; never silently change units.
    match = re.fullmatch(r"([1-9][0-9]*)(M|Mi|G|Gi)", raw)
    require(match is not None, f"unsupported memory quantity: {raw!r}")
    n, unit = int(match.group(1)), match.group(2)
    return {"M": f"{n}m", "Mi": str(n * 2**20),
            "G": f"{n}g", "Gi": str(n * 2**30)}[unit]


def _environment(container: dict, annotations: dict) -> dict:
    fallback = _annotation_json(annotations, "compose-env-defaults", [])
    require(isinstance(fallback, list) and all(isinstance(k, str) and ENV_KEY.fullmatch(k) for k in fallback)
            and len(set(fallback)) == len(fallback), "invalid compose-env-defaults annotation")
    env = {}
    for value in container.get("env") or []:
        key = value.get("name")
        require(isinstance(key, str) and ENV_KEY.fullmatch(key), f"invalid environment name: {key!r}")
        require(key not in env, f"duplicate environment variable: {key}")
        require("valueFrom" not in value, f"Kubernetes valueFrom requires explicit converter support: {key}")
        raw = value.get("value", "")
        require(isinstance(raw, str), f"non-string Kubernetes env: {key}")
        require("${" not in raw, f"Compose interpolation is forbidden in Kubernetes env: {key}")
        env[key] = raw
    for key in fallback:
        require(key in env, f"missing Compose env default: {key}")
        require("}" not in env[key] and "\n" not in env[key], f"unsafe Compose env default: {key}")
        env[key] = "${" + key + ":-" + env[key] + "}"
    return env


def _read_pod(deployment: dict) -> tuple[dict, dict]:
    template = ((deployment.get("spec") or {}).get("template") or {})
    pod = template.get("spec") or {}
    containers = pod.get("containers") or []
    require(len(containers) == 1, "only a single container per Kubernetes Deployment is supported")
    require((deployment.get("spec") or {}).get("replicas", 1) == 1, "replicas must be 1 in the Docker target")
    return pod, containers[0]


def _security(compose: dict, pod: dict, container: dict, annotations: dict) -> None:
    pod_sec = pod.get("securityContext") or {}
    sec = container.get("securityContext") or {}
    user = sec.get("runAsUser", pod_sec.get("runAsUser"))
    group = sec.get("runAsGroup", pod_sec.get("runAsGroup"))
    if user is not None:
        require(isinstance(user, int) and user >= 0, "invalid runAsUser")
        require(group is None or (isinstance(group, int) and group >= 0), "invalid runAsGroup")
        compose["user"] = f"{user}:{group}" if group is not None else str(user)
    if "readOnlyRootFilesystem" in sec:
        compose["read_only"] = bool(sec["readOnlyRootFilesystem"])
    if "allowPrivilegeEscalation" in sec:
        if sec["allowPrivilegeEscalation"] is False:
            compose["security_opt"] = ["no-new-privileges:true"]
        else:
            require(sec["allowPrivilegeEscalation"] is True, "invalid allowPrivilegeEscalation")
    caps = sec.get("capabilities") or {}
    if caps.get("drop"):
        compose["cap_drop"] = list(caps["drop"])
    if caps.get("add"):
        compose["cap_add"] = list(caps["add"])
    if sec.get("privileged"):
        compose["privileged"] = True
    pids = _int_annotation(annotations, "pids-limit")
    if pids is not None:
        compose["pids_limit"] = pids


def _resources(compose: dict, container: dict) -> None:
    limits = ((container.get("resources") or {}).get("limits") or {})
    require(set(limits) <= {"memory", "cpu"}, f"unsupported Kubernetes resource limit: {set(limits)-{'memory','cpu'}}")
    compose.pop("deploy", None)  # dekube emits deploy.resources; our runtime uses direct Compose limits
    if "memory" in limits:
        compose["mem_limit"] = _k8s_memory(limits["memory"])
    if "cpu" in limits:
        compose["cpus"] = _k8s_cpu(limits["cpu"])


def _ports(compose: dict, container: dict) -> None:
    ports = []
    for p in container.get("ports") or []:
        internal = p.get("containerPort")
        require(isinstance(internal, int) and 1 <= internal <= 65535, "invalid containerPort")
        proto = (p.get("protocol") or "TCP").lower()
        require(proto in ("tcp", "udp"), f"unsupported protocol: {proto}")
        if "hostPort" in p:
            published = p["hostPort"]
            require(isinstance(published, int) and 1 <= published <= 65535, "invalid hostPort")
            host = p.get("hostIP")
            ports.append({
                **({"host_ip": host} if host else {}),
                "mode": "ingress", "protocol": proto,
                "published": str(published), "target": internal,
            })
    compose.pop("ports", None)  # exclude accidental dekube Service port publications
    if ports:
        compose["ports"] = ports


def _health(compose: dict, container: dict, pod: dict) -> None:
    probe = container.get("readinessProbe") or container.get("livenessProbe")
    require(isinstance(probe, dict) and (probe.get("exec") or {}).get("command"),
            "a persistent Docker service requires an exec healthcheck (readinessProbe)")
    command = probe["exec"]["command"]
    require(isinstance(command, list) and len(command) > 0 and all(isinstance(s, str) and s for s in command),
            "invalid exec healthcheck")
    # Kubernetes readiness and Compose start-period are not identical: this
    # mapping is an explicit target policy, exercised by parity tests.
    compose["healthcheck"] = {
        "test": ["CMD", *command],
        "interval": f'{probe.get("periodSeconds", 10)}s',
        "timeout": f'{probe.get("timeoutSeconds", 1)}s',
        "start_period": f'{probe.get("initialDelaySeconds", 0)}s',
        "retries": probe.get("failureThreshold", 3),
    }
    grace = pod.get("terminationGracePeriodSeconds")
    if grace is not None:
        require(isinstance(grace, int) and grace >= 0, "invalid terminationGracePeriodSeconds")
        compose["stop_grace_period"] = f"{grace}s"


def _volumes(compose: dict, pod: dict, container: dict, stack: dict,
             configmaps: dict, files_root: Path) -> None:
    sources = {v.get("name"): v for v in pod.get("volumes") or []}
    result = []
    expected_secrets = {namespaced_path(path) for path in (stack.get("secret_files") or {}).values()}
    seen_secrets = set()
    seen_persistent = set()
    for vm in container.get("volumeMounts") or []:
        volume = sources.get(vm.get("name"))
        require(volume is not None, f"unknown Kubernetes volumeMount: {vm.get('name')}")
        target = vm.get("mountPath")
        require(isinstance(target, str) and target.startswith("/"), f"invalid mountPath: {target}")
        mount = {"type": "bind", "target": target, "bind": {"create_host_path": False}}
        if "persistentVolumeClaim" in volume:
            claim = (volume["persistentVolumeClaim"] or {}).get("claimName")
            require(claim in (stack.get("persistent_dirs") or []), f"PVC {claim!r} absent from persistent_dirs")
            require(not vm.get("subPath") and not vm.get("readOnly"), "PVC subPath/readOnly needs explicit support")
            mount["source"] = "${KINGDOM_STACK_ROOT:?}/" + claim
            seen_persistent.add(claim)
        elif "secret" in volume:
            secret = volume["secret"] or {}
            require(secret.get("secretName"), "missing Kubernetes secretName")
            filename = target.rsplit("/", 1)[-1]
            path = "secrets/" + filename
            require(path in expected_secrets, f"secret {path!r} missing from Kingdom secret_files contract")
            items = secret.get("items") or []
            require(any(item.get("path") == filename for item in items),
                    f"secret {path!r} missing explicit item mapping")
            require(vm.get("readOnly", False) and vm.get("subPath") == filename,
                    f"secret {path!r} must use readOnly subPath to avoid directory mount")
            mount["source"] = "${KINGDOM_STACK_ROOT:?}/" + path
            mount["read_only"] = True
            seen_secrets.add(path)
        elif "configMap" in volume:
            cm = (volume["configMap"] or {})
            name = cm.get("name")
            require(name in configmaps, f"missing ConfigMap: {name!r}")
            data = configmaps[name].get("data") or {}
            require(isinstance(data, dict) and data, f"empty ConfigMap: {name}")
            require(not vm.get("subPath"), "ConfigMap subPath needs explicit support")
            root = f"configmaps/{name}"
            for key, value in data.items():
                rel = namespaced_path(f"{root}/{key}")
                require(isinstance(value, str), f"ConfigMap {name} key must contain text")
                dest = files_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(value, encoding="utf-8")
            mount["source"] = "${KINGDOM_RELEASE_ROOT:?}/files/" + root
            mount["read_only"] = True
        else:
            raise BundleError(f"unsupported volume type for {vm.get('name')}: {volume}")
        result.append(mount)
    require(seen_secrets == expected_secrets,
            f"secret contract mismatch: missing {sorted(expected_secrets - seen_secrets)}")
    require(seen_persistent == set(stack.get("persistent_dirs") or []),
            f"persistent mount contract mismatch: {seen_persistent}")
    compose["volumes"] = result


def _ensure_no_plaintext_secret(manifests: list[dict]) -> None:
    for item in manifests:
        kind = item.get("kind")
        require(kind in ALLOWED_KINDS, f"unsupported Kubernetes kind: {kind}")
        if kind == "ConfigMap":
            values = item.get("data") or {}
            require(all(isinstance(v, str) for v in values.values()), "invalid ConfigMap values")
        # Do not accept Secret manifests in rendered bundles, even placeholders.
        # Kubernetes Secrets must be provisioned independently at runtime.


def compile_bundle(*, manifests: list[dict], generated: dict,
                   descriptor: dict, output: Path) -> dict:
    """Compile portable Kube manifests and dekube's service model to a Kingdom bundle tree."""
    _ensure_no_plaintext_secret(manifests)
    require(descriptor.get("schema_version") == 1 and len(descriptor.get("stacks") or []) == 1,
            "expected one Kingdom v1 stack")
    stack = descriptor["stacks"][0]
    stack_id = stack.get("id")
    require(isinstance(stack_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", stack_id), "invalid stack id")
    deps = [obj for obj in manifests if obj["kind"] == "Deployment"]
    require(len(deps) == 1, "exactly one Kubernetes Deployment is supported")
    dep = deps[0]
    name = (dep.get("metadata") or {}).get("name")
    require(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name), "invalid Kubernetes Deployment name")
    pod, container = _read_pod(dep)
    source = generated.get("services") or {}
    require(set(source) == {name}, f"dekube output service mismatch: {sorted(source)} != {name}")
    image = container.get("image")
    require(isinstance(image, str) and PINNED_IMAGE.fullmatch(image), "image must be pinned by GHCR digest")
    require(source[name].get("image") == image, "dekube image differs from Kubernetes image")
    valid_repos = set((stack.get("image_variables") or {}).values())
    require(image.split("@")[0] in valid_repos, "image not declared by Kingdom image_variables")
    configmaps = {(m.get("metadata") or {}).get("name"): m for m in manifests if m["kind"] == "ConfigMap"}
    require(len(configmaps) == len([m for m in manifests if m["kind"] == "ConfigMap"]),
            "duplicate ConfigMap name")
    compose = copy.deepcopy(source[name])
    # The composed source model is authoritative for base workload conversion.
    # Kingdom's compatibility adapter supplies Docker-only semantics missing
    # from upstream dekube, always derived from PodSpec or explicit annotations.
    anns = _annotations(dep)
    # Docker Compose's normalized default network is part of the immutable
    # delivery contract; do not expose generated Kubernetes service aliases.
    compose["networks"] = {"default": None}
    compose["image"] = image
    compose["environment"] = _environment(container, anns)
    compose["restart"] = anns.get(PREFIX + "restart", "always")
    require(compose["restart"] in {"always", "unless-stopped", "on-failure", "no"}, "invalid restart policy")
    _resources(compose, container)
    _security(compose, pod, container, anns)
    _ports(compose, container)
    _health(compose, container, pod)
    logger = _annotation_json(anns, "logging", None)
    if logger is not None:
        require(isinstance(logger, dict) and logger.get("driver") == "json-file", "unsupported logging annotation")
        compose["logging"] = logger
    dest = output / "stacks" / stack_id
    files_root = dest / "files"
    files_root.mkdir(parents=True, exist_ok=True)
    # Preserve all ConfigMap data as concrete OCI files even when a service
    # intentionally does not mount it (e.g. the current mutable stations.json).
    # This allows source inspection and a future separately gated config
    # rollout without changing today's Compose/runtime state semantics.
    for config_name, config in sorted(configmaps.items()):
        require(re.fullmatch(r"[a-z0-9][a-z0-9.-]*", config_name),
                f"unsafe ConfigMap name: {config_name!r}")
        for key, value in sorted((config.get("data") or {}).items()):
            path = files_root / namespaced_path(f"configmaps/{config_name}/{key}")
            require(isinstance(value, str), f"invalid ConfigMap value: {config_name}/{key}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
    _volumes(compose, pod, container, stack, configmaps, files_root)
    require(set(stack.get("secret_env") or []) <= set(compose.get("environment") or {}),
            "secret environment keys absent from Kubernetes env")
    # Never emit a Compose section that builds an image or embeds plaintext secrets.
    require(not any(x in compose for x in ["build", "env_file", "secrets", "configs"]),
            "forbidden build or external secret reference in Compose")
    normalized = {"networks": {"default": {}}, "services": {name: compose}}
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "compose.yaml").write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    manifest_dir = output / "deploy"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "kingdom-runtime.json").write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n")
    return normalized


def semantic_diff(left, right, path: str = "$") -> list[str]:
    """Report precise structural differences; do not silently ignore security fields."""
    if type(left) is not type(right):
        return [f"{path}: {type(left).__name__} != {type(right).__name__}"]
    if isinstance(left, dict):
        changes = []
        for key in sorted(left.keys() | right.keys()):
            dest = f"{path}.{key}"
            if key not in left:
                changes.append(f"{dest}: missing from expected")
            elif key not in right:
                changes.append(f"{dest}: missing from actual")
            else:
                changes.extend(semantic_diff(left[key], right[key], dest))
        return changes
    if isinstance(left, list):
        if len(left) != len(right):
            return [f"{path}: length {len(left)} != {len(right)}"]
        return [d for i, (a, b) in enumerate(zip(left, right)) for d in semantic_diff(a, b, f"{path}[{i}]")]
    return [] if left == right else [f"{path}: {left!r} != {right!r}"]


def expected_with_release_images(expected: dict, actual: dict, descriptor: dict) -> dict:
    """Allow only image *digest* changes within each declared image repository.

    All security options, mounts and other fields still undergo exact parity.
    This is a contract update for SemVer promotions, not a broad diff ignore.
    """
    result = copy.deepcopy(expected)
    allowed = {repository for stack in descriptor.get("stacks", [])
               for repository in (stack.get("image_variables") or {}).values()}
    for name, expected_service in (result.get("services") or {}).items():
        old = expected_service.get("image")
        new = ((actual.get("services") or {}).get(name) or {}).get("image")
        if (isinstance(old, str) and isinstance(new, str)
                and PINNED_IMAGE.fullmatch(old) and PINNED_IMAGE.fullmatch(new)):
            old_repo = old.split("@", 1)[0]
            new_repo = new.split("@", 1)[0]
            if old_repo == new_repo and new_repo in allowed:
                expected_service["image"] = new
    return result


def load_rendered(path: Path) -> list[dict]:
    values = [p for p in yaml.safe_load_all(path.read_text()) if p]
    require(all(isinstance(v, dict) for v in values), "invalid Kubernetes YAML document")
    return values


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rendered", type=Path, required=True)
    p.add_argument("--dekube-compose", type=Path, required=True)
    p.add_argument("--descriptor", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-json", type=Path, help="optional normalized Compose golden contract")
    p.add_argument("--source-revision", default="")
    p.add_argument("--chart-revision", default="")
    p.add_argument("--dekube-sha256", default="")
    args = p.parse_args()
    try:
        manifests = load_rendered(args.rendered)
        model = yaml.safe_load(args.dekube_compose.read_text())
        descriptor = json.loads(args.descriptor.read_text())
        actual = compile_bundle(manifests=manifests, generated=model, descriptor=descriptor, output=args.output)
        if args.expected_json:
            expected = json.loads(args.expected_json.read_text())
            diff = semantic_diff(expected_with_release_images(expected, actual, descriptor), actual)
            if diff:
                raise BundleError("semantic parity failed:\n" + "\n".join(diff[:60]))
        kube_dir = args.output / "kubernetes"
        kube_dir.mkdir(parents=True, exist_ok=True)
        (kube_dir / "manifests.yaml").write_bytes(args.rendered.read_bytes())
        checksums = {}
        for fp in sorted(args.output.rglob("*")):
            if fp.is_file():
                checksums[str(fp.relative_to(args.output))] = hashlib.sha256(fp.read_bytes()).hexdigest()
        (args.output / "sources.lock.json").write_text(json.dumps({
            "schema_version": 1, "environment_revision": args.source_revision,
            "chart_revision": args.chart_revision, "dekube_sha256": args.dekube_sha256,
            "files": checksums}, indent=2, sort_keys=True) + "\n")
        print(f"Compiled {sorted(actual['services'])} to Kingdom OCI runtime tree: {args.output}")
        return 0
    except (BundleError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
